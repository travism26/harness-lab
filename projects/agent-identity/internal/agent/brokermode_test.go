package agent_test

import (
	"context"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/spiffe/go-spiffe/v2/bundle/jwtbundle"
	"github.com/spiffe/go-spiffe/v2/spiffeid"

	"github.com/travism26/harness-lab/projects/agent-identity/internal/agent"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/broker"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/pin"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/provider"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/standin/model"
)

const brokerAudience = "spiffe://example.com/model-broker"

func withBroker(url string) func(*agent.Config) {
	return func(c *agent.Config) { c.Model = &agent.ModelConfig{BaseURL: url, BrokerAudience: brokerAudience} }
}

// startBroker puts a real Broker in front of upstream (a stand-in Model's URL)
// and returns its URL. It lists both test Agents and pins each to the Agent's
// own Pin. prov and key are what the Broker holds: the Agent never does.
func startBroker(t *testing.T, bundles jwtbundle.Source, upstream string, prov provider.Provider, key string) string {
	t.Helper()
	b, err := broker.New(broker.Config{
		Audience: brokerAudience, Bundles: bundles, Allowlist: []spiffeid.ID{listedID, unlistedID},
		Provider: prov, Key: key, UpstreamURL: upstream,
		Pins: map[spiffeid.ID]pin.Pin{listedID: pin.Agent(), unlistedID: pin.Agent()},
	})
	if err != nil {
		t.Fatal(err)
	}
	srv, err := b.ListenLoopback()
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { srv.Close() })
	return srv.URL
}

// A question asked through a real Broker reaches the same Reply as before; the
// footer shows the Broker hop, and the Agent's record copies what the Broker
// reported, labelled as Broker-reported, under the Correlation ID the Broker
// also audits.
func TestAskThroughARealBrokerRepliesAndCopiesWhatTheBrokerReported(t *testing.T) {
	e := newAuditEnv(t)
	m := model.New(model.ToolUse("tom", "invoice:approve"))
	defer m.Close()
	var brokerLog syncBuffer
	b, err := broker.New(broker.Config{
		Audience: brokerAudience, Bundles: e.source, Allowlist: []spiffeid.ID{listedID},
		Provider: provider.StandIn, UpstreamURL: m.URL, Audit: &brokerLog,
		Pins: map[spiffeid.ID]pin.Pin{listedID: pin.Agent()},
	})
	if err != nil {
		t.Fatal(err)
	}
	srv, err := b.ListenLoopback()
	if err != nil {
		t.Fatal(err)
	}
	defer srv.Close()
	a := e.agent(t, listedID, e.url, nil, 0, withBroker(srv.URL))

	r, err := a.Ask(context.Background(), e.assertion(t, "acme/alice", listedID), "Can Tom approve invoices?")
	if err != nil {
		t.Fatal(err)
	}

	if r.ID != agent.ReplyYes || !strings.HasSuffix(r.Text, "\n[model: stand-in via broker · id "+r.CorrelationID+"]") {
		t.Errorf("reply %s %q", r.ID, r.Text)
	}
	if reqs := m.Requests(); len(reqs) != 1 || reqs[0].Auth != model.AuthNone {
		t.Errorf("the Model's requests %+v; the Agent must send no key", reqs)
	}
	recs := e.agentRecords(t)
	if len(recs) != 1 {
		t.Fatalf("%d Agent records", len(recs))
	}
	g := recs[0]
	if g.Backend != "stand-in" || g.Model != "stand-in" || g.Reply != agent.ReplyYes || g.WardenStatus != 200 {
		t.Errorf("record = %+v", g)
	}
	if len(g.ModelCalls) != 1 {
		t.Fatalf("model calls = %+v", g.ModelCalls)
	}
	if c := g.ModelCalls[0]; c.Provider != "stand-in" || !c.BrokerReported || c.InputTokens != 10 || c.OutputTokens != 5 || c.RequestID != "req_standin_1" {
		t.Errorf("model call = %+v", c)
	}
	br := decodeLines[broker.AuditRecord](t, brokerLog.String())
	if len(br) != 1 || br[0].CorrelationID != r.CorrelationID || br[0].Outcome != broker.OutcomeAllowed || br[0].SPIFFEID != listedID.String() {
		t.Errorf("Broker records = %+v; want one allowed under %s", br, r.CorrelationID)
	}
	if w := e.wardenRecords(t); len(w) != 1 || w[0].CorrelationID != r.CorrelationID {
		t.Errorf("Warden records %+v", w)
	}
	e.noSecrets(t, r, nil)
}

// A Broker 401, 403 or 502, or no Broker at all, is the Model-unreachable Reply
// with no Lookup, and the Agent's record carries the Broker's status and reason.
func TestBrokerRefusalOrOutageIsModelUnreachableWithNoLookup(t *testing.T) {
	respond := func(status int, body string) func(*testing.T) string {
		return func(t *testing.T) string {
			s := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				io.Copy(io.Discard, r.Body)
				w.WriteHeader(status)
				io.WriteString(w, body)
			}))
			t.Cleanup(s.Close)
			return s.URL
		}
	}
	cases := []struct {
		name       string
		url        func(*testing.T) string
		wantStatus int
		wantReason string
	}{
		{"401", respond(401, `{"reason":"jwt_svid_audience"}`), 401, "jwt_svid_audience"},
		{"403", respond(403, `{"reason":"not_allowlisted"}`), 403, "not_allowlisted"},
		{"502", respond(502, `{"reason":"upstream_error","upstream_status":401}`), 502, "upstream_error"},
		{"unreachable", closedURL, 0, ""},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			e := newAuditEnv(t)
			a := e.agent(t, listedID, e.url, nil, 0, withBroker(tc.url(t)))

			r, err := a.Ask(context.Background(), e.assertion(t, "acme/alice", listedID), "q")

			if err != nil {
				t.Fatal(err)
			}
			if r.ID != agent.ReplyModelUnreachable || body(r) != modelDownText || r.Status != 0 {
				t.Errorf("got %s %d %q", r.ID, r.Status, body(r))
			}
			if !strings.HasSuffix(r.Text, "\n[model: unknown via broker · id "+r.CorrelationID+"]") {
				t.Errorf("footer %q", r.Text)
			}
			if w := e.wardenRecords(t); len(w) != 0 {
				t.Errorf("%d Lookups reached the Warden", len(w))
			}
			g := e.agentRecords(t)
			if len(g) != 1 || g[0].Reply != agent.ReplyModelUnreachable || g[0].WardenStatus != 0 ||
				g[0].ModelFailure == nil || g[0].ModelFailure.Code != "provider_error" ||
				g[0].ModelFailure.BrokerStatus != tc.wantStatus || g[0].ModelFailure.BrokerReason != tc.wantReason {
				t.Errorf("the Agent's Audit record %+v", g)
			}
			e.noSecrets(t, r, err)
		})
	}
}
