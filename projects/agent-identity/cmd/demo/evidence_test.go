package main

import (
	"bytes"
	"flag"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"testing"

	"github.com/travism26/harness-lab/projects/agent-identity/internal/agent"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/broker"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/login"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/warden"
)

// update regenerates projects/agent-identity/docs/evidence/tour.txt:
// go test ./cmd/demo -run TestTourTranscript -update
var update = flag.Bool("update", false, "rewrite docs/evidence/tour.txt from a fresh stand-in tour")

const evidenceDir = "../../docs/evidence"

var (
	correlationIDMask = regexp.MustCompile(`\b[0-9a-f]{32}\b`)
	timeMask          = regexp.MustCompile(`time=\S+`)
	portMask          = regexp.MustCompile(`127\.0\.0\.1:[0-9]+`)
	// jwtShaped is three base64url segments joined by dots, the compact JWS form.
	jwtShaped = regexp.MustCompile(`[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+`)
	// keyShaped is what a provider key looks like: Anthropic's and OpenRouter's
	// both start sk- and run on in base64url.
	keyShaped = regexp.MustCompile(`sk-[A-Za-z0-9_-]{8,}`)
)

// maskTour replaces what changes from run to run: Correlation IDs,
// timestamps, Warden ports and the run directory.
func maskTour(s, runDir string) string {
	s = strings.ReplaceAll(s, runDir, "<run-dir>")
	s = correlationIDMask.ReplaceAllString(s, "<correlation-id>")
	s = timeMask.ReplaceAllString(s, "time=<ts>")
	return portMask.ReplaceAllString(s, "127.0.0.1:<port>")
}

// TestTourTranscript compares a fresh stand-in tour with the committed
// transcript in projects/agent-identity/docs/evidence/tour.txt.
func TestTourTranscript(t *testing.T) {
	dir := t.TempDir()
	var stdout, stderr bytes.Buffer
	if code := run([]string{"tour", "--out", dir}, &stdout, &stderr); code != 0 {
		t.Fatalf("tour exit %d, stderr: %s", code, stderr.String())
	}
	got := maskTour("$ go run ./cmd/demo tour\n# stdout\n"+stdout.String()+"# stderr\n"+stderr.String(), dir)
	path := filepath.Join(evidenceDir, "tour.txt")
	if *update {
		if err := os.WriteFile(path, []byte(got), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	want, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if got != string(want) {
		t.Errorf("stand-in tour differs from %s (regenerate with -update):\n got:\n%s\nwant:\n%s", path, got, want)
	}
}

// TestSampleRunLogs holds the committed live Audit logs to the record structs:
// every line decodes strictly, the two files share their Correlation IDs, and
// no token or key appears. The third log, the Broker's, comes from a fresh
// stand-in tour until a live run through the Broker is committed.
func TestSampleRunLogs(t *testing.T) {
	sample := filepath.Join(evidenceDir, "sample-run")
	agentRecs := decodeFile[agent.AuditRecord](t, filepath.Join(sample, "agent.audit.jsonl"))
	wardenRecs := decodeFile[warden.AuditRecord](t, filepath.Join(sample, "warden.audit.jsonl"))
	if len(agentRecs) == 0 || len(agentRecs) != len(wardenRecs) {
		t.Fatalf("got %d agent and %d warden records, want the same nonzero count", len(agentRecs), len(wardenRecs))
	}
	for i := range agentRecs {
		if a, w := agentRecs[i].CorrelationID, wardenRecs[i].CorrelationID; a != w {
			t.Errorf("record %d: agent correlation_id %s, warden %s", i, a, w)
		}
	}
	for _, name := range []string{"agent.audit.jsonl", "warden.audit.jsonl"} {
		assertNoTokenOrKey(t, filepath.Join(sample, name))
	}

	// The tour's three logs: strict decoding, one Correlation ID per question
	// across all three, and no token or key in any of them.
	dir := t.TempDir()
	var stdout, stderr bytes.Buffer
	if code := run([]string{"tour", "--out", dir}, &stdout, &stderr); code != 0 {
		t.Fatalf("tour exit %d, stderr: %s", code, stderr.String())
	}
	tourAgent := decodeFile[agent.AuditRecord](t, filepath.Join(dir, "agent.audit.jsonl"))
	tourBroker := decodeFile[broker.AuditRecord](t, filepath.Join(dir, "broker.audit.jsonl"))
	// One record for the tour's question, then the broker scenario's four.
	if len(tourBroker) != 5 {
		t.Fatalf("got %d Broker records, want 5 (the tour's question and four broker outcomes)", len(tourBroker))
	}
	for i, want := range []struct {
		status int
		reason string
	}{{200, ""}, {401, "jwt_svid_audience"}, {403, "not_allowlisted"}, {403, "outside_pin"}} {
		if r := tourBroker[i+1]; r.Status != want.status || r.Reason != want.reason {
			t.Errorf("broker scenario record %d = status %d reason %q; want %d %q", i, r.Status, r.Reason, want.status, want.reason)
		}
	}
	b := tourBroker[0]
	var asked agent.AuditRecord
	for _, r := range tourAgent {
		if r.Question != "" {
			asked = r
		}
	}
	if b.CorrelationID != asked.CorrelationID || b.Outcome != broker.OutcomeAllowed || b.SPIFFEID != permissionAgent.String() ||
		b.Provider != "stand-in" || b.RequestID == "" || b.InputTokens == 0 || b.OutputTokens == 0 {
		t.Errorf("Broker record %+v does not match the Agent's %s", b, asked.CorrelationID)
	}
	for _, name := range []string{"agent.audit.jsonl", "warden.audit.jsonl", "broker.audit.jsonl"} {
		assertNoTokenOrKey(t, filepath.Join(dir, name))
	}
}

// assertNoTokenOrKey fails if the file holds a JWT-shaped or a key-shaped string.
func assertNoTokenOrKey(t *testing.T, path string) {
	t.Helper()
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if m := jwtShaped.Find(raw); m != nil {
		t.Errorf("%s holds a JWT-shaped string: %.20s…", path, m)
	}
	if m := keyShaped.Find(raw); m != nil {
		t.Errorf("%s holds a key-shaped string: %.8s…", path, m)
	}
}

// TestKeyShapedCatchesAProviderKey keeps the key check honest.
func TestKeyShapedCatchesAProviderKey(t *testing.T) {
	for _, k := range []string{"sk-ant-api03-AbCdEf123456_-xyz", "sk-or-v1-0123456789abcdef"} {
		if !keyShaped.MatchString(k) {
			t.Errorf("keyShaped does not match %q", k)
		}
	}
}

// TestJWTShapedCatchesARealToken keeps the sample-log check honest: a token
// the Login signs must match it.
func TestJWTShapedCatchesARealToken(t *testing.T) {
	lg, err := login.New(nil)
	if err != nil {
		t.Fatal(err)
	}
	tok, err := lg.Sign("acme/alice", wardenAud, permissionAgent.String())
	if err != nil {
		t.Fatal(err)
	}
	if !jwtShaped.MatchString(string(tok)) {
		t.Error("jwtShaped does not match a signed Caller assertion")
	}
}
