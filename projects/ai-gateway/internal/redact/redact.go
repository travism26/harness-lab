// Package redact rewrites a Call-record JSONL file with secret-shaped strings
// replaced by a kind tag such as [REDACTED:bearer]. It is a post-processor:
// the Gateway's write path is unchanged and the live audit file stays raw.
//
// A Call record stores request_body and response_body as plain JSON strings
// holding the body text as the Gateway saw it
// (projects/ai-gateway/internal/callrecord/callrecord.go). That text is often
// JSON or server-sent events itself, so a body is not parsed again: the
// patterns run over the decoded string value, and the PEM and token patterns
// also accept the backslash-escaped form a JSON-in-a-string body has.
// Redaction is pattern-based and best-effort.
package redact

import (
	"bufio"
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"regexp"
	"strings"
)

// Counts maps a kind to the number of redactions made for it.
type Counts map[string]int

type rule struct {
	kind string
	re   *regexp.Regexp
	// keep, when not nil, decides whether a match is a secret. It exists so a
	// pattern can stay a plain regexp where RE2 has no lookahead.
	keep func(match string) bool
}

// rules run in order; a later rule never rewrites a tag an earlier one wrote
// (see the keep func of the header rule).
//
// The sk-ant- and ANTHROPIC_API_KEY patterns duplicate KEY_PATTERNS in
// projects/agents/scripts/check.ts; keep the two in step by hand, as they are
// in different languages and Projects.
var rules = []rule{
	{kind: "pem", re: regexp.MustCompile(
		`-----BEGIN [A-Z ]*PRIVATE KEY-----(?:[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----|[\s\S]*)`)},
	// sk-ant-oat... and sk-ant-ort... are OAuth access and refresh tokens, so
	// this rule must run before the generic sk-ant- rule.
	{kind: "oauth", re: regexp.MustCompile(`sk-ant-o[a-z]{2}[0-9]*-[A-Za-z0-9_-]{10,}`)},
	{kind: "oauth", re: regexp.MustCompile(
		`(?i)\b(?:access|refresh|id)_token\\?"\s*:\s*\\?"[^"\\]{8,}`)},
	{kind: "oauth", re: regexp.MustCompile(`eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]*`)},
	{kind: "anthropic-key", re: regexp.MustCompile(`sk-ant-[A-Za-z0-9_-]{10,}`)},
	{kind: "anthropic-key", re: regexp.MustCompile(
		`ANTHROPIC_API_KEY\s*[=:]\s*\\?["']?[A-Za-z0-9_-]{16,}`)},
	{kind: "bearer", re: regexp.MustCompile(`(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}`), keep: bearerLooksLikeToken},
	// Generic header values, as they appear in a body that quotes headers.
	{kind: "header", re: regexp.MustCompile(
		`(?i)\b(?:authorization|x-api-key)\\?"?\s*[:=]\s*\\?"?(?:(?:basic|token)\s+)?[^\s"\\,;]{8,}`),
		keep: func(m string) bool { return !strings.Contains(m, "[REDACTED:") }},
}

// bearerLooksLikeToken drops prose such as "bearer authentication": a token
// has a digit or a punctuation character in it.
func bearerLooksLikeToken(m string) bool {
	fields := strings.Fields(m)
	tok := fields[len(fields)-1]
	return strings.ContainsAny(tok, "0123456789._~+/=-")
}

// String returns s with every secret-shaped substring replaced by a
// [REDACTED:<kind>] tag, and adds each replacement to counts.
func String(s string, counts Counts) string {
	for _, r := range rules {
		s = r.re.ReplaceAllStringFunc(s, func(m string) string {
			if r.keep != nil && !r.keep(m) {
				return m
			}
			counts[r.kind]++
			return "[REDACTED:" + r.kind + "]"
		})
	}
	return s
}

// value redacts every string inside a decoded JSON value.
func value(v any, counts Counts) any {
	switch x := v.(type) {
	case string:
		return String(x, counts)
	case []any:
		for i := range x {
			x[i] = value(x[i], counts)
		}
	case map[string]any:
		for k := range x {
			x[k] = value(x[k], counts)
		}
	}
	return v
}

// Stream reads Call records, one JSON object per line, from in and writes them
// to out with every string value redacted. Blank lines are skipped and record
// order is kept. Numbers and other non-string values are written as read; keys
// come out in sorted order. An invalid line is an error that names the line
// number and never the line.
func Stream(in io.Reader, out io.Writer) (Counts, error) {
	counts := Counts{}
	r := bufio.NewReader(in)
	w := bufio.NewWriter(out)
	for n := 1; ; n++ {
		line, err := r.ReadBytes('\n')
		if len(bytes.TrimSpace(line)) > 0 {
			var rec map[string]any
			dec := json.NewDecoder(bytes.NewReader(line))
			dec.UseNumber()
			if derr := dec.Decode(&rec); derr != nil || rec == nil {
				return counts, fmt.Errorf("line %d is not a JSON object", n)
			}
			if _, derr := dec.Token(); derr != io.EOF {
				return counts, fmt.Errorf("line %d has data after the JSON object", n)
			}
			b, merr := json.Marshal(value(rec, counts))
			if merr != nil {
				return counts, fmt.Errorf("line %d cannot be encoded again", n)
			}
			w.Write(b)
			w.WriteByte('\n')
		}
		if err == io.EOF {
			break
		}
		if err != nil {
			return counts, err
		}
	}
	return counts, w.Flush()
}
