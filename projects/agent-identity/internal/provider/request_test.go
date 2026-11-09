package provider

import "testing"

func TestCostAnthropicFromPriceTable(t *testing.T) {
	a, _ := Lookup("anthropic")
	for _, tc := range []struct {
		model string
		want  float64
	}{
		{"claude-haiku-5-5", (1000*0.10 + 500*0.50) / 1e6},
		{"claude-sonnet-5-5", (1000*2 + 500*10) / 1e6},
		{"claude-opus-5-5", (1000*4 + 500*20) / 1e6},
		{"claude-unlisted", 0},
	} {
		if got := a.Cost(tc.model, 1000, 500, nil); got != tc.want {
			t.Errorf("Cost(%q) = %v, want %v", tc.model, got, tc.want)
		}
	}
}

func TestCostPrefersReportedCost(t *testing.T) {
	rep := 0.042
	a, _ := Lookup("anthropic")
	if got := a.Cost("claude-haiku-5-5", 1000, 500, &rep); got != rep {
		t.Errorf("anthropic with reported = %v", got)
	}
	o, _ := Lookup("openrouter")
	if got := o.Cost("anthropic/claude-haiku-5.5", 1000, 500, &rep); got != rep {
		t.Errorf("openrouter reported = %v", got)
	}
}

func TestCostOpenRouterAndStandInUnreportedIsZero(t *testing.T) {
	for _, name := range []string{"openrouter", "stand-in"} {
		p, _ := Lookup(name)
		if got := p.Cost("claude-haiku-5-5", 1000, 500, nil); got != 0 {
			t.Errorf("%s = %v, want 0", name, got)
		}
	}
}
