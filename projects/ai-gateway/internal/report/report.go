// Package report summarises a Call-record JSONL file: record counts, sessions,
// token totals, a list-price cost estimate and latency percentiles. It never
// reads a body: record below has no request_body or response_body field, so
// encoding/json skips those values and no body text can reach the output.
package report

import (
	"bufio"
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"math"
	"sort"
)

// NoSession is the bucket name for records without a session id.
const NoSession = "(no session id)"

// record is the part of a Call record the report reads. The field names are
// those of projects/ai-gateway/internal/callrecord/callrecord.go. Do not add
// the body fields here.
type record struct {
	SessionID string `json:"x-claude-code-session-id"`
	Model     string `json:"model"`
	LatencyMS int64  `json:"latency_ms"`
	Usage     Tokens `json:"usage"`
}

// Tokens is a set of the usage counters a Call record defines, or their sum.
type Tokens struct {
	InputTokens              int64 `json:"input_tokens"`
	OutputTokens             int64 `json:"output_tokens"`
	CacheCreationInputTokens int64 `json:"cache_creation_input_tokens"`
	CacheReadInputTokens     int64 `json:"cache_read_input_tokens"`
}

func (t *Tokens) add(o Tokens) {
	t.InputTokens += o.InputTokens
	t.OutputTokens += o.OutputTokens
	t.CacheCreationInputTokens += o.CacheCreationInputTokens
	t.CacheReadInputTokens += o.CacheReadInputTokens
}

// Group is the records of one session, or of one model.
type Group struct {
	Records int
	Tokens  Tokens
	// CostUSD is the list-price estimate; it stays 0 for a model with no list price.
	CostUSD float64
}

// Summary is what Summarize learned from a file.
type Summary struct {
	Records   int
	Tokens    Tokens
	Sessions  map[string]*Group
	Models    map[string]*Group
	Latencies []int64 // sorted ascending
	// Unpriced is the number of records whose model has no list price.
	Unpriced int
	// CostUSD sums the models that have a list price.
	CostUSD float64
}

// Summarize reads Call records from in, one JSON object per line. An invalid
// line is an error that names the line number and not the line.
func Summarize(in io.Reader) (*Summary, error) {
	s := &Summary{Sessions: map[string]*Group{}, Models: map[string]*Group{}}
	r := bufio.NewReader(in)
	for n := 1; ; n++ {
		line, err := r.ReadBytes('\n')
		if len(bytes.TrimSpace(line)) > 0 {
			var rec record
			if jerr := json.Unmarshal(line, &rec); jerr != nil {
				return nil, fmt.Errorf("line %d is not a Call record", n)
			}
			s.add(rec)
		}
		if err == io.EOF {
			break
		}
		if err != nil {
			return nil, err
		}
	}
	sort.Slice(s.Latencies, func(i, j int) bool { return s.Latencies[i] < s.Latencies[j] })
	return s, nil
}

func (s *Summary) add(rec record) {
	s.Records++
	s.Tokens.add(rec.Usage)
	s.Latencies = append(s.Latencies, rec.LatencyMS)
	sid := rec.SessionID
	if sid == "" {
		sid = NoSession
	}
	model := rec.Model
	if model == "" {
		model = NoModel
	}
	cost, priced := Estimate(rec.Model, rec.Usage)
	for _, g := range []*Group{group(s.Sessions, sid), group(s.Models, model)} {
		g.Records++
		g.Tokens.add(rec.Usage)
		g.CostUSD += cost
	}
	if priced {
		s.CostUSD += cost
	} else {
		s.Unpriced++
	}
}

// NoModel is the bucket name for records without a model.
const NoModel = "(no model)"

func group(m map[string]*Group, k string) *Group {
	g := m[k]
	if g == nil {
		g = &Group{}
		m[k] = g
	}
	return g
}

// Estimate returns the list-price cost in USD of one Call's usage, and false
// (with cost 0) when the model has no list price. Cache creation tokens are
// charged at the 5-minute cache write price, as a Call record does not say
// which cache duration was used.
func Estimate(model string, u Tokens) (float64, bool) {
	mp, ok := priceFor(model)
	if !ok {
		return 0, false
	}
	p := mp.Price
	if mp.Over100k != nil && u.InputTokens+u.CacheCreationInputTokens+u.CacheReadInputTokens > 100_000 {
		p = *mp.Over100k
	}
	const mtok = 1e6
	return (float64(u.InputTokens)*p.Input +
		float64(u.CacheCreationInputTokens)*p.CacheWrite +
		float64(u.CacheReadInputTokens)*p.CacheRead +
		float64(u.OutputTokens)*p.Output) / mtok, true
}

// Percentile returns the nearest-rank p-th percentile (0 < p <= 100) of the
// ascending values: the value at 1-based rank ceil(p/100 * n). It returns 0
// for no values.
func Percentile(sorted []int64, p float64) int64 {
	if len(sorted) == 0 {
		return 0
	}
	rank := int(math.Ceil(p / 100 * float64(len(sorted))))
	if rank < 1 {
		rank = 1
	}
	return sorted[rank-1]
}

// Write prints s as text. It prints session ids, model names, counts and
// numbers, and nothing taken from a body.
func Write(w io.Writer, s *Summary) {
	fmt.Fprintf(w, "records: %d\n", s.Records)
	named := len(s.Sessions)
	if s.Sessions[NoSession] != nil {
		named--
	}
	fmt.Fprintf(w, "sessions: %d (records without a session id are listed as %q)\n", named, NoSession)
	for _, k := range sortedKeys(s.Sessions) {
		g := s.Sessions[k]
		fmt.Fprintf(w, "  %s: records=%d %s\n", k, g.Records, tokenLine(g.Tokens))
	}
	fmt.Fprintf(w, "tokens: %s\n", tokenLine(s.Tokens))
	fmt.Fprintf(w, "latency_ms: p50=%d p95=%d (nearest-rank over %d records)\n",
		Percentile(s.Latencies, 50), Percentile(s.Latencies, 95), len(s.Latencies))
	fmt.Fprintf(w, "estimated cost (list-price estimate, not an invoice; prices from %s, retrieved %s):\n",
		PricesSource, PricesRetrieved)
	for _, k := range sortedKeys(s.Models) {
		g := s.Models[k]
		if _, ok := priceFor(k); ok {
			fmt.Fprintf(w, "  %s: records=%d $%.4f\n", k, g.Records, g.CostUSD)
		} else {
			fmt.Fprintf(w, "  %s: records=%d no list price\n", k, g.Records)
		}
	}
	fmt.Fprintf(w, "  total, models with a list price only: $%.4f\n", s.CostUSD)
	if s.Unpriced > 0 {
		fmt.Fprintf(w, "  %d record(s) with no list price are left out of the total\n", s.Unpriced)
	}
}

func tokenLine(t Tokens) string {
	return fmt.Sprintf("input=%d output=%d cache_creation=%d cache_read=%d",
		t.InputTokens, t.OutputTokens, t.CacheCreationInputTokens, t.CacheReadInputTokens)
}

func sortedKeys(m map[string]*Group) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	return keys
}
