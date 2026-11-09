package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/spiffe/go-spiffe/v2/bundle/jwtbundle"
	"github.com/spiffe/go-spiffe/v2/spiffeid"
	"github.com/spiffe/go-spiffe/v2/svid/jwtsvid"

	"github.com/travism26/harness-lab/projects/agent-identity/internal/broker"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/modelrequest"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/standin/model"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/standin/workload"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/wire"
)

type syncBuffer struct {
	mu sync.Mutex
	b  bytes.Buffer
}

func (s *syncBuffer) Write(p []byte) (int, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.b.Write(p)
}

func (s *syncBuffer) String() string {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.b.String()
}

func jwtsvidParams(aud string) jwtsvid.Params { return jwtsvid.Params{Audience: aud} }

func keys(kv map[string]string) func(string) string {
	return func(k string) string { return kv[k] }
}

// fakeBundles stands for the Broker's own Workload API socket.
type fakeBundles struct {
	src    *workload.Source
	opened []string
	fail   bool
}

func (f *fakeBundles) open(_ context.Context, socket string) (bundleSource, error) {
	f.opened = append(f.opened, socket)
	if f.fail {
		return nil, errors.New("dial unix: no such file")
	}
	return closer{f.src}, nil
}

type closer struct{ jwtbundle.Source }

func (closer) Close() error { return nil }

func newFakeBundles(t *testing.T) *fakeBundles {
	t.Helper()
	src, err := workload.New(spiffeid.RequireTrustDomainFromString("example.com"))
	if err != nil {
		t.Fatal(err)
	}
	return &fakeBundles{src: src}
}

// runFailing runs the command to its exit and returns stderr and the code.
func runFailing(t *testing.T, d deps, args ...string) (string, int) {
	t.Helper()
	var out, errOut bytes.Buffer
	code := run(context.Background(), args, &out, &errOut, d)
	return errOut.String(), code
}

func TestMissingKeyExitsNonZeroBeforeServing(t *testing.T) {
	for _, tc := range []struct {
		name         string
		env          map[string]string
		args         []string
		wantProvider string
		wantVar      string
	}{
		{"explicit anthropic", map[string]string{"OPENROUTER_API_KEY": "o"}, []string{"--provider", "anthropic"}, "anthropic", "ANTHROPIC_API_KEY"},
		{"explicit openrouter", map[string]string{"ANTHROPIC_API_KEY": "a"}, []string{"--provider", "openrouter"}, "openrouter", "OPENROUTER_API_KEY"},
		{"no key at all", nil, nil, "openrouter", "OPENROUTER_API_KEY"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			f := newFakeBundles(t)
			out := filepath.Join(t.TempDir(), "run")
			errOut, code := runFailing(t, deps{getenv: keys(tc.env), openBundles: f.open}, append(tc.args, "--out", out)...)
			if code == 0 {
				t.Fatal("exit 0")
			}
			if !strings.Contains(errOut, "provider "+tc.wantProvider) || !strings.Contains(errOut, tc.wantVar) {
				t.Errorf("stderr should print the chosen provider and the missing variable: %s", errOut)
			}
			if strings.Contains(errOut, "listening") || len(f.opened) != 0 {
				t.Errorf("served or opened a socket before the key check: %s %v", errOut, f.opened)
			}
			if _, err := os.Stat(out); !os.IsNotExist(err) {
				t.Errorf("run directory created before the key check: %v", err)
			}
		})
	}
}

func TestProviderChoiceFollowsAdr0003(t *testing.T) {
	for _, tc := range []struct {
		name string
		env  map[string]string
		args []string
		want string
	}{
		{"both keys, default", map[string]string{"ANTHROPIC_API_KEY": "a", "OPENROUTER_API_KEY": "o"}, nil, "anthropic"},
		{"openrouter only", map[string]string{"OPENROUTER_API_KEY": "o"}, nil, "openrouter"},
		{"flag wins", map[string]string{"ANTHROPIC_API_KEY": "a", "OPENROUTER_API_KEY": "o"}, []string{"--provider", "openrouter"}, "openrouter"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			f := newFakeBundles(t)
			ctx, cancel := context.WithCancel(context.Background())
			errOut := &syncBuffer{}
			done := make(chan int)
			go func() {
				done <- run(ctx, append(tc.args, "--addr", "127.0.0.1:0", "--out", t.TempDir()), &bytes.Buffer{}, errOut, deps{getenv: keys(tc.env), openBundles: f.open})
			}()
			waitFor(t, errOut, "listening on ")
			cancel()
			if code := <-done; code != 0 {
				t.Fatalf("exit %d: %s", code, errOut)
			}
			if n := strings.Count(errOut.String(), "provider "+tc.want); n != 1 {
				t.Errorf("want the choice %q printed once: %s", tc.want, errOut)
			}
		})
	}
}

var listenRE = regexp.MustCompile(`listening on (http://\S+)`)

func waitFor(t *testing.T, buf *syncBuffer, substr string) string {
	t.Helper()
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		if s := buf.String(); strings.Contains(s, substr) {
			return s
		}
		time.Sleep(5 * time.Millisecond)
	}
	t.Fatalf("never saw %q: %s", substr, buf)
	return ""
}

// The Broker command serves a real Broker: the key comes from .env only, the
// bundle from its own socket, and the Audit log goes to --out.
func TestServesAskAndWritesItsAuditLogToOut(t *testing.T) {
	envFile := filepath.Join(t.TempDir(), ".env")
	if err := os.WriteFile(envFile, []byte("ANTHROPIC_API_KEY=from-the-file\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	f := newFakeBundles(t)
	m := model.New(model.ToolUse("tom", "invoice:approve"))
	defer m.Close()
	out := filepath.Join(t.TempDir(), "run")
	ctx, cancel := context.WithCancel(context.Background())
	errOut := &syncBuffer{}
	done := make(chan int)
	go func() {
		done <- run(ctx, []string{"--addr", "127.0.0.1:0", "--out", out, "--spiffe-socket", "/tmp/x/model-broker.sock"}, &bytes.Buffer{}, errOut,
			deps{getenv: keys(nil), envFile: envFile, openBundles: f.open, upstreamURL: m.URL})
	}()
	m1 := listenRE.FindStringSubmatch(waitFor(t, errOut, "listening on http://"))
	if m1 == nil {
		t.Fatalf("no URL in %s", errOut)
	}

	wl, err := f.src.Workload(broker.PermissionAgent)
	if err != nil {
		t.Fatal(err)
	}
	svid, err := wl.FetchJWTSVID(context.Background(), jwtsvidParams("spiffe://example.com/model-broker"))
	if err != nil {
		t.Fatal(err)
	}
	body, err := modelrequest.Body("Can Tom approve invoices?")
	if err != nil {
		t.Fatal(err)
	}
	req, _ := http.NewRequest(http.MethodPost, m1[1]+wire.PathMessages, bytes.NewReader(body))
	req.Header.Set(wire.HeaderAuthorization, string(wire.BearerFor(wire.JWTSVID(svid.Marshal()))))
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("status %d", resp.StatusCode)
	}
	if got := m.Requests()[0].Header.Get("x-api-key"); got != "from-the-file" {
		t.Errorf("the provider saw key %q", got)
	}

	cancel()
	if code := <-done; code != 0 {
		t.Fatalf("exit %d: %s", code, errOut)
	}
	raw, err := os.ReadFile(filepath.Join(out, "broker.audit.jsonl"))
	if err != nil || strings.Count(string(raw), "\n") != 1 || !strings.Contains(string(raw), `"outcome":"allowed"`) {
		t.Errorf("audit log: %q, %v", raw, err)
	}
	if strings.Contains(errOut.String(), "from-the-file") {
		t.Error("the key leaked into stderr")
	}
	if len(f.opened) != 1 || f.opened[0] != "/tmp/x/model-broker.sock" {
		t.Errorf("opened %v", f.opened)
	}
}

// The Broker command pins model-eval to the Eval's sweep: a sweep model passes,
// no model is refused (the sweep lists several), and the Agent's own Pin is
// still its default model only.
func TestModelEvalIsPinnedToTheSweepAndTheAgentIsNot(t *testing.T) {
	f := newFakeBundles(t)
	// One reply for each request that gets through.
	m := model.New(model.ToolUse("tom", "invoice:approve"), model.ToolUse("tom", "invoice:approve"), model.ToolUse("tom", "invoice:approve"))
	defer m.Close()
	ctx, cancel := context.WithCancel(context.Background())
	errOut := &syncBuffer{}
	done := make(chan int)
	go func() {
		done <- run(ctx, []string{"--addr", "127.0.0.1:0", "--out", t.TempDir()}, &bytes.Buffer{}, errOut,
			deps{getenv: keys(map[string]string{"ANTHROPIC_API_KEY": "k"}), openBundles: f.open, upstreamURL: m.URL})
	}()
	url := listenRE.FindStringSubmatch(waitFor(t, errOut, "listening on http://"))[1]

	send := func(id spiffeid.ID, modelID string) int {
		t.Helper()
		wl, err := f.src.Workload(id)
		if err != nil {
			t.Fatal(err)
		}
		svid, err := wl.FetchJWTSVID(context.Background(), jwtsvidParams("spiffe://example.com/model-broker"))
		if err != nil {
			t.Fatal(err)
		}
		raw, err := modelrequest.Body("Can Tom approve invoices?")
		if err != nil {
			t.Fatal(err)
		}
		var fields map[string]json.RawMessage
		if err := json.Unmarshal(raw, &fields); err != nil {
			t.Fatal(err)
		}
		if modelID != "" {
			fields["model"], _ = json.Marshal(modelID)
		}
		body, _ := json.Marshal(fields)
		req, _ := http.NewRequest(http.MethodPost, url+wire.PathMessages, bytes.NewReader(body))
		req.Header.Set(wire.HeaderAuthorization, string(wire.BearerFor(wire.JWTSVID(svid.Marshal()))))
		resp, err := http.DefaultClient.Do(req)
		if err != nil {
			t.Fatal(err)
		}
		resp.Body.Close()
		return resp.StatusCode
	}
	for _, tc := range []struct {
		name    string
		id      spiffeid.ID
		modelID string
		want    int
	}{
		{"model-eval, Sonnet", broker.ModelEval, "claude-sonnet-5-5", 200},
		{"model-eval, Opus", broker.ModelEval, "claude-opus-5-5", 200},
		{"model-eval, off its list", broker.ModelEval, "claude-opus-9", 403},
		{"model-eval, no model", broker.ModelEval, "", 403},
		{"permission-agent, Sonnet is not on its Pin", broker.PermissionAgent, "claude-sonnet-5-5", 403},
		{"permission-agent, no model", broker.PermissionAgent, "", 200},
	} {
		if got := send(tc.id, tc.modelID); got != tc.want {
			t.Errorf("%s: status %d, want %d", tc.name, got, tc.want)
		}
	}
	cancel()
	<-done
}

func TestDefaultsAreTheBrokersSocketAndALoopbackAddress(t *testing.T) {
	f := newFakeBundles(t)
	ctx, cancel := context.WithCancel(context.Background())
	errOut := &syncBuffer{}
	done := make(chan int)
	// Run in a scratch directory so the default runs/<UTC timestamp>/ lands there.
	t.Chdir(t.TempDir())
	go func() {
		done <- run(ctx, []string{"--addr", "127.0.0.1:0"}, &bytes.Buffer{}, errOut, deps{getenv: keys(map[string]string{"ANTHROPIC_API_KEY": "k"}), openBundles: f.open})
	}()
	waitFor(t, errOut, "listening on ")
	cancel()
	<-done
	if len(f.opened) != 1 || f.opened[0] != "/tmp/agent-identity/model-broker.sock" {
		t.Errorf("opened %v", f.opened)
	}
	runs, _ := filepath.Glob("runs/*/broker.audit.jsonl")
	if len(runs) != 1 {
		t.Errorf("default --out should make runs/<UTC timestamp>/broker.audit.jsonl, found %v", runs)
	}
}

func TestRefusesANonLoopbackAddress(t *testing.T) {
	f := newFakeBundles(t)
	errOut, code := runFailing(t, deps{getenv: keys(map[string]string{"ANTHROPIC_API_KEY": "k"}), openBundles: f.open}, "--addr", "0.0.0.0:8787")
	if code != 2 || !strings.Contains(errOut, "loopback") {
		t.Errorf("exit %d: %s", code, errOut)
	}
}

func TestUnreachableSocketExitsNonZeroWithAHint(t *testing.T) {
	f := newFakeBundles(t)
	f.fail = true
	errOut, code := runFailing(t, deps{getenv: keys(map[string]string{"ANTHROPIC_API_KEY": "k"}), openBundles: f.open}, "--out", t.TempDir())
	if code != 1 || !strings.Contains(errOut, "spiffecli run --config spiffecli/workloads.toml") || strings.Contains(errOut, "listening") {
		t.Errorf("exit %d: %s", code, errOut)
	}
}

func TestBadFlagsAreUsageErrors(t *testing.T) {
	for _, args := range [][]string{{"--nope"}, {"extra"}, {"--provider", "gemini"}} {
		errOut, code := runFailing(t, deps{getenv: keys(map[string]string{"ANTHROPIC_API_KEY": "k"})}, args...)
		if code != 2 {
			t.Errorf("%v: exit %d: %s", args, code, errOut)
		}
	}
}
