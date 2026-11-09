package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"log/slog"
	"os"
	"path/filepath"
	"sync"

	"github.com/travism26/harness-lab/projects/agent-identity/internal/agent"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/broker"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/rundir"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/warden"
)

// runsBase is where a run directory goes when --out is not given.
var runsBase = "runs"

// recordLog is one Audit log: every line goes to its file and to a copy in
// memory, so the trace can be built from what was just written.
type recordLog struct {
	mu   sync.Mutex
	file *os.File
	buf  bytes.Buffer
	// readPath, for a log another process writes (a live run's Broker), is the
	// file records reads; the demo never writes or truncates it. file is nil.
	readPath string
}

func (l *recordLog) Write(p []byte) (int, error) {
	l.mu.Lock()
	defer l.mu.Unlock()
	if l.file == nil {
		return 0, errors.New("audit log is read-only here")
	}
	l.buf.Write(p)
	return l.file.Write(p)
}

func (l *recordLog) close() {
	if l.file != nil {
		l.file.Close()
	}
}

// records decodes the lines written so far.
func records[T any](l *recordLog) []T {
	l.mu.Lock()
	defer l.mu.Unlock()
	data := l.buf.Bytes()
	if l.file == nil {
		data, _ = os.ReadFile(l.readPath)
	}
	var out []T
	for _, line := range bytes.Split(data, []byte("\n")) {
		var r T
		if len(line) > 0 && json.Unmarshal(line, &r) == nil {
			out = append(out, r)
		}
	}
	return out
}

// auditSink is the run directory and the three Audit logs written into it.
type auditSink struct {
	dir    string
	agent  *recordLog
	warden *recordLog
	broker *recordLog
}

// openAudit makes the run directory (out, or a UTC-timestamped one under
// runsBase) and opens the three logs in it. With externalBroker the Broker log
// is another process's: it is only read, never created or truncated.
func openAudit(out string, externalBroker bool) (*auditSink, error) {
	dir, err := rundir.Make(out, runsBase)
	if err != nil {
		return nil, err
	}
	s := &auditSink{dir: dir}
	if s.agent, err = openLog(filepath.Join(dir, "agent.audit.jsonl")); err != nil {
		return nil, err
	}
	if s.warden, err = openLog(filepath.Join(dir, "warden.audit.jsonl")); err != nil {
		s.agent.close()
		return nil, err
	}
	brokerPath := filepath.Join(dir, "broker.audit.jsonl")
	if externalBroker {
		s.broker = &recordLog{readPath: brokerPath}
		return s, nil
	}
	if s.broker, err = openLog(brokerPath); err != nil {
		s.agent.close()
		s.warden.close()
		return nil, err
	}
	return s, nil
}

func openLog(path string) (*recordLog, error) {
	f, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_TRUNC, 0o644)
	if err != nil {
		return nil, err
	}
	return &recordLog{file: f}, nil
}

func (s *auditSink) close() {
	s.agent.close()
	s.warden.close()
	s.broker.close()
}

// trace logs the steps of one question, built from the Audit records just
// written for its Correlation ID rather than from the run's own variables.
func (s *auditSink) trace(log *slog.Logger, correlationID string) {
	var ar *agent.AuditRecord
	for _, r := range records[agent.AuditRecord](s.agent) {
		if r.CorrelationID == correlationID {
			ar = &r
		}
	}
	if ar == nil {
		return
	}
	if p := ar.Proposal; p != nil {
		log.Info("proposal", "target", p.Target, "permission", p.Permission, "model_calls", ar.Attempts, "correlation_id", ar.CorrelationID)
	} else {
		attrs := []any{"model_calls", ar.Attempts, "correlation_id", ar.CorrelationID}
		if f := ar.ModelFailure; f != nil {
			attrs = append(attrs, "model_failure", f.Code)
		}
		log.Info("no proposal", attrs...)
	}
	for _, b := range records[broker.AuditRecord](s.broker) {
		if b.CorrelationID == correlationID {
			attrs := []any{"status", b.Status, "outcome", b.Outcome}
			if b.Reason != "" {
				attrs = append(attrs, "reason", b.Reason)
			}
			log.Info("broker", attrs...)
		}
	}
	for _, w := range records[warden.AuditRecord](s.warden) {
		if w.CorrelationID == correlationID {
			attrs := []any{"status", w.Status, "outcome", w.Outcome}
			if w.FailedCheck != "" {
				attrs = append(attrs, "failed_check", w.FailedCheck)
			}
			if w.Reason != "" {
				attrs = append(attrs, "reason", w.Reason)
			}
			log.Info("warden", attrs...)
		}
	}
	log.Info("reply", "id", ar.Reply, "correlation_id", ar.CorrelationID)
}
