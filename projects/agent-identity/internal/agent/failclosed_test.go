package agent_test

import (
	"context"
	"errors"
	"net"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/spiffe/go-spiffe/v2/svid/jwtsvid"

	"github.com/travism26/harness-lab/projects/agent-identity/internal/agent"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/standin/model"
)

const (
	wardenDownText = "The Warden couldn't be reached, so I can't say whether `tom` holds `invoice:approve` in `acme`."
	modelDownText  = "The Model couldn't be reached, so no lookup was made."
	noPropText     = "I couldn't turn that into one permission lookup, so no lookup was made. Ask about one person and one permission."
)

// newAgent builds an Agent for the listed workload with an explicit Model
// config. src nil means the capturing source.
func (e *auditEnv) newAgent(t *testing.T, url string, mc *agent.ModelConfig, src agent.SVIDSource) *agent.Agent {
	t.Helper()
	wl, err := e.source.Workload(listedID)
	if err != nil {
		t.Fatal(err)
	}
	e.fetched = &capturing{inner: wl}
	if src == nil {
		src = e.fetched
	}
	a, err := agent.New(agent.Config{WardenURL: url, Audience: wardenAudience, Source: src, Audit: &e.agentLog, Model: mc})
	if err != nil {
		t.Fatal(err)
	}
	return a
}

func (e *auditEnv) svidCount() int {
	e.fetched.mu.Lock()
	defer e.fetched.mu.Unlock()
	return len(e.fetched.svids)
}

// noSecrets fails if text holds any assertion or captured JWT-SVID.
func (e *auditEnv) noSecrets(t *testing.T, what, text string) {
	t.Helper()
	var canaries []string
	for _, as := range e.assertions {
		canaries = append(canaries, string(as), strings.Split(string(as), ".")[2])
	}
	e.fetched.mu.Lock()
	for _, s := range e.fetched.svids {
		canaries = append(canaries, s, strings.Split(s, ".")[2])
	}
	e.fetched.mu.Unlock()
	for _, c := range canaries {
		if strings.Contains(text, c) {
			t.Errorf("%s contains a token: %q", what, c)
		}
	}
}

func closedURL(t *testing.T) string {
	t.Helper()
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	u := "http://" + l.Addr().String()
	l.Close()
	return u
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
			a := e.newAgent(t, srv.URL, &agent.ModelConfig{BaseURL: m.URL, APIKey: "k", Provider: "stand-in"}, nil)
			r, err := a.Ask(context.Background(), e.assertion(t, "acme/alice", listedID), "q")
			if err != nil {
				t.Fatal(err)
			}
			if r.ID != agent.ReplyWardenUnreachable || body(r) != wardenDownText || r.Status != tc.status {
				t.Errorf("got %s %d %q", r.ID, r.Status, body(r))
			}
			if g := e.agentRecords(t); len(g) != 1 || g[0].Reply != agent.ReplyWardenUnreachable || g[0].WardenStatus != tc.status {
				t.Errorf("agent record %+v", g)
			}
			e.noSecrets(t, "Reply", r.Text)
		})
	}
}

// A Model that can't be reached, whatever the reason, means no SVID, no Lookup
// and a model_unreachable Reply; a live provider never falls back to a stand-in.
func TestModelFailureIsUnreachableWithNoSVIDAndNoLookup(t *testing.T) {
	const (
		viaScript = iota
		viaClosedPort
		viaDeadline
	)
	cases := []struct {
		name     string
		provider string
		script   model.Reply
		how      int
	}{
		{"401 live", "anthropic", model.Error(401), viaScript},
		{"403 live", "anthropic", model.Error(403), viaScript},
		{"closed port stand-in", "stand-in", model.Error(500), viaClosedPort},
		{"closed port live", "anthropic", model.Error(500), viaClosedPort},
		{"deadline live", "anthropic", model.Error(500), viaDeadline},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			e := newAuditEnv(t)
			m := model.New(tc.script)
			defer m.Close()
			base := m.URL
			ctx := context.Background()
			switch tc.how {
			case viaClosedPort:
				base = closedURL(t)
			case viaDeadline:
				dead, err := net.Listen("tcp", "127.0.0.1:0") // accepts, never answers
				if err != nil {
					t.Fatal(err)
				}
				defer dead.Close()
				base = "http://" + dead.Addr().String()
				var cancel context.CancelFunc
				ctx, cancel = context.WithTimeout(ctx, 50*time.Millisecond)
				defer cancel()
			}
			a := e.newAgent(t, e.url, &agent.ModelConfig{BaseURL: base, APIKey: "k", Provider: tc.provider}, nil)
			r, err := a.Ask(ctx, e.assertion(t, "acme/alice", listedID), "q")
			if err != nil {
				t.Fatal(err)
			}
			wantBackend := "live"
			if tc.provider == "stand-in" {
				wantBackend = "stand-in"
			}
			if r.ID != agent.ReplyModelUnreachable || body(r) != modelDownText || r.Status != 0 {
				t.Errorf("got %s %d %q", r.ID, r.Status, body(r))
			}
			if !strings.HasSuffix(r.Text, "\n[model: "+wantBackend+" · id "+r.CorrelationID+"]") {
				t.Errorf("footer %q; want backend %s", r.Text, wantBackend)
			}
			if n := e.svidCount(); n != 0 {
				t.Errorf("fetched %d JWT-SVIDs", n)
			}
			if w := e.wardenRecords(t); len(w) != 0 {
				t.Errorf("Warden got %d requests", len(w))
			}
			g := e.agentRecords(t)
			if len(g) != 1 || g[0].Backend != wantBackend || g[0].WardenStatus != 0 || g[0].Reply != agent.ReplyModelUnreachable ||
				g[0].ModelFailure == nil || g[0].ModelFailure.Code != "provider_error" {
				t.Errorf("agent record %+v", g)
			}
			e.noSecrets(t, "Reply", r.Text)
		})
	}
}

type failingSource struct{}

func (failingSource) FetchJWTSVID(context.Context, jwtsvid.Params) (*jwtsvid.SVID, error) {
	return nil, errors.New("workload api: socket gone")
}

// If the JWT-SVID can't be fetched after the Model proposed, Ask returns an
// error with no Reply text and sends nothing to the Warden.
func TestSVIDFetchFailureIsAnErrorWithNoReplyAndNoLookup(t *testing.T) {
	e := newAuditEnv(t)
	m := model.New(model.ToolUse("tom", "invoice:approve"))
	defer m.Close()
	a := e.newAgent(t, e.url, &agent.ModelConfig{BaseURL: m.URL, APIKey: "k", Provider: "stand-in"}, failingSource{})
	r, err := a.Ask(context.Background(), e.assertion(t, "acme/alice", listedID), "q")
	if err == nil {
		t.Fatal("no error")
	}
	if r.Text != "" || r.ID != "" {
		t.Errorf("reply %+v", r)
	}
	if w := e.wardenRecords(t); len(w) != 0 {
		t.Errorf("Warden got %d requests", len(w))
	}
	g := e.agentRecords(t)
	if len(g) != 1 || g[0].Proposal == nil || g[0].WardenStatus != 0 || g[0].Reply != "" {
		t.Errorf("agent record %+v", g)
	}
	e.noSecrets(t, "error", err.Error())
	e.noSecrets(t, "Reply", r.Text)
}

func TestMissingKeyOrModelStopsBeforeAnyRequest(t *testing.T) {
	for _, name := range []string{"empty key", "nil Model"} {
		t.Run(name, func(t *testing.T) {
			e := newAuditEnv(t)
			m := model.New(model.ToolUse("tom", "invoice:approve"))
			defer m.Close()
			mc := &agent.ModelConfig{BaseURL: m.URL, APIKey: "", Provider: "anthropic"}
			if name == "nil Model" {
				mc = nil
			}
			a := e.newAgent(t, e.url, mc, nil)
			r, err := a.Ask(context.Background(), e.assertion(t, "acme/alice", listedID), "q")
			if err == nil || r.Text != "" {
				t.Errorf("err %v, reply %q", err, r.Text)
			}
			if n := len(m.Requests()); n != 0 {
				t.Errorf("Model got %d requests", n)
			}
			if n := e.svidCount(); n != 0 {
				t.Errorf("fetched %d JWT-SVIDs", n)
			}
			if w := e.wardenRecords(t); len(w) != 0 {
				t.Errorf("Warden got %d requests", len(w))
			}
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
			a := e.newAgent(t, e.url, &agent.ModelConfig{BaseURL: m.URL, APIKey: "k", Provider: "stand-in"}, nil)
			r, err := a.Ask(context.Background(), e.assertion(t, "acme/alice", listedID), "q")
			if err != nil {
				t.Fatal(err)
			}
			if r.ID != agent.ReplyNoProposal || body(r) != noPropText || r.Proposal != nil {
				t.Errorf("got %s %q", r.ID, body(r))
			}
			if n := e.svidCount(); n != 0 {
				t.Errorf("fetched %d JWT-SVIDs", n)
			}
			if w := e.wardenRecords(t); len(w) != 0 {
				t.Errorf("Warden got %d requests", len(w))
			}
		})
	}
}
