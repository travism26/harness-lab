package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"testing"

	"github.com/travism26/harness-lab/projects/agent-identity/internal/agent"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/broker"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/warden"
)

// TestMain keeps default run directories out of the source tree.
func TestMain(m *testing.M) {
	dir, err := os.MkdirTemp("", "demo-runs")
	if err != nil {
		panic(err)
	}
	runsBase = dir
	code := m.Run()
	os.RemoveAll(dir)
	os.Exit(code)
}

func decodeFile[T any](t *testing.T, path string) []T {
	t.Helper()
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var out []T
	for _, line := range strings.Split(strings.TrimSpace(string(raw)), "\n") {
		dec := json.NewDecoder(strings.NewReader(line))
		dec.DisallowUnknownFields()
		var r T
		if err := dec.Decode(&r); err != nil {
			t.Fatalf("%s: line %q: %v", path, line, err)
		}
		out = append(out, r)
	}
	return out
}

func lastLine(s string) string {
	lines := strings.Split(strings.TrimSpace(s), "\n")
	return lines[len(lines)-1]
}

func TestTourWritesBothLogsAndNamesTheDirectoryLast(t *testing.T) {
	dir := t.TempDir()
	_, errOut, code := replyOut("tour", "--out", dir)
	if code != 0 {
		t.Fatalf("exit %d: %s", code, errOut)
	}
	if last := lastLine(errOut); !strings.Contains(last, dir) {
		t.Errorf("last stderr line %q does not name %s", last, dir)
	}
	agentRecs := decodeFile[agent.AuditRecord](t, filepath.Join(dir, "agent.audit.jsonl"))
	wardenRecs := decodeFile[warden.AuditRecord](t, filepath.Join(dir, "warden.audit.jsonl"))
	// tokens (3) + scripted (3) + ask (1), one record each per service.
	if len(agentRecs) != 7 || len(wardenRecs) != 7 {
		t.Fatalf("got %d Agent and %d Warden records; want 7 each", len(agentRecs), len(wardenRecs))
	}
	seen := map[string]int{}
	for _, r := range agentRecs {
		seen[r.CorrelationID]++
	}
	for _, r := range wardenRecs {
		seen[r.CorrelationID]++
	}
	for id, n := range seen {
		if n != 2 {
			t.Errorf("Correlation ID %s has %d records; want 2", id, n)
		}
	}
}

func TestDefaultRunDirectoryIsAUTCTimestampUnderRuns(t *testing.T) {
	_, errOut, code := replyOut("ask", "Can Tom approve invoices?")
	if code != 0 {
		t.Fatalf("exit %d: %s", code, errOut)
	}
	re := regexp.MustCompile(regexp.QuoteMeta(runsBase) + `/\d{8}T\d{6}Z\S*$`)
	dir := re.FindString(lastLine(errOut))
	if dir == "" {
		t.Fatalf("last stderr line %q names no run directory", lastLine(errOut))
	}
	for _, f := range []string{"agent.audit.jsonl", "warden.audit.jsonl"} {
		if _, err := os.Stat(filepath.Join(dir, f)); err != nil {
			t.Error(err)
		}
	}
}

func TestTraceIsBuiltFromTheRecordsJustWritten(t *testing.T) {
	dir := t.TempDir()
	_, errOut, code := replyOut("ask", "Can Tom approve invoices?", "--out", dir)
	if code != 0 {
		t.Fatal(errOut)
	}
	agentRec := decodeFile[agent.AuditRecord](t, filepath.Join(dir, "agent.audit.jsonl"))[0]
	for _, want := range []string{
		"proposal", "target=" + agentRec.Proposal.Target, "permission=" + agentRec.Proposal.Permission,
		"status=200", "outcome=answer_yes", "correlation_id=" + agentRec.CorrelationID,
	} {
		if !strings.Contains(errOut, want) {
			t.Errorf("stderr lacks %q:\n%s", want, errOut)
		}
	}
}

func TestAnUnwritableOutDirectoryExitsNonZero(t *testing.T) {
	file := filepath.Join(t.TempDir(), "afile")
	if err := os.WriteFile(file, nil, 0o600); err != nil {
		t.Fatal(err)
	}
	if _, _, code := replyOut("scripted", "--out", file); code != 1 {
		t.Errorf("exit %d; want 1", code)
	}
}

func TestTwoAsksIntoOneOutKeepBothRunsRecordsJoinedByCorrelationID(t *testing.T) {
	dir := t.TempDir()
	var traces []string
	for i := 0; i < 2; i++ {
		_, errOut, code := replyOut("ask", "Can Tom approve invoices?", "--out", dir)
		if code != 0 {
			t.Fatal(errOut)
		}
		traces = append(traces, errOut)
	}

	agents := decodeFile[agent.AuditRecord](t, filepath.Join(dir, "agent.audit.jsonl"))
	wardens := decodeFile[warden.AuditRecord](t, filepath.Join(dir, "warden.audit.jsonl"))
	brokers := decodeFile[broker.AuditRecord](t, filepath.Join(dir, "broker.audit.jsonl"))
	if len(agents) != 2 || len(wardens) != 2 || len(brokers) != 2 {
		t.Fatalf("records agent/warden/broker = %d/%d/%d; want 2 each", len(agents), len(wardens), len(brokers))
	}
	for i, a := range agents {
		if wardens[i].CorrelationID != a.CorrelationID || brokers[i].CorrelationID != a.CorrelationID {
			t.Errorf("run %d: Agent %s, Warden %s, Broker %s; want one Correlation ID", i, a.CorrelationID, wardens[i].CorrelationID, brokers[i].CorrelationID)
		}
		// The trace names only this run's records.
		if strings.Count(traces[i], "correlation_id="+a.CorrelationID) != 2 || strings.Contains(traces[i], agents[1-i].CorrelationID) {
			t.Errorf("run %d trace is not just its own run:\n%s", i, traces[i])
		}
	}
}
