package main

import (
	"bytes"
	"strings"
	"testing"
)

const fixture = "../../internal/report/testdata/calls.jsonl"

// The fixture has 8 records. Expected values, computed by hand:
//
//	sessions: sess-alpha 3 records, sess-beta 2, sess-gamma 1, and 2 with no session id
//	input tokens:  3100 + 11000 + 150000 + 17 = 164117
//	output tokens: 1550 + 2100 + 1100 + 23    = 4773
//	cache creation 4000, cache read 8000
//	latency_ms sorted: 100 200 300 400 500 600 700 1000
//	  p50 = rank ceil(0.50*8) = 4 -> 400; p95 = rank ceil(0.95*8) = 8 -> 1000
//	cost, USD per MTok list price:
//	  claude-sonnet-4-5 (3 / 3.75 / 0.30 / 15), 4 records:
//	    1000*3 + 500*15                       = 10500
//	    2000*3 + 1000*15 + 4000*3.75          = 36000
//	    100*3 + 50*15 + 8000*0.30             = 3450
//	    10*3 + 20*15                          = 330     -> 50280 / 1e6 = 0.05028
//	  claude-haiku-4-5 (1 / 5), 1 record: 10000*1 + 2000*5 = 20000 -> 0.02
//	  claude-haiku-5-5, 2 records:
//	    1000 in (prompt <= 100k): 1000*0.10 + 100*0.50     = 150
//	    150000 in (prompt > 100k): 150000*0.50 + 1100*2.50 = 77750 -> 0.07790
//	  claude-opus-9-9: no list price, 1 record, left out of the total
//	  total = 0.05028 + 0.02 + 0.0779 = 0.14818
func TestReportOnFixture(t *testing.T) {
	var stdout, stderr bytes.Buffer
	if code := run([]string{fixture}, &stdout, &stderr); code != 0 {
		t.Fatalf("exit code %d", code)
	}
	out := stdout.String()
	for _, want := range []string{
		"records: 8\n",
		"sessions: 3 ",
		"  sess-alpha: records=3 input=3100 output=1550 cache_creation=4000 cache_read=8000\n",
		"  sess-beta: records=2 input=11000 output=2100 cache_creation=0 cache_read=0\n",
		"  sess-gamma: records=1 input=150000 output=1100 cache_creation=0 cache_read=0\n",
		"  (no session id): records=2 input=17 output=23 cache_creation=0 cache_read=0\n",
		"tokens: input=164117 output=4773 cache_creation=4000 cache_read=8000\n",
		"latency_ms: p50=400 p95=1000 ",
		"estimate, not an invoice",
		"  claude-sonnet-4-5-20250929: records=4 $0.0503\n",
		"  claude-haiku-4-5-20251001: records=1 $0.0200\n",
		"  claude-haiku-5-5: records=2 $0.0779\n",
		"  claude-opus-9-9: records=1 no list price\n",
		"  total, models with a list price only: $0.1482\n",
		"1 record(s) with no list price are left out of the total",
	} {
		if !strings.Contains(out, want) {
			t.Errorf("stdout lacks %q", want)
		}
	}
}

func TestReportPrintsNoBodyAndNoSecret(t *testing.T) {
	var stdout, stderr bytes.Buffer
	run([]string{fixture}, &stdout, &stderr)
	for name, text := range map[string]string{"stdout": stdout.String(), "stderr": stderr.String()} {
		for _, banned := range []string{"BODYTEXT", "RESPONSETEXT", "FIXTUREONLY", "sk-ant", "Bearer", "PRIVATE KEY", "request_body", "response_body"} {
			if strings.Contains(text, banned) {
				t.Errorf("%s contains a banned string (%d bytes checked)", name, len(banned))
			}
		}
	}
}

func TestUsageAndMissingInput(t *testing.T) {
	var stdout, stderr bytes.Buffer
	if code := run(nil, &stdout, &stderr); code != 2 {
		t.Errorf("no args: code %d, want 2", code)
	}
	if code := run([]string{"no-such-file.jsonl"}, &stdout, &stderr); code != 1 {
		t.Errorf("missing file: code %d, want 1", code)
	}
}
