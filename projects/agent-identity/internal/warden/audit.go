package warden

import (
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"regexp"
	"time"
)

// AuditRecord is the Warden's Audit record: one JSON line per Lookup. The field
// set is the struct, and it has no catch-all field, so no token, key, body or
// raw error can land in it. Agent and Caller are set only once their token has
// verified.
type AuditRecord struct {
	TS            time.Time   `json:"ts"`
	CorrelationID string      `json:"correlation_id"`
	Status        int         `json:"status"`
	Outcome       Outcome     `json:"outcome"`
	FailedCheck   FailedCheck `json:"failed_check,omitempty"`
	Reason        Reason      `json:"reason,omitempty"`
	Agent         string      `json:"agent,omitempty"`
	Caller        string      `json:"caller,omitempty"`
	Target        string      `json:"target,omitempty"`
	Permission    string      `json:"permission,omitempty"`
	Role          string      `json:"role,omitempty"`
	// RejectedCorrelationIDLen is the length of a Correlation-Id header that was
	// not 32 lowercase hex characters. Its content is never recorded.
	RejectedCorrelationIDLen *int `json:"rejected_correlation_id_len,omitempty"`
}

var correlationIDRe = regexp.MustCompile(`^[0-9a-f]{32}$`)

// correlationID returns the request's Correlation ID if it is valid, otherwise
// a fresh one and the rejected header's length (nil if the header was absent).
func correlationID(header string) (id string, rejectedLen *int) {
	if correlationIDRe.MatchString(header) {
		return header, nil
	}
	b := make([]byte, 16)
	if _, err := rand.Read(b); err != nil {
		panic(err) // crypto/rand does not fail on supported platforms
	}
	if header != "" {
		n := len(header)
		rejectedLen = &n
	}
	return hex.EncodeToString(b), rejectedLen
}

// writeAudit writes the Decision as one Audit record.
func (w *Warden) writeAudit(d Decision) {
	if w.audit == nil {
		return
	}
	line, err := json.Marshal(AuditRecord{
		TS: w.now().UTC(), CorrelationID: d.CorrelationID, Status: d.Status, Outcome: d.Outcome,
		FailedCheck: d.FailedCheck, Reason: d.Reason, Agent: d.Agent, Caller: d.Caller,
		Target: d.Target, Permission: d.Permission, Role: d.Role,
		RejectedCorrelationIDLen: d.RejectedCorrelationIDLen,
	})
	if err != nil {
		w.log.Error("audit record not encoded")
		return
	}
	w.auditMu.Lock()
	defer w.auditMu.Unlock()
	if _, err := w.audit.Write(append(line, '\n')); err != nil {
		w.log.Error("audit record not written")
	}
}
