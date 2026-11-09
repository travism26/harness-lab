package broker

import (
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"regexp"
	"time"
)

// usage is the token counts a provider reported.
type usage struct{ in, out int }

// AuditRecord is the Broker's Audit record: one JSON line per Model request.
// The field set is the struct, and it has no catch-all field, so no provider
// key, JWT-SVID, request body or raw error can land in it. The Broker never
// reads the Caller assertion, so it has no field for it either. SPIFFEID is set
// only once the JWT-SVID has verified.
type AuditRecord struct {
	TS            time.Time `json:"ts"`
	CorrelationID string    `json:"correlation_id"`
	SPIFFEID      string    `json:"spiffe_id,omitempty"`
	Provider      string    `json:"provider"`
	Model         string    `json:"model,omitempty"`
	Outcome       Outcome   `json:"outcome"`
	Status        int       `json:"status"`
	// Reason is a jwt_svid_* code or a Broker reason, on a non-allowed outcome.
	Reason string `json:"reason,omitempty"`
	// UpstreamStatus is the provider's status on upstream_error (0: unreachable).
	UpstreamStatus int `json:"upstream_status,omitempty"`
	// RequestID is the provider's request id.
	RequestID    string  `json:"request_id,omitempty"`
	InputTokens  int     `json:"input_tokens,omitempty"`
	OutputTokens int     `json:"output_tokens,omitempty"`
	Cost         float64 `json:"cost,omitempty"`
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

// writeAudit writes rec, completed from s, as one Audit record.
func (b *Broker) writeAudit(rec AuditRecord, s settled) {
	if b.audit == nil {
		return
	}
	rec.TS = b.now().UTC()
	rec.Outcome, rec.Status, rec.Reason, rec.UpstreamStatus = s.outcome, s.status, s.reason, s.upstreamStatus
	rec.RequestID, rec.InputTokens, rec.OutputTokens, rec.Cost = s.requestID, s.usage.in, s.usage.out, s.cost
	if s.model != "" {
		rec.Model = s.model
	}
	line, err := json.Marshal(rec)
	if err != nil {
		b.log.Error("audit record not encoded")
		return
	}
	b.auditMu.Lock()
	defer b.auditMu.Unlock()
	if _, err := b.audit.Write(append(line, '\n')); err != nil {
		b.log.Error("audit record not written")
	}
}
