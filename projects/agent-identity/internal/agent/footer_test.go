package agent_test

import (
	"context"
	"strings"
	"testing"

	"github.com/travism26/harness-lab/projects/agent-identity/internal/agent"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/standin/model"
)

// The footer names the backend, stand-in or live, never the provider: it says
// live exactly when the Model call was to a live provider.
func TestFooterNamesTheBackend(t *testing.T) {
	for _, tc := range []struct {
		provider string
		bearer   bool
		want     string
	}{
		{"stand-in", false, "[model: stand-in · id "},
		{"anthropic", false, "[model: live · id "},
		{"openrouter", true, "[model: live · id "},
	} {
		t.Run(tc.provider, func(t *testing.T) {
			e := newAskEnv(t)
			m := model.New(model.ToolUse("tom", "invoice:approve"))
			defer m.Close()
			a, err := agent.New(agent.Config{
				WardenURL: e.url, Audience: wardenAudience, Source: e.source,
				Model: &agent.ModelConfig{BaseURL: m.URL, APIKey: "k", Provider: tc.provider, BearerAuth: tc.bearer},
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
		})
	}
}
