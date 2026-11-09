package main

import (
	"bytes"
	"context"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/spiffe/go-spiffe/v2/spiffeid"

	"github.com/travism26/harness-lab/projects/agent-identity/internal/broker"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/eval"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/pin"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/provider"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/standin/model"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/standin/workload"
)

var committedCases string

// TestMain moves into an empty directory, so no real .env is ever near.
func TestMain(m *testing.M) {
	var err error
	if committedCases, err = filepath.Abs("../../evals/cases.jsonl"); err != nil {
		panic(err)
	}
	dir, err := os.MkdirTemp("", "eval-cwd")
	if err != nil {
		panic(err)
	}
	if err := os.Chdir(dir); err != nil {
		panic(err)
	}
	code := m.Run()
	os.RemoveAll(dir)
	os.Exit(code)
}

// brokerFixture is a loopback Broker in front of the stand-in Model, holding
// model-eval to its Pin, and the Workload API socket stand-in that gives the
// Eval its JWT-SVIDs. No key exists anywhere.
type brokerFixture struct {
	model  *model.Server
	url    string
	deps   deps
	opened []string
}

func newBrokerFixture(t *testing.T, replies ...model.Reply) *brokerFixture {
	t.Helper()
	f := &brokerFixture{model: model.New(replies...)}
	t.Cleanup(f.model.Close)
	ws, err := workload.New(spiffeid.RequireTrustDomainFromString("example.com"))
	if err != nil {
		t.Fatal(err)
	}
	b, err := broker.New(broker.Config{
		Audience: broker.ID.String(), Bundles: ws, Provider: provider.StandIn, UpstreamURL: f.model.URL,
		Pins: map[spiffeid.ID]pin.Pin{broker.ModelEval: pin.ModelEval()},
	})
	if err != nil {
		t.Fatal(err)
	}
	srv, err := b.ListenLoopback()
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { srv.Close() })
	f.url = srv.URL
	f.deps = deps{openJWT: func(_ context.Context, socket string) (svidSource, error) {
		f.opened = append(f.opened, socket)
		wl, err := ws.Workload(broker.ModelEval)
		return standInSource{wl}, err
	}}
	return f
}

type standInSource struct{ *workload.Workload }

func (standInSource) Close() error { return nil }

func (f *brokerFixture) run(args ...string) (stdout, stderr string, code int) {
	var out, errb bytes.Buffer
	code = runWith(context.Background(), args, &out, &errb, f.deps)
	return out.String(), errb.String(), code
}

func casesFile(t *testing.T, body string) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "cases.jsonl")
	if err := os.WriteFile(path, []byte(body), 0o600); err != nil {
		t.Fatal(err)
	}
	return path
}

const twoCases = `{"id":"a","category":"named","question":"Can Tom approve invoices?","accept":[{"target":"tom","permission":"invoice:approve"}]}
{"id":"b","category":"no-proposal","question":"Weather?","no_proposal":true}
`

func TestCommittedCasesCoverTheFourCategories(t *testing.T) {
	f, err := os.Open(committedCases)
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	cases, err := eval.LoadCases(f)
	if err != nil {
		t.Fatal(err)
	}
	counts := map[string]int{}
	reportOnly, outOfCatalog := 0, 0
	for _, c := range cases {
		counts[c.Category]++
		if c.ReportOnly {
			reportOnly++
		}
		if strings.HasPrefix(c.ID, "named-ooc-") {
			outOfCatalog++
		}
	}
	if len(cases) < 20 || len(cases) > 28 {
		t.Errorf("%d cases, want about 24", len(cases))
	}
	for _, k := range eval.Categories {
		if counts[k] < 5 {
			t.Errorf("category %s has %d cases", k, counts[k])
		}
	}
	if reportOnly != 2 || outOfCatalog < 2 || outOfCatalog > 3 {
		t.Errorf("report-only = %d, out-of-catalog = %d", reportOnly, outOfCatalog)
	}
}

func TestEvalRunsAgainstALoopbackBrokerAndStandInModelWithNoKey(t *testing.T) {
	f := newBrokerFixture(t, model.ToolUse("tom", "invoice:approve"), model.Text("x"))
	out, errb, code := f.run("--cases", casesFile(t, twoCases), "--runs", "1", "--broker-url", f.url, "--model", "claude-sonnet-5-5")
	if code != 0 {
		t.Fatalf("code=%d out=%s err=%s", code, out, errb)
	}
	// The report names what the Broker reported.
	if !strings.Contains(out, "provider: stand-in\nmodel: claude-sonnet-5-5\n") {
		t.Errorf("report:\n%s", out)
	}
	reqs := f.model.Requests()
	if len(reqs) != 2 {
		t.Fatalf("%d Model requests", len(reqs))
	}
	for _, r := range reqs {
		if r.Header.Get("X-Api-Key") != "" || r.Header.Get("Authorization") != "" {
			t.Errorf("a credential reached the Model: %v", r.Header)
		}
	}
	if len(f.opened) != 1 || f.opened[0] != "/tmp/agent-identity/model-eval.sock" {
		t.Errorf("opened %v; want model-eval's default socket", f.opened)
	}
}

func TestEvalReadsNoKeyAndNoEnvFile(t *testing.T) {
	// A key in the environment and a .env in the working directory are both ignored.
	t.Setenv("ANTHROPIC_API_KEY", "sk-must-not-be-read")
	if err := os.WriteFile(".env", []byte("OPENROUTER_API_KEY=sk-must-not-be-read\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	defer os.Remove(".env")
	f := newBrokerFixture(t, model.ToolUse("tom", "invoice:approve"), model.Text("x"))
	out, _, code := f.run("--cases", casesFile(t, twoCases), "--runs", "1", "--broker-url", f.url, "--model", "claude-haiku-5-5")
	if code != 0 || !strings.Contains(out, "provider: stand-in") {
		t.Fatalf("code=%d out=%s", code, out)
	}
	for _, r := range f.model.Requests() {
		if strings.Contains(r.Header.Get("X-Api-Key")+r.Header.Get("Authorization"), "sk-must-not-be-read") {
			t.Error("the key reached the Model")
		}
	}
	for _, args := range [][]string{{"--provider", "anthropic"}, {"--env-file", ".env"}} {
		if _, _, code := f.run(append([]string{"--broker-url", f.url, "--model", "x"}, args...)...); code != 2 {
			t.Errorf("%v: code %d; the flag is gone, want 2", args, code)
		}
	}
}

func TestAModelOffThePinFailsEveryRunAtTheBroker(t *testing.T) {
	f := newBrokerFixture(t, model.ToolUse("tom", "invoice:approve"))
	out, _, code := f.run("--cases", casesFile(t, twoCases), "--runs", "1", "--broker-url", f.url, "--model", "claude-opus-9")
	if code != 1 || !strings.Contains(out, "provider_error") || len(f.model.Requests()) != 0 {
		t.Fatalf("code=%d requests=%d out=%s", code, len(f.model.Requests()), out)
	}
}

func TestMissingModelOrBrokerURLIsUsageBeforeAnySocketOrRequest(t *testing.T) {
	f := newBrokerFixture(t)
	cases := casesFile(t, twoCases)
	for _, args := range [][]string{
		{"--cases", cases, "--broker-url", f.url},
		{"--cases", cases, "--model", "claude-haiku-5-5"},
		{"--cases", cases, "--model", "claude-haiku-5-5", "--broker-url", "nope"},
	} {
		if _, _, code := f.run(args...); code != 2 {
			t.Errorf("%v: code %d, want 2", args, code)
		}
	}
	if len(f.opened) != 0 || len(f.model.Requests()) != 0 {
		t.Errorf("opened %v, %d requests", f.opened, len(f.model.Requests()))
	}
}

func TestUnreachableSocketIsUsageWithAHint(t *testing.T) {
	var out, errb bytes.Buffer
	d := deps{openJWT: func(context.Context, string) (svidSource, error) { return nil, errors.New("dial unix: no such file") }}
	code := runWith(context.Background(), []string{"--cases", casesFile(t, twoCases), "--broker-url", "http://127.0.0.1:1", "--model", "m"}, &out, &errb, d)
	if code != 2 || !strings.Contains(errb.String(), "spiffecli run --config spiffecli/workloads.toml") {
		t.Fatalf("code=%d err=%s", code, errb.String())
	}
}

func TestExitCodeFollowsMinAccuracy(t *testing.T) {
	for _, tc := range []struct {
		args []string
		want int
	}{
		{nil, 1},
		{[]string{"--min-accuracy", "0"}, 0},
	} {
		f := newBrokerFixture(t, model.ToolUse("tom", "invoice:read"), model.Text("x"))
		args := append([]string{"--cases", casesFile(t, twoCases), "--runs", "1", "--broker-url", f.url, "--model", "claude-haiku-5-5"}, tc.args...)
		if out, _, code := f.run(args...); code != tc.want {
			t.Errorf("%v: code %d, want %d\n%s", tc.args, code, tc.want, out)
		}
	}
}

func TestBadUsage(t *testing.T) {
	f := newBrokerFixture(t)
	for _, args := range [][]string{
		{"--runs", "0"},
		{"--cases", "/no/such/file"},
		{"--min-accuracy", "2"},
		{"extra"},
	} {
		args = append([]string{"--broker-url", f.url, "--model", "claude-haiku-5-5"}, args...)
		if _, _, code := f.run(args...); code != 2 {
			t.Errorf("%v: code %d, want 2", args, code)
		}
	}
}
