package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"log/slog"
	"os"
	"path/filepath"
	"sync"
	"time"

	"github.com/travism26/harness-lab/projects/agent-identity/internal/agent"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/broker"
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
}

func (l *recordLog) Write(p []byte) (int, error) {
	l.mu.Lock()
	defer l.mu.Unlock()
	l.buf.Write(p)
	return l.file.Write(p)
}

// records decodes the lines written so far.
func records[T any](l *recordLog) []T {
	l.mu.Lock()
	defer l.mu.Unlock()
	var out []T
	for _, line := range bytes.Split(l.buf.Bytes(), []byte("\n")) {
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
// runsBase) and opens the three logs in it.
func openAudit(out string) (*auditSink, error) {
	dir := out
	if dir == "" {
		stamp := time.Now().UTC().Format("20060102T150405Z")
		dir = filepath.Join(runsBase, stamp)
		for n := 2; ; n++ {
			err := os.MkdirAll(runsBase, 0o755)
			if err == nil {
				err = os.Mkdir(dir, 0o755)
			}
			if err == nil {
				break
			}
			if !errors.Is(err, fs.ErrExist) {
				return nil, err
			}
			dir = filepath.Join(runsBase, fmt.Sprintf("%s-%d", stamp, n))
		}
	} else if err := os.MkdirAll(dir, 0o755); err != nil {
		return nil, err
	}
	s := &auditSink{dir: dir}
	var err error
	if s.agent, err = openLog(filepath.Join(dir, "agent.audit.jsonl")); err != nil {
		return nil, err
	}
	if s.warden, err = openLog(filepath.Join(dir, "warden.audit.jsonl")); err != nil {
		s.agent.file.Close()
		return nil, err
	}
	if s.broker, err = openLog(filepath.Join(dir, "broker.audit.jsonl")); err != nil {
		s.agent.file.Close()
		s.warden.file.Close()
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
	s.agent.file.Close()
	s.warden.file.Close()
	s.broker.file.Close()
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
