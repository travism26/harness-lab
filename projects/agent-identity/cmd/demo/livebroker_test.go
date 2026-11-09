package main

import (
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"

	"github.com/spiffe/go-spiffe/v2/spiffeid"

	"github.com/travism26/harness-lab/projects/agent-identity/internal/broker"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/pin"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/provider"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/standin/model"
)

const providerKey = "sk-broker-only-key"

// liveBroker is a Broker as its own process would run it: it alone holds the
// provider key, takes its bundle from a socket of its own and writes
// broker.audit.jsonl into the run directory.
type liveBroker struct {
	url string
	out string
	m   *model.Server
}

func startLiveBroker(t *testing.T, f *fakeSockets) liveBroker {
	t.Helper()
	m := model.New(model.ToolUse("tom", "invoice:approve"))
	t.Cleanup(m.Close)
	out := filepath.Join(t.TempDir(), "run")
	if err := os.MkdirAll(out, 0o755); err != nil {
		t.Fatal(err)
	}
	logFile, err := os.Create(filepath.Join(out, "broker.audit.jsonl"))
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { logFile.Close() })
	b, err := broker.New(broker.Config{
		Audience: brokerAud, Bundles: f.src, Provider: provider.Providers["anthropic"], Key: providerKey,
		UpstreamURL: m.URL, Audit: logFile,
		Pins: map[spiffeid.ID]pin.Pin{permissionAgent: pin.Agent()},
	})
	if err != nil {
		t.Fatal(err)
	}
	srv, err := b.ListenLoopback()
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { srv.Close() })
	return liveBroker{url: srv.URL, out: out, m: m}
}

// Key-absence: the demo reads no provider key and no .env, and the ask still
// succeeds because the Broker holds the key.
func TestLiveAskThroughABrokerNeedsNoKeyInTheDemo(t *testing.T) {
	for _, k := range []string{"ANTHROPIC_API_KEY", "OPENROUTER_API_KEY"} {
		t.Setenv(k, "")
	}
	// A .env with a key in the working directory must not be read either.
	t.Chdir(t.TempDir())
	if err := os.WriteFile(".env", []byte("ANTHROPIC_API_KEY=file-key\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	f := newFakeSockets(t)
	lb := startLiveBroker(t, f)
	out, errOut, code := runDeps(deps{openJWT: f.open}, "ask", question, "--live", "--broker-url", lb.url, "--spiffe-socket", "/tmp/x/agent.sock", "--out", lb.out)
	if code != 0 {
		t.Fatalf("exit %d: %s", code, errOut)
	}
	if !strings.HasPrefix(out, "Yes. tom holds") || !strings.Contains(out, "\n[model: anthropic/") || !strings.Contains(out, " via broker · id ") {
		t.Errorf("reply: %q", out)
	}
	reqs := lb.m.Requests()
	if len(reqs) != 1 || reqs[0].Header.Get("x-api-key") != providerKey {
		t.Fatalf("the provider should see the Broker's key once: %v", reqs)
	}
	if strings.Contains(out+errOut, providerKey) || strings.Contains(out+errOut, "file-key") {
		t.Error("a key leaked into the output")
	}
}

func TestLiveRunKeepsTheBrokersAuditLogAndTracesIt(t *testing.T) {
	f := newFakeSockets(t)
	lb := startLiveBroker(t, f)
	_, errOut, code := runDeps(deps{openJWT: f.open}, "ask", question, "--live", "--broker-url", lb.url, "--spiffe-socket", "/tmp/x/agent.sock", "--out", lb.out)
	if code != 0 {
		t.Fatalf("exit %d: %s", code, errOut)
	}
	raw, err := os.ReadFile(filepath.Join(lb.out, "broker.audit.jsonl"))
	if err != nil || strings.Count(string(raw), "\n") != 1 {
		t.Fatalf("the demo must leave the Broker's log alone: %q, %v", raw, err)
	}
	if !strings.Contains(errOut, "msg=broker status=200 outcome=allowed") {
		t.Errorf("the trace lacks the Broker's record: %s", errOut)
	}
}

func TestLiveNeedsABrokerURLAndASpiffeSocket(t *testing.T) {
	for _, tc := range []struct {
		name string
		args []string
		want string
	}{
		{"no broker url", []string{"ask", question, "--live", "--spiffe-socket", "/tmp/x/agent.sock"}, "--broker-url"},
		{"no spiffe socket", []string{"tour", "--live", "--broker-url", "http://127.0.0.1:1"}, "--spiffe-socket"},
		{"broker url without live", []string{"ask", question, "--broker-url", "http://127.0.0.1:1"}, "--live"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			f := newFakeSockets(t)
			out, errOut, code := runDeps(deps{openJWT: f.open}, tc.args...)
			if code != 2 || out != "" || !strings.Contains(errOut, tc.want) {
				t.Errorf("exit %d, stdout %q, stderr %s", code, out, errOut)
			}
			if len(f.opened) != 0 {
				t.Errorf("a socket was opened before the check: %v", f.opened)
			}
		})
	}
}

func TestModelAndProviderFlagsAreGone(t *testing.T) {
	for _, flag := range []string{"--model", "--provider"} {
		_, _, code := runDeps(deps{}, "ask", question, "--live", flag, "x")
		if code != 2 {
			t.Errorf("%s: exit %d, want 2", flag, code)
		}
	}
	_, errOut, _ := runDeps(deps{})
	if !strings.Contains(errOut, "--broker-url") || strings.Contains(errOut, "--model") || strings.Contains(errOut, "--provider") {
		t.Errorf("usage: %s", errOut)
	}
}

func TestFullLiveTour(t *testing.T) {
	f := newFakeSockets(t)
	lb := startLiveBroker(t, f)
	out, errOut, code := runDeps(deps{openJWT: f.open}, "tour", "--live", "--broker-url", lb.url, "--spiffe-socket", "/tmp/x/agent.sock", "--spiffe-socket-other", "/tmp/x/other.sock", "--out", lb.out)
	if code != 0 {
		t.Fatalf("exit %d: %s", code, errOut)
	}
	checkLines(t, lookupLines(out), slices.Concat(tokenLines, scriptedLines))
	if !strings.Contains(out, "== ask\nYes. tom holds") || !strings.Contains(out, "[model: anthropic/") {
		t.Errorf("tour output: %s", out)
	}
	if !strings.Contains(out, "== broker\nnote: skipped") {
		t.Errorf("the stand-in broker scenario should be skipped in a live tour: %s", out)
	}
	raw, _ := os.ReadFile(filepath.Join(lb.out, "broker.audit.jsonl"))
	if n := strings.Count(string(raw), "\n"); n != 1 {
		t.Errorf("the Broker's log has %d records; want only the ask's", n)
	}
}
