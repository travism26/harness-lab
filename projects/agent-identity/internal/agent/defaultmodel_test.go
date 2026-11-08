package agent_test

import (
	"testing"

	"github.com/travism26/harness-lab/projects/agent-identity/internal/agent"
)

func TestDefaultModel(t *testing.T) {
	for provider, want := range map[string]string{
		"anthropic":  "claude-haiku-5-5",
		"openrouter": "anthropic/claude-haiku-5.5",
	} {
		if got := agent.DefaultModel(provider); got != want {
			t.Errorf("DefaultModel(%q) = %q; want %q", provider, got, want)
		}
	}
}
