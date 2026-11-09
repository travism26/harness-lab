package provider

import (
	"strings"
	"testing"
)

func TestLookupCarriesDefaultModelAndAuthStyle(t *testing.T) {
	for _, tc := range []struct {
		name, model string
		bearer, ok  bool
	}{
		{"anthropic", "claude-haiku-5-5", false, true},
		{"openrouter", "anthropic/claude-haiku-5.5", true, true},
		{"stand-in", "claude-haiku-5-5", false, true},
		{"nope", "claude-haiku-5-5", false, false},
	} {
		p, ok := Lookup(tc.name)
		if ok != tc.ok || p.DefaultModel != tc.model || p.BearerAuth != tc.bearer {
			t.Errorf("Lookup(%q) = %+v, %v", tc.name, p, ok)
		}
	}
}

func TestSweepIsHaikuSonnetOpusAndStartsWithTheDefault(t *testing.T) {
	for _, tc := range []struct {
		p    Provider
		want []string
	}{
		{Providers["anthropic"], []string{"claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"}},
		{Providers["openrouter"], []string{"anthropic/claude-haiku-5.5", "anthropic/claude-sonnet-5.5", "anthropic/claude-opus-5.5"}},
		{StandIn, []string{"claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"}},
	} {
		if strings.Join(tc.p.Sweep, ",") != strings.Join(tc.want, ",") || tc.p.Sweep[0] != tc.p.DefaultModel {
			t.Errorf("%s sweep = %v, want %v", tc.p.Name, tc.p.Sweep, tc.want)
		}
	}
}
