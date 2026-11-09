package broker

import (
	"maps"
	"slices"
	"testing"

	"github.com/travism26/harness-lab/projects/agent-identity/internal/provider"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/trustlint"
)

// trustlint R5 matches key variable names by the list in trustlint.KeyVars, so
// that list must be exactly the names this table holds, one per live provider.
func TestKeyEnvIsExactlyTrustlintsKeyVars(t *testing.T) {
	got := slices.Sorted(maps.Values(keyEnv))
	want := slices.Sorted(slices.Values(trustlint.KeyVars))
	if !slices.Equal(got, want) {
		t.Errorf("keyEnv = %v; trustlint.KeyVars = %v; they must match", got, want)
	}
	for name := range provider.Providers {
		if keyEnv[name] == "" {
			t.Errorf("provider %s has no key variable", name)
		}
	}
	if len(keyEnv) != len(provider.Providers) {
		t.Errorf("keyEnv has %d entries; want one per provider (%d)", len(keyEnv), len(provider.Providers))
	}
}
