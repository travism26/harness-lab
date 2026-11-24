package report

import (
	"math"
	"strings"
	"testing"
)

func TestPercentileNearestRank(t *testing.T) {
	ten := []int64{1, 2, 3, 4, 5, 6, 7, 8, 9, 10}
	cases := []struct {
		vals []int64
		p    float64
		want int64
	}{
		{ten, 50, 5}, // rank ceil(0.5*10) = 5
		{ten, 95, 10},
		{ten, 10, 1},
		{ten, 11, 2},
		{[]int64{7}, 50, 7},
		{[]int64{7}, 95, 7},
		{[]int64{1, 2}, 50, 1},
		{nil, 50, 0},
	}
	for _, c := range cases {
		if got := Percentile(c.vals, c.p); got != c.want {
			t.Errorf("Percentile(%v, %v) = %d, want %d", c.vals, c.p, got, c.want)
		}
	}
}

func TestPriceFor(t *testing.T) {
	for _, id := range []string{
		"claude-sonnet-4-5-20250929", "claude-sonnet-4-5", "claude-sonnet-4-5-latest", "CLAUDE-SONNET-4-5-20250929",
		"claude-sonnet-4-5-20250929[1m]", "claude-opus-4-1-20250805", "claude-opus-4-20250514", "claude-haiku-5-5",
	} {
		if _, ok := priceFor(id); !ok {
			t.Errorf("%q should have a list price", id)
		}
	}
	for _, id := range []string{"", "gpt-x", "claude-opus-9-9", "claude-sonnet-4-9", "claude-sonnet-4-5-beta", "claude-opus-4-5x"} {
		if _, ok := priceFor(id); ok {
			t.Errorf("%q should have no list price", id)
		}
	}
	// The longest key wins: opus 4.5 is $5 input, opus 4 is $15.
	mp, _ := priceFor("claude-opus-4-5-20251101")
	if mp.Input != 5 {
		t.Errorf("opus 4.5 input price = %v, want 5", mp.Input)
	}
	mp, _ = priceFor("claude-opus-4-20250514")
	if mp.Input != 15 {
		t.Errorf("opus 4 input price = %v, want 15", mp.Input)
	}
}

func TestEstimate(t *testing.T) {
	// claude-sonnet-4-5: $3 input, $3.75 cache write, $0.30 cache read, $15 output per MTok.
	// 1M of each: 3 + 3.75 + 0.30 + 15 = 22.05.
	got, ok := Estimate("claude-sonnet-4-5-20250929", Tokens{1e6, 1e6, 1e6, 1e6})
	if !ok || math.Abs(got-22.05) > 1e-9 {
		t.Errorf("sonnet 4.5 estimate = %v, %v; want 22.05", got, ok)
	}
	// claude-haiku-5-5 at or under 100,000 prompt tokens: $0.10 input, $0.50 output.
	got, _ = Estimate("claude-haiku-5-5", Tokens{InputTokens: 100_000, OutputTokens: 1e6})
	if math.Abs(got-(0.01+0.5)) > 1e-9 {
		t.Errorf("haiku 5.5 low tier = %v, want 0.51", got)
	}
	// One token over: the prompt includes cache tokens; $0.50 input, $2.50 output.
	got, _ = Estimate("claude-haiku-5-5", Tokens{InputTokens: 1, CacheReadInputTokens: 100_000, OutputTokens: 1e6})
	// 1 input token at $0.50, 100,000 cache read tokens at $0.05, 1M output at $2.50.
	if want := (0.5 + 100_000*0.05 + 1e6*2.5) / 1e6; math.Abs(got-want) > 1e-9 {
		t.Errorf("haiku 5.5 high tier = %v, want %v", got, want)
	}
	if c, ok := Estimate("claude-opus-9-9", Tokens{InputTokens: 5}); ok || c != 0 {
		t.Errorf("unknown model: %v, %v; want 0, false", c, ok)
	}
}

func TestSummarizeSkipsBodiesByConstruction(t *testing.T) {
	in := `{"model":"claude-haiku-4-5","request_body":{"not":"a string"},"response_body":12,"latency_ms":5,"usage":{"input_tokens":1}}` + "\n"
	s, err := Summarize(strings.NewReader(in))
	if err != nil {
		t.Fatalf("a body of any type must be ignored: %v", err)
	}
	if s.Records != 1 || s.Tokens.InputTokens != 1 {
		t.Errorf("records=%d input=%d", s.Records, s.Tokens.InputTokens)
	}
}

func TestSummarizeInvalidLine(t *testing.T) {
	_, err := Summarize(strings.NewReader(`{"model":"m"}` + "\n" + `{"request_body":"BODYTEXT"` + "\n"))
	if err == nil || strings.Contains(err.Error(), "BODYTEXT") || !strings.Contains(err.Error(), "line 2") {
		t.Error("want an error naming line 2 and no content")
	}
}
