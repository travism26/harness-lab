package agent_test

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/spiffe/go-spiffe/v2/svid/jwtsvid"

	"github.com/travism26/harness-lab/projects/agent-identity/internal/agent"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/provider"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/standin/model"
)

const (
	wardenDownText = "The Warden couldn't be reached, so I can't say whether `tom` holds `invoice:approve` in `acme`."
	modelDownText  = "The Model couldn't be reached, so no lookup was made."
	noProposalText = "I couldn't turn that into one permission lookup, so no lookup was made. Ask about one person and one permission."
)

// svidCount is the JWT-SVIDs fetched for the Warden; those for the Broker are
// not counted.
func (e *auditEnv) svidCount() int {
	e.fetched.mu.Lock()
	defer e.fetched.mu.Unlock()
	return e.fetched.wardenFetches
}

// noSecrets fails if the Reply text, the error text (when there is one) or
// either Audit log holds a signed assertion, a fetched JWT-SVID or the Model API
// key. On a path where no JWT-SVID was fetched the JWT-SVID part checks nothing;
// the assertions and the API key are always real.
func (e *auditEnv) noSecrets(t *testing.T, r agent.Reply, err error) {
	t.Helper()
	texts := map[string]string{"Reply text": r.Text, "Agent Audit log": e.agentLog.String(), "Warden Audit log": e.wardenLog.String()}
	if err != nil {
		texts["error text"] = err.Error()
	}
	canaries := append(e.tokenCanaries(), e.modelAPIKey)
	for what, text := range texts {
		for _, c := range canaries {
			if strings.Contains(text, c) {
				t.Errorf("%s contains a secret: %q", what, c)
			}
		}
	}
}

func withModel(mc *agent.ModelConfig) func(*agent.Config) {
	return func(c *agent.Config) { c.Model = mc }
}

// A Warden that answers 200 with nothing readable, or an unexpected status,
// gave no answer: the Reply says so and never says "No.".
func TestWardenNoAnswerIsUnreachableNeverNo(t *testing.T) {
	cases := []struct {
		name   string
		status int
		body   string
	}{
		{"200 not json", 200, "not json"},
		{"200 empty body", 200, ""},
		{"400", 400, `{"error":"x"}`},
		{"404", 404, `{"error":"x"}`},
		{"429", 429, `{"error":"x"}`},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			e := newAuditEnv(t)
			srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				w.WriteHeader(tc.status)
				w.Write([]byte(tc.body))
			}))
			defer srv.Close()
			m := model.New(model.ToolUse("tom", "invoice:approve"))
			defer m.Close()
			a := e.agent(t, listedID, srv.URL, m, 0)
			r, err := a.Ask(context.Background(), e.assertion(t, "acme/alice", listedID), "q")
			if err != nil {
				t.Fatal(err)
			}
			if r.ID != agent.ReplyWardenUnreachable || body(r) != wardenDownText || r.Status != tc.status {
				t.Errorf("got %s %d %q", r.ID, r.Status, body(r))
			}
			if g := e.agentRecords(t); len(g) != 1 || g[0].Reply != agent.ReplyWardenUnreachable || g[0].WardenStatus != tc.status {
				t.Errorf("the Agent's Audit record %+v", g)
			}
			e.noSecrets(t, r, err)
		})
	}
}

// A Model that can't be reached, whatever the reason, means no Warden SVID, no
// Lookup and a model_unreachable Reply. The Agent reaches the Model only through
// the Broker, so it never falls back to calling a provider.
func TestModelFailureIsUnreachableWithNoSVIDAndNoLookup(t *testing.T) {
	// setup returns the Model URL the Broker forwards to and the context Ask runs under.
	type setup func(t *testing.T, m *model.Server) (string, context.Context)
	scripted := func(t *testing.T, m *model.Server) (string, context.Context) { return m.URL, context.Background() }
	closedPort := func(t *testing.T, m *model.Server) (string, context.Context) {
		return closedURL(t), context.Background()
	}
	deadline := func(t *testing.T, m *model.Server) (string, context.Context) {
		ctx, cancel := context.WithTimeout(context.Background(), 50*time.Millisecond)
		t.Cleanup(cancel)
		return deadURL(t), ctx
	}
	cases := []struct {
		name   string
		script model.Reply
		setup  setup
	}{
		{"401", model.Error(401), scripted},
		{"403", model.Error(403), scripted},
		{"closed port", model.Error(500), closedPort},
		{"deadline", model.Error(500), deadline},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			e := newAuditEnv(t)
			m := model.New(tc.script)
			defer m.Close()
			upstream, ctx := tc.setup(t, m)
			mc := &agent.ModelConfig{BaseURL: startBroker(t, e.source, upstream, provider.StandIn, ""), BrokerAudience: brokerAudience}
			a := e.agent(t, listedID, e.url, nil, 0, withModel(mc))
			r, err := a.Ask(ctx, e.assertion(t, "acme/alice", listedID), "q")
			if err != nil {
				t.Fatal(err)
			}
			if r.ID != agent.ReplyModelUnreachable || body(r) != modelDownText || r.Status != 0 {
				t.Errorf("got %s %d %q", r.ID, r.Status, body(r))
			}
			if !strings.HasSuffix(r.Text, "\n[model: unknown via broker · id "+r.CorrelationID+"]") {
				t.Errorf("footer %q", r.Text)
			}
			if n := e.svidCount(); n != 0 {
				t.Errorf("fetched %d JWT-SVIDs for the Warden", n)
			}
			if w := e.wardenRecords(t); len(w) != 0 {
				t.Errorf("%d Lookups reached the Warden", len(w))
			}
			g := e.agentRecords(t)
			if len(g) != 1 || g[0].Backend != "" || g[0].WardenStatus != 0 || g[0].Reply != agent.ReplyModelUnreachable ||
				g[0].ModelFailure == nil || g[0].ModelFailure.Code != "provider_error" {
				t.Errorf("the Agent's Audit record %+v", g)
			}
			e.noSecrets(t, r, err)
		})
	}
}

// failingSource fails the JWT-SVID for the Warden, as a Workload API that went
// away after the Model proposed; the Broker's still works.
type failingSource struct{ inner agent.SVIDSource }

func (f failingSource) FetchJWTSVID(ctx context.Context, p jwtsvid.Params) (*jwtsvid.SVID, error) {
	if p.Audience != wardenAudience {
		return f.inner.FetchJWTSVID(ctx, p)
	}
	return nil, errors.New("workload api: socket gone")
}

// If the JWT-SVID can't be fetched after the Model proposed, Ask returns an
// error with no Reply text and no Lookup reaches the Warden.
func TestSVIDFetchFailureIsAnErrorWithNoReplyAndNoLookup(t *testing.T) {
	e := newAuditEnv(t)
	m := model.New(model.ToolUse("tom", "invoice:approve"))
	defer m.Close()
	a := e.agent(t, listedID, e.url, m, 0, func(c *agent.Config) { c.Source = failingSource{inner: c.Source} })
	r, err := a.Ask(context.Background(), e.assertion(t, "acme/alice", listedID), "q")
	if err == nil {
		t.Fatal("no error")
	}
	if r.Text != "" || r.ID != "" {
		t.Errorf("reply %+v", r)
	}
	if w := e.wardenRecords(t); len(w) != 0 {
		t.Errorf("%d Lookups reached the Warden", len(w))
	}
	g := e.agentRecords(t)
	if len(g) != 1 || g[0].Proposal == nil || g[0].WardenStatus != 0 || g[0].Reply != "" {
		t.Errorf("the Agent's Audit record %+v", g)
	}
	e.noSecrets(t, r, err)
}

func TestNoBrokerAudienceOrModelStopsBeforeAnyModelCallOrLookup(t *testing.T) {
	cases := []struct {
		name  string
		model func(m *model.Server) *agent.ModelConfig
	}{
		{"no Broker audience", func(m *model.Server) *agent.ModelConfig {
			return &agent.ModelConfig{BaseURL: m.URL}
		}},
		{"nil Model", func(*model.Server) *agent.ModelConfig { return nil }},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			e := newAuditEnv(t)
			m := model.New(model.ToolUse("tom", "invoice:approve"))
			defer m.Close()
			a := e.agent(t, listedID, e.url, nil, 0, withModel(tc.model(m)))
			r, err := a.Ask(context.Background(), e.assertion(t, "acme/alice", listedID), "q")
			if err == nil || r.Text != "" {
				t.Errorf("err %v, reply %q", err, r.Text)
			}
			if n := len(m.Requests()); n != 0 {
				t.Errorf("the Model was asked %d times; want 0", n)
			}
			if n := e.svidCount(); n != 0 {
				t.Errorf("fetched %d JWT-SVIDs", n)
			}
			if w := e.wardenRecords(t); len(w) != 0 {
				t.Errorf("%d Lookups reached the Warden", len(w))
			}
			e.noSecrets(t, r, err)
		})
	}
}

// The gate refuses a Proposal the Model makes twice: a Tenant-qualified Target,
// a wrong tool name, an extra field, a bad Target format. No SVID, no Lookup.
func TestGateFailuresTwiceGiveNoProposalAndNoLookup(t *testing.T) {
	cases := []struct {
		name string
		r    model.Reply
	}{
		{"other tenant target", model.ToolUse("globex/tom", "invoice:approve")},
		{"own tenant target", model.ToolUse("acme/alice", "invoice:approve")},
		{"wrong tool name", model.ToolUseNamed("other", map[string]any{"target": "tom", "permission": "invoice:approve"})},
		{"extra field", model.ToolUseNamed("lookup_permission", map[string]any{"target": "tom", "permission": "invoice:approve", "tenant": "globex"})},
		{"bad target format", model.ToolUse("Tom!", "invoice:approve")},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			e := newAuditEnv(t)
			m := model.New(tc.r, tc.r)
			defer m.Close()
			a := e.agent(t, listedID, e.url, m, 0)
			r, err := a.Ask(context.Background(), e.assertion(t, "acme/alice", listedID), "q")
			if err != nil {
				t.Fatal(err)
			}
			if r.ID != agent.ReplyNoProposal || body(r) != noProposalText || r.Proposal != nil {
				t.Errorf("got %s %q", r.ID, body(r))
			}
			if n := len(m.Requests()); n != 2 {
				t.Errorf("the Model was asked %d times; want 2", n)
			}
			if n := e.svidCount(); n != 0 {
				t.Errorf("fetched %d JWT-SVIDs", n)
			}
			if w := e.wardenRecords(t); len(w) != 0 {
				t.Errorf("%d Lookups reached the Warden", len(w))
			}
			e.noSecrets(t, r, err)
		})
	}
}
