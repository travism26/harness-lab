package modelclient_test

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"slices"
	"testing"

	"github.com/travism26/harness-lab/projects/agent-identity/internal/modelclient"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/pin"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/provider"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/wire"
)

// rawRequests runs one Propose against a server that records each raw body.
func rawRequests(t *testing.T, cfg modelclient.Config) [][]byte {
	t.Helper()
	var bodies [][]byte
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		raw, _ := io.ReadAll(r.Body)
		bodies = append(bodies, raw)
		w.WriteHeader(http.StatusOK)
		io.WriteString(w, toolUseReply)
	}))
	defer srv.Close()
	cfg.BaseURL = srv.URL
	c, err := modelclient.New(cfg)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := c.Propose(context.Background(), "Can Tom approve invoices?"); err != nil {
		t.Fatal(err)
	}
	return bodies
}

// The Pin the Broker holds the permission-agent to is built from the Model
// client's own request constants, and this test is what keeps the two in step:
// change the client's system prompt, tools, tool_choice, output_config or any
// other field and this fails here, not on the Broker in a live run.
func TestTheDefaultPinMatchesWhatTheModelClientSends(t *testing.T) {
	p := modelclient.DefaultPin()
	modes := map[string]modelclient.Config{
		"broker mode": {SVID: func(context.Context) (wire.JWTSVID, error) { return "svid", nil }},
		"key mode":    {APIKey: "k", Provider: "stand-in"},
	}
	for name, cfg := range modes {
		t.Run(name, func(t *testing.T) {
			bodies := rawRequests(t, cfg)
			if len(bodies) != 1 {
				t.Fatalf("%d requests; want 1", len(bodies))
			}
			got, err := pin.Shape(bodies[0])
			if err != nil {
				t.Fatal(err)
			}
			if got != p.Shape {
				t.Errorf("the client's request shape hash %s differs from the Pin's %s", got, p.Shape)
			}
		})
	}
}

// Request is the body the Client sends in Broker mode for a first call, so the
// tour can show a request the Pin allows without writing one by hand.
func TestRequestIsTheBodyTheClientSendsInBrokerMode(t *testing.T) {
	bodies := rawRequests(t, modelclient.Config{SVID: func(context.Context) (wire.JWTSVID, error) { return "svid", nil }})
	want, err := modelclient.Request("Can Tom approve invoices?")
	if err != nil {
		t.Fatal(err)
	}
	if string(want) != string(bodies[0]) {
		t.Errorf("Request = %s\nsent    = %s", want, bodies[0])
	}
}

func TestTheDefaultPinListsEachProvidersDefaultModelAndTheClientsMaxTokens(t *testing.T) {
	p := modelclient.DefaultPin()
	for _, name := range []string{"anthropic", "openrouter", "stand-in"} {
		prov, _ := provider.Lookup(name)
		if got := p.Models[name]; !slices.Equal(got, []string{prov.DefaultModel}) {
			t.Errorf("models for %s = %v; want only %s", name, got, prov.DefaultModel)
		}
	}
	if len(p.Models) != 3 {
		t.Errorf("Pin has models for %d providers; want 3", len(p.Models))
	}
	bodies := rawRequests(t, modelclient.Config{APIKey: "k", Provider: "stand-in"})
	var sent struct {
		MaxTokens int `json:"max_tokens"`
	}
	if err := json.Unmarshal(bodies[0], &sent); err != nil {
		t.Fatal(err)
	}
	if p.MaxTokens != sent.MaxTokens || p.MaxTokens == 0 {
		t.Errorf("Pin ceiling %d; the client sends %d", p.MaxTokens, sent.MaxTokens)
	}
}
