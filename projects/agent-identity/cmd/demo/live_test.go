package main

import (
	"bytes"
	"context"
	"errors"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"sync"
	"testing"

	"github.com/spiffe/go-spiffe/v2/bundle/jwtbundle"
	"github.com/spiffe/go-spiffe/v2/spiffeid"
	"github.com/spiffe/go-spiffe/v2/svid/jwtsvid"

	"github.com/travism26/harness-lab/projects/agent-identity/internal/standin/model"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/standin/workload"
)

const question = "Can Tom approve invoices?"

func keys(kv map[string]string) func(string) string {
	return func(k string) string { return kv[k] }
}

func runDeps(d deps, args ...string) (stdout, stderr string, code int) {
	var out, errOut bytes.Buffer
	code = runWith(args, &out, &errOut, d)
	return out.String(), errOut.String(), code
}

// The live Model, reached through a stand-in at the provider's API root.

func TestLiveAskUsesAnthropicByDefault(t *testing.T) {
	m := model.New(model.ToolUse("tom", "invoice:approve"))
	defer m.Close()
	d := deps{getenv: keys(map[string]string{"ANTHROPIC_API_KEY": "a-key", "OPENROUTER_API_KEY": "o-key"}), modelBaseURL: m.URL}
	out, errOut, code := runDeps(d, "ask", question, "--live", "--model", "claude-sonnet-5-5")
	if code != 0 {
		t.Fatalf("exit %d: %s", code, errOut)
	}
	if !strings.Contains(out, "\n[model: live · id ") || strings.Contains(out, "stand-in") {
		t.Errorf("footer should say live: %q", out)
	}
	reqs := m.Requests()
	if len(reqs) != 1 {
		t.Fatalf("%d Model requests; want 1", len(reqs))
	}
	h := reqs[0].Header
	if h.Get("x-api-key") != "a-key" || h.Get("anthropic-version") == "" || h.Get("Authorization") != "" {
		t.Errorf("not Anthropic-style auth: %v", h)
	}
	if reqs[0].Body["model"] != "claude-sonnet-5-5" {
		t.Errorf("model = %v", reqs[0].Body["model"])
	}
	if n := strings.Count(errOut, "provider anthropic"); n != 1 {
		t.Errorf("the choice should be printed once, got %d times: %s", n, errOut)
	}
	if strings.Contains(errOut+out, "a-key") {
		t.Error("the key leaked into the output")
	}
}

func TestLiveReadsKeysFromTheEnvFileAndTheProcessOverridesIt(t *testing.T) {
	path := filepath.Join(t.TempDir(), ".env")
	if err := os.WriteFile(path, []byte("ANTHROPIC_API_KEY=file-a\nOPENROUTER_API_KEY=file-o\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	m := model.NewDemo()
	defer m.Close()
	// Only the file has keys: Anthropic by default.
	_, errOut, code := runDeps(deps{getenv: keys(nil), envFile: path, modelBaseURL: m.URL}, "ask", question, "--live")
	if code != 0 || !strings.Contains(errOut, "provider anthropic") {
		t.Fatalf("code=%d stderr=%s", code, errOut)
	}
	if got := m.Requests()[0].Header.Get("X-Api-Key"); got != "file-a" {
		t.Errorf("x-api-key = %q, want the file's key", got)
	}
	// The process environment wins over the file.
	_, _, code = runDeps(deps{getenv: keys(map[string]string{"ANTHROPIC_API_KEY": "proc-a"}), envFile: path, modelBaseURL: m.URL}, "ask", question, "--live")
	if code != 0 {
		t.Fatalf("code=%d", code)
	}
	if got := m.Requests()[1].Header.Get("X-Api-Key"); got != "proc-a" {
		t.Errorf("x-api-key = %q, want the process key", got)
	}
}

func TestLiveWithAnEnvFileThatIsMissingStillNeedsAKey(t *testing.T) {
	_, errOut, code := runDeps(deps{getenv: keys(nil), envFile: filepath.Join(t.TempDir(), "absent")}, "ask", question, "--live")
	if code == 0 || !strings.Contains(errOut, "API_KEY") {
		t.Fatalf("code=%d stderr=%s", code, errOut)
	}
}

func TestLiveProviderFlagPicksOpenRouter(t *testing.T) {
	m := model.New(model.ToolUse("tom", "invoice:approve"))
	defer m.Close()
	d := deps{getenv: keys(map[string]string{"ANTHROPIC_API_KEY": "a-key", "OPENROUTER_API_KEY": "o-key"}), modelBaseURL: m.URL}
	_, errOut, code := runDeps(d, "ask", question, "--live", "--provider", "openrouter")
	if code != 0 {
		t.Fatalf("exit %d: %s", code, errOut)
	}
	reqs := m.Requests()
	if len(reqs) != 1 || reqs[0].Header.Get("Authorization") != "Bearer o-key" || reqs[0].Header.Get("x-api-key") != "" {
		t.Fatalf("not OpenRouter-style auth: %v", reqs)
	}
	if !strings.Contains(errOut, "provider openrouter") {
		t.Errorf("the choice is not printed: %s", errOut)
	}
}

func TestLiveFallsBackToOpenRouterOnlyWithoutAnthropicKey(t *testing.T) {
	m := model.New(model.ToolUse("tom", "invoice:approve"))
	defer m.Close()
	d := deps{getenv: keys(map[string]string{"OPENROUTER_API_KEY": "o-key"}), modelBaseURL: m.URL}
	_, errOut, code := runDeps(d, "ask", question, "--live")
	if code != 0 || !strings.Contains(errOut, "provider openrouter") {
		t.Errorf("exit %d: %s", code, errOut)
	}
}

func TestLiveMissingKeyExitsBeforeAnyRequest(t *testing.T) {
	for _, tc := range []struct {
		name string
		env  map[string]string
		args []string
	}{
		{"neither key", nil, []string{"ask", question, "--live"}},
		{"explicit provider without its key", map[string]string{"OPENROUTER_API_KEY": "o"}, []string{"ask", question, "--live", "--provider", "anthropic"}},
		{"tour", nil, []string{"tour", "--live"}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			m := model.New(model.ToolUse("tom", "invoice:approve"))
			defer m.Close()
			out, errOut, code := runDeps(deps{getenv: keys(tc.env), modelBaseURL: m.URL}, tc.args...)
			if code == 0 {
				t.Fatalf("exit 0; stderr: %s", errOut)
			}
			if len(m.Requests()) != 0 {
				t.Error("a request was made before the key check")
			}
			if out != "" {
				t.Errorf("nothing should have run, stdout: %q", out)
			}
			if !strings.Contains(errOut, "_API_KEY") {
				t.Errorf("stderr should name the missing variable: %s", errOut)
			}
		})
	}
}

func TestLiveUnknownProviderIsBadUsage(t *testing.T) {
	_, _, code := runDeps(deps{getenv: keys(map[string]string{"ANTHROPIC_API_KEY": "k"})}, "ask", question, "--live", "--provider", "gemini")
	if code == 0 {
		t.Error("exit 0 for an unknown provider")
	}
}

func TestTourLiveSendsOnlyTheAskToTheModel(t *testing.T) {
	m := model.New(model.ToolUse("tom", "invoice:approve"))
	defer m.Close()
	d := deps{getenv: keys(map[string]string{"ANTHROPIC_API_KEY": "k"}), modelBaseURL: m.URL}
	out, errOut, code := runDeps(d, "tour", "--live")
	if code != 0 {
		t.Fatalf("exit %d: %s", code, errOut)
	}
	checkLines(t, lookupLines(out), slices.Concat(tokenLines, scriptedLines))
	if len(m.Requests()) != 1 {
		t.Errorf("%d Model requests; want 1", len(m.Requests()))
	}
}

func TestScenariosIgnoreFlagsTheyCannotUse(t *testing.T) {
	// tokens and scripted take no Model: --live needs no key and prints no choice.
	for _, s := range []string{"tokens", "scripted"} {
		out, errOut, code := runDeps(deps{getenv: keys(nil)}, s, "--live")
		if code != 0 || strings.Contains(errOut, "provider") || len(lookupLines(out)) != 3 {
			t.Errorf("%s --live: exit %d, stderr %s", s, code, errOut)
		}
	}
}

func TestStandInRunNeverPrintsAProviderChoice(t *testing.T) {
	_, errOut, code := runDeps(deps{getenv: keys(map[string]string{"ANTHROPIC_API_KEY": "k"})}, "ask", question)
	if code != 0 || strings.Contains(errOut, "provider") {
		t.Errorf("exit %d: %s", code, errOut)
	}
}

// The live Workload API, reached through a stand-in behind the same interfaces.

type fakeSockets struct {
	src *workload.Source

	mu      sync.Mutex
	opened  []string
	fetches map[string]int
	failOn  string
}

type fakeJWTSource struct {
	f      *fakeSockets
	socket string
	wl     *workload.Workload
}

func (s *fakeJWTSource) FetchJWTSVID(ctx context.Context, p jwtsvid.Params) (*jwtsvid.SVID, error) {
	s.f.mu.Lock()
	s.f.fetches[s.socket]++
	s.f.mu.Unlock()
	return s.wl.FetchJWTSVID(ctx, p)
}

func (s *fakeJWTSource) GetJWTBundleForTrustDomain(td spiffeid.TrustDomain) (*jwtbundle.Bundle, error) {
	return s.f.src.GetJWTBundleForTrustDomain(td)
}

func (s *fakeJWTSource) Close() error { return nil }

// open serves a workload by socket name: agent.sock is the permission-agent,
// other.sock the unlisted-agent, anything else (the Warden's) only a bundle.
func (f *fakeSockets) open(_ context.Context, socket string) (jwtSource, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.opened = append(f.opened, socket)
	if socket == f.failOn {
		return nil, errors.New("dial unix " + socket + ": no such file")
	}
	s := &fakeJWTSource{f: f, socket: socket}
	switch {
	case strings.HasSuffix(socket, "agent.sock"):
		s.wl, _ = f.src.Workload(permissionAgent)
	case strings.HasSuffix(socket, "other.sock"):
		s.wl, _ = f.src.Workload(unlistedAgent)
	default:
		s.wl, _ = f.src.Workload(spiffeid.RequireFromString("spiffe://example.com/warden"))
	}
	return s, nil
}

func newFakeSockets(t *testing.T) *fakeSockets {
	t.Helper()
	src, err := workload.New(spiffeid.RequireTrustDomainFromString("example.com"))
	if err != nil {
		t.Fatal(err)
	}
	return &fakeSockets{src: src, fetches: map[string]int{}}
}

func TestSpiffeSocketServesTheAgentAndTheWarden(t *testing.T) {
	f := newFakeSockets(t)
	out, errOut, code := runDeps(deps{openJWT: f.open}, "ask", question, "--spiffe-socket", "/tmp/x/agent.sock", "--spiffe-socket-warden", "/tmp/x/warden.sock")
	if code != 0 {
		t.Fatalf("exit %d: %s", code, errOut)
	}
	if !strings.HasPrefix(out, "Yes. tom holds") || !strings.Contains(out, "[model: stand-in") {
		t.Errorf("reply: %q", out)
	}
	if !slices.Contains(f.opened, "/tmp/x/agent.sock") || !slices.Contains(f.opened, "/tmp/x/warden.sock") {
		t.Errorf("opened %v; want the Agent's and the Warden's sockets", f.opened)
	}
	if f.fetches["/tmp/x/agent.sock"] != 1 || f.fetches["/tmp/x/warden.sock"] != 0 {
		t.Errorf("fetches %v: the Agent fetches once, the Warden never", f.fetches)
	}
}

func TestSpiffeWardenSocketDefaultsBesideTheAgents(t *testing.T) {
	f := newFakeSockets(t)
	_, errOut, code := runDeps(deps{openJWT: f.open}, "ask", question, "--spiffe-socket", "/tmp/agent-identity/agent.sock")
	if code != 0 || !slices.Contains(f.opened, "/tmp/agent-identity/warden.sock") {
		t.Errorf("exit %d, opened %v: %s", code, f.opened, errOut)
	}
}

func TestSpiffeSocketUnreachableExitsNonZero(t *testing.T) {
	f := newFakeSockets(t)
	f.failOn = "/tmp/x/agent.sock"
	runs := filepath.Join(t.TempDir(), "runs")
	out, errOut, code := runDeps(deps{openJWT: f.open}, "tokens", "--spiffe-socket", "/tmp/x/agent.sock", "--out", runs)
	if code == 0 || out != "" || !strings.Contains(errOut, "/tmp/x/agent.sock") {
		t.Errorf("exit %d, stdout %q, stderr %s", code, out, errOut)
	}
	if hint := "spiffecli run --config spiffecli/workloads.toml"; !strings.Contains(errOut, hint) || !strings.Contains(errOut, "projects/agent-identity") {
		t.Errorf("stderr lacks the setup hint: %s", errOut)
	}
	if strings.Contains(errOut, "stand-in") {
		t.Errorf("stderr mentions a stand-in fallback: %s", errOut)
	}
	if _, err := os.Stat(runs); !os.IsNotExist(err) {
		t.Errorf("run directory created: %v", err)
	}
}

func TestTokensUsesTheOtherSocketForThe403(t *testing.T) {
	f := newFakeSockets(t)
	out, errOut, code := runDeps(deps{openJWT: f.open}, "tokens", "--spiffe-socket", "/tmp/x/agent.sock", "--spiffe-socket-other", "/tmp/x/other.sock")
	if code != 0 {
		t.Fatalf("exit %d: %s", code, errOut)
	}
	checkLines(t, lookupLines(out), tokenLines)
	if f.fetches["/tmp/x/other.sock"] != 1 {
		t.Errorf("fetches %v", f.fetches)
	}
}

func TestTokensSkipsThe403WithANoteWithoutTheOtherSocket(t *testing.T) {
	f := newFakeSockets(t)
	out, errOut, code := runDeps(deps{openJWT: f.open}, "tokens", "--spiffe-socket", "/tmp/x/agent.sock")
	if code != 0 {
		t.Fatalf("exit %d: %s", code, errOut)
	}
	checkLines(t, lookupLines(out), tokenLines[:2])
	if !strings.Contains(out+errOut, "skipped") || !strings.Contains(out+errOut, "--spiffe-socket-other") {
		t.Errorf("no skip note: %s%s", out, errOut)
	}
}

func TestFullLiveTour(t *testing.T) {
	f := newFakeSockets(t)
	m := model.New(model.ToolUse("tom", "invoice:approve"))
	defer m.Close()
	d := deps{getenv: keys(map[string]string{"ANTHROPIC_API_KEY": "k"}), modelBaseURL: m.URL, openJWT: f.open}
	out, errOut, code := runDeps(d, "tour", "--live", "--spiffe-socket", "/tmp/x/agent.sock", "--spiffe-socket-other", "/tmp/x/other.sock")
	if code != 0 {
		t.Fatalf("exit %d: %s", code, errOut)
	}
	checkLines(t, lookupLines(out), slices.Concat(tokenLines, scriptedLines))
	if !strings.Contains(out, "== ask\nYes. tom holds") || !strings.Contains(out, "[model: live · id ") {
		t.Errorf("tour output: %s", out)
	}
	if len(m.Requests()) != 1 {
		t.Errorf("%d Model requests; want 1 (only ask uses the Model)", len(m.Requests()))
	}
}
