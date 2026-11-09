package agent_test

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/spiffe/go-spiffe/v2/spiffeid"
	"github.com/spiffe/go-spiffe/v2/svid/jwtsvid"

	"github.com/travism26/harness-lab/projects/agent-identity/internal/agent"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/login"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/standin/model"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/standin/workload"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/warden"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/wire"
)

type countingSource struct {
	inner agent.SVIDSource
	n     atomic.Int32
}

func (c *countingSource) FetchJWTSVID(ctx context.Context, p jwtsvid.Params) (*jwtsvid.SVID, error) {
	c.n.Add(1)
	return c.inner.FetchJWTSVID(ctx, p)
}

type askEnv struct {
	login  *login.Login
	source *countingSource
	url    string
}

func newAskEnv(t *testing.T) *askEnv {
	t.Helper()
	source, err := workload.New(trustDomain)
	if err != nil {
		t.Fatal(err)
	}
	lg, err := login.New(nil)
	if err != nil {
		t.Fatal(err)
	}
	w, err := warden.New(warden.Config{
		Audience: wardenAudience, Bundles: source,
		Allowlist: []spiffeid.ID{listedID}, LoginKey: lg.PublicKey(),
	})
	if err != nil {
		t.Fatal(err)
	}
	srv, err := w.ListenLoopback()
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { srv.Close() })
	wl, err := source.Workload(listedID)
	if err != nil {
		t.Fatal(err)
	}
	return &askEnv{login: lg, source: &countingSource{inner: wl}, url: srv.URL}
}

func (e *askEnv) agent(t *testing.T, m *model.Server, wardenURL string, timeout time.Duration) *agent.Agent {
	t.Helper()
	a, err := agent.New(agent.Config{
		WardenURL: wardenURL, Audience: wardenAudience, Source: e.source,
		WardenTimeout: timeout,
		Model:         &agent.ModelConfig{BaseURL: m.URL, APIKey: "k", Provider: "stand-in"},
	})
	if err != nil {
		t.Fatal(err)
	}
	return a
}

func (e *askEnv) assertion(t *testing.T, caller string) wire.CallerAssertion {
	t.Helper()
	as, err := e.login.Sign(caller, wardenAudience, listedID.String())
	if err != nil {
		t.Fatal(err)
	}
	return as
}

const footerPrefix = "[model: stand-in · id "

func ask(t *testing.T, a *agent.Agent, as wire.CallerAssertion, q string) agent.Reply {
	t.Helper()
	r, err := a.Ask(context.Background(), as, q)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.HasSuffix(r.Text, "]") || !strings.Contains(r.Text, "\n"+footerPrefix+r.CorrelationID+"]") || r.CorrelationID == "" {
		t.Errorf("reply lacks the footer with its Correlation ID: %q", r.Text)
	}
	return r
}

func body(r agent.Reply) string { return strings.SplitN(r.Text, "\n", 2)[0] }

func TestAskReplies(t *testing.T) {
	tests := []struct {
		name   string
		caller string
		script []model.Reply
		id     agent.ReplyID
		want   string
	}{
		{"yes", "acme/alice", []model.Reply{model.ToolUse("tom", "invoice:approve")}, "yes",
			"Yes. tom holds `invoice:approve` in acme through the Finance Approver role."},
		{"no", "acme/alice", []model.Reply{model.ToolUse("bob", "invoice:approve")}, "no",
			"No. bob does not hold `invoice:approve` in acme."},
		{"self", "acme/bob", []model.Reply{model.ToolUse("self", "invoice:read")}, "yes",
			"Yes. bob holds `invoice:read` in acme through the Employee role."},
		{"denial", "acme/bob", []model.Reply{model.ToolUse("tom", "invoice:approve")}, "denial",
			"I can't answer that: the Warden didn't allow this lookup."},
		{"unknown_permission", "acme/alice", []model.Reply{model.ToolUse("tom", "invoices:approve")}, "unknown_permission",
			"The Warden doesn't know the permission `invoices:approve`, so it couldn't answer whether `tom` holds it in `acme`."},
		{"unauthenticated", "acme/nobody", []model.Reply{model.ToolUse("tom", "invoice:approve")}, "unauthenticated",
			"The Warden didn't accept my identity or yours, so no lookup was made."},
		{"no_proposal text", "acme/alice", []model.Reply{model.Text("SECRET model words")}, "no_proposal",
			"I couldn't turn that into one permission lookup, so no lookup was made. Ask about one person and one permission."},
		{"no_proposal refusal", "acme/alice", []model.Reply{model.Refusal()}, "no_proposal",
			"I couldn't turn that into one permission lookup, so no lookup was made. Ask about one person and one permission."},
		{"model_unreachable", "acme/alice", []model.Reply{model.Error(500)}, "model_unreachable",
			"The Model couldn't be reached, so no lookup was made."},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			e := newAskEnv(t)
			m := model.New(tc.script...)
			defer m.Close()
			r := ask(t, e.agent(t, m, e.url, 0), e.assertion(t, tc.caller), "Can Tom approve invoices?")
			if r.ID != tc.id || body(r) != tc.want {
				t.Errorf("got %s %q; want %s %q", r.ID, body(r), tc.id, tc.want)
			}
			if strings.Contains(r.Text, "SECRET") {
				t.Error("the Model's text reached the Reply")
			}
		})
	}
}

func TestNoProposalNeverFetchesAnSVID(t *testing.T) {
	e := newAskEnv(t)
	m := model.New(model.Text("hi"))
	defer m.Close()
	ask(t, e.agent(t, m, e.url, 0), e.assertion(t, "acme/alice"), "hello")
	if n := e.source.n.Load(); n != 0 {
		t.Errorf("fetched %d JWT-SVIDs on the no-Proposal path", n)
	}
}

func TestProposalFetchesExactlyOneSVID(t *testing.T) {
	e := newAskEnv(t)
	m := model.New(model.ToolUse("tom", "invoice:approve"))
	defer m.Close()
	ask(t, e.agent(t, m, e.url, 0), e.assertion(t, "acme/alice"), "q")
	if n := e.source.n.Load(); n != 1 {
		t.Errorf("fetched %d JWT-SVIDs; want 1", n)
	}
}

func TestTwoToolUsesTwiceGivesNoProposalAndNoLookup(t *testing.T) {
	e := newAskEnv(t)
	two := map[string]any{"target": "tom", "permission": "invoice:approve"}
	m := model.New(model.ToolUses(two, two), model.ToolUses(two, two))
	defer m.Close()
	r := ask(t, e.agent(t, m, e.url, 0), e.assertion(t, "acme/alice"), "Can Tom approve and read invoices?")
	if r.ID != "no_proposal" || e.source.n.Load() != 0 || len(m.Requests()) != 2 {
		t.Errorf("id=%s fetches=%d model calls=%d", r.ID, e.source.n.Load(), len(m.Requests()))
	}
}

func TestOneProposalForTwoPartQuestionMakesOneLookup(t *testing.T) {
	var lookups atomic.Int32
	e := newAskEnv(t)
	counting := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		lookups.Add(1)
		w.Write([]byte(`{"holds":false}`))
	}))
	defer counting.Close()
	m := model.New(model.ToolUse("tom", "invoice:approve"))
	defer m.Close()
	r := ask(t, e.agent(t, m, counting.URL, 0), e.assertion(t, "acme/alice"), "Can Tom approve invoices and can Bob read them?")
	if body(r) != "No. tom does not hold `invoice:approve` in acme." || lookups.Load() != 1 {
		t.Errorf("got %q after %d lookups", body(r), lookups.Load())
	}
}

func TestWardenUnreachable(t *testing.T) {
	want := "The Warden couldn't be reached, so I can't say whether `tom` holds `invoice:approve` in `acme`."
	e := newAskEnv(t)

	deadListener, closedPort := deadURL(t), closedURL(t)
	fiveXX := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(502) }))
	defer fiveXX.Close()

	for name, c := range map[string]struct {
		url     string
		timeout time.Duration
	}{
		"dead listener": {deadListener, 50 * time.Millisecond},
		"closed port":   {closedPort, 0},
		"5xx":           {fiveXX.URL, 0},
	} {
		t.Run(name, func(t *testing.T) {
			m := model.New(model.ToolUse("tom", "invoice:approve"))
			defer m.Close()
			r := ask(t, e.agent(t, m, c.url, c.timeout), e.assertion(t, "acme/alice"), "q")
			if r.ID != "warden_unreachable" || body(r) != want {
				t.Errorf("got %s %q", r.ID, body(r))
			}
		})
	}
}

func TestA401IsNeverRetried(t *testing.T) {
	var hits atomic.Int32
	e := newAskEnv(t)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits.Add(1)
		w.WriteHeader(401)
		w.Write([]byte(`{"error":"unauthenticated"}`))
	}))
	defer srv.Close()
	m := model.New(model.ToolUse("tom", "invoice:approve"))
	defer m.Close()
	r := ask(t, e.agent(t, m, srv.URL, 0), e.assertion(t, "acme/alice"), "q")
	if r.ID != "unauthenticated" || hits.Load() != 1 || e.source.n.Load() != 1 {
		t.Errorf("id=%s hits=%d fetches=%d", r.ID, hits.Load(), e.source.n.Load())
	}
}

func TestTargetIsCallersTenantPlusModelName(t *testing.T) {
	var corrID, target string
	e := newAskEnv(t)
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		corrID = r.Header.Get(wire.HeaderCorrelationID)
		var req wire.LookupRequest
		json.NewDecoder(r.Body).Decode(&req)
		target = req.Target
		w.Write([]byte(`{"holds":false}`))
	}))
	defer srv.Close()
	m := model.New(model.ToolUse("tom", "invoice:approve"))
	defer m.Close()
	r := ask(t, e.agent(t, m, srv.URL, 0), e.assertion(t, "globex/sam"), "q")
	if body(r) != "No. tom does not hold `invoice:approve` in globex." {
		t.Errorf("got %q", body(r))
	}
	if target != "globex/tom" {
		t.Errorf("Warden saw target %q; want globex/tom", target)
	}
	if corrID != r.CorrelationID {
		t.Errorf("Correlation-Id header %q; want %q", corrID, r.CorrelationID)
	}
}
