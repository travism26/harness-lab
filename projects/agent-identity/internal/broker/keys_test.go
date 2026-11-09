package broker_test

import (
	"strings"
	"testing"

	"github.com/travism26/harness-lab/projects/agent-identity/internal/broker"
)

func env(kv map[string]string) func(string) string {
	return func(k string) string { return kv[k] }
}

func TestSelect(t *testing.T) {
	both := map[string]string{"ANTHROPIC_API_KEY": "a-key", "OPENROUTER_API_KEY": "o-key"}
	cases := []struct {
		name, flag string
		env        map[string]string
		want, key  string
		wantErr    string
	}{
		{"no flag, both keys: Anthropic", "", both, "anthropic", "a-key", ""},
		{"no flag, only OpenRouter key: fallback", "", map[string]string{"OPENROUTER_API_KEY": "o-key"}, "openrouter", "o-key", ""},
		{"flag wins over the default", "openrouter", both, "openrouter", "o-key", ""},
		{"explicit anthropic", "anthropic", both, "anthropic", "a-key", ""},
		{"no flag, no key", "", nil, "", "", "ANTHROPIC_API_KEY"},
		{"explicit provider, its key missing", "anthropic", map[string]string{"OPENROUTER_API_KEY": "o-key"}, "", "", "ANTHROPIC_API_KEY"},
		{"unknown provider", "gemini", both, "", "", "unknown provider"},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			got, err := broker.Select(c.flag, env(c.env))
			if c.wantErr != "" {
				if err == nil || !strings.Contains(err.Error(), c.wantErr) {
					t.Fatalf("err = %v; want it to mention %q", err, c.wantErr)
				}
				return
			}
			if err != nil {
				t.Fatal(err)
			}
			if got.Name != c.want || got.Key != c.key {
				t.Errorf("got %s/%q; want %s/%q", got.Name, got.Key, c.want, c.key)
			}
		})
	}
}

func TestSelectedProviderCarriesItsRoot(t *testing.T) {
	got, err := broker.Select("openrouter", env(map[string]string{"OPENROUTER_API_KEY": "k"}))
	if err != nil {
		t.Fatal(err)
	}
	if got.BaseURL != "https://openrouter.ai/api" {
		t.Errorf("BaseURL = %q", got.BaseURL)
	}
}

// Choose is the ADR 0003 rule on its own: it names the provider and never
// reports a missing key, so a command can say what it chose before Select
// fails on the key.
func TestChooseAppliesTheRuleWithoutNeedingAKey(t *testing.T) {
	for _, tc := range []struct {
		name string
		env  map[string]string
		want string
	}{
		{"openrouter", map[string]string{"ANTHROPIC_API_KEY": "a"}, "openrouter"},
		{"", map[string]string{"ANTHROPIC_API_KEY": "a", "OPENROUTER_API_KEY": "o"}, "anthropic"},
		{"", map[string]string{"OPENROUTER_API_KEY": "o"}, "openrouter"},
		{"", nil, "openrouter"},
	} {
		if got := broker.Choose(tc.name, env(tc.env)); got != tc.want {
			t.Errorf("Choose(%q, %v) = %q, want %q", tc.name, tc.env, got, tc.want)
		}
	}
}
