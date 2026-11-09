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

	"github.com/travism26/harness-lab/projects/agent-identity/internal/standin/workload"
)

const question = "Can Tom approve invoices?"

func runDeps(d deps, args ...string) (stdout, stderr string, code int) {
	var out, errOut bytes.Buffer
	code = runWith(args, &out, &errOut, d)
	return out.String(), errOut.String(), code
}

func TestScenariosIgnoreFlagsTheyCannotUse(t *testing.T) {
	// tokens and scripted take no Model: --live needs needs no Broker URL and prints no choice.
	for _, s := range []string{"tokens", "scripted"} {
		out, errOut, code := runDeps(deps{}, s, "--live")
		if code != 0 || strings.Contains(errOut, "provider") || len(lookupLines(out)) != 3 {
			t.Errorf("%s --live: exit %d, stderr %s", s, code, errOut)
		}
	}
}

func TestStandInRunNeverPrintsAProviderChoice(t *testing.T) {
	_, errOut, code := runDeps(deps{}, "ask", question)
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
		return nil, errors.New("dial unix: no such file")
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
	if f.fetches["/tmp/x/agent.sock"] != 2 || f.fetches["/tmp/x/warden.sock"] != 0 {
		t.Errorf("fetches %v: the Agent fetches twice (the Broker's audience, then the Warden's), the Warden never", f.fetches)
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
