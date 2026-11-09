package agent_test

import (
	"context"
	"strings"
	"testing"

	"github.com/travism26/harness-lab/projects/agent-identity/internal/agent"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/provider"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/standin/model"
)

// The footer names what the Broker says served the question, and that the
// Broker did: the provider and model for a live provider, "stand-in" for the
// stand-in. The Agent holds no key in any of the three.
func TestFooterNamesWhatTheBrokerSaysServedTheQuestion(t *testing.T) {
	for _, tc := range []struct {
		provider string
		want     string
	}{
		{"stand-in", "[model: stand-in via broker · id "},
		{"anthropic", "[model: anthropic/claude-haiku-5-5 via broker · id "},
		{"openrouter", "[model: openrouter/anthropic/claude-haiku-5.5 via broker · id "},
	} {
		t.Run(tc.provider, func(t *testing.T) {
			e := newAskEnv(t)
			m := model.New(model.ToolUse("tom", "invoice:approve"))
			defer m.Close()
			prov, _ := provider.Lookup(tc.provider)
			a, err := agent.New(agent.Config{
				WardenURL: e.url, Audience: wardenAudience, Source: e.source,
				Model: &agent.ModelConfig{BaseURL: startBroker(t, e.bundles, m.URL, prov, "provider-key"), BrokerAudience: brokerAudience},
			})
			if err != nil {
				t.Fatal(err)
			}
			r, err := a.Ask(context.Background(), e.assertion(t, "acme/alice"), "Can Tom approve invoices?")
			if err != nil {
				t.Fatal(err)
			}
			if !strings.Contains(r.Text, "\n"+tc.want+r.CorrelationID+"]") {
				t.Errorf("footer wrong: %q; want prefix %q", r.Text, tc.want)
			}
			if strings.Contains(r.Text, "provider-key") {
				t.Error("the provider key reached the Reply")
			}
		})
	}
}
