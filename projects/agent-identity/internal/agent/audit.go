package agent

import (
	"encoding/json"
	"time"

	"github.com/travism26/harness-lab/projects/agent-identity/internal/modelclient"
)

// maxModelText is the longest model_text an Audit record carries, in characters.
const maxModelText = 500

// AuditRecord is the Agent's Audit record: one JSON line per question or per
// scripted Lookup. The field set is the struct, and it has no catch-all field,
// so no token, key, raw HTTP body, prompt or raw error can land in it. Of the
// Model's output, only model_text is kept, and only on a text-only reply.
type AuditRecord struct {
	TS               time.Time `json:"ts"`
	CorrelationID    string    `json:"correlation_id"`
	CallerUnverified string    `json:"caller_unverified"`
	Question         string    `json:"question,omitempty"`
	// Backend is "stand-in" or "live"; Model, Attempts, ModelCalls, Proposal and
	// ModelFailure are absent on a scripted Lookup.
	Backend      string        `json:"backend,omitempty"`
	Model        string        `json:"model,omitempty"`
	Attempts     int           `json:"attempts,omitempty"`
	Proposal     *Proposal     `json:"proposal,omitempty"`
	ModelFailure *ModelFailure `json:"model_failure,omitempty"`
	ModelText    string        `json:"model_text,omitempty"`
	// WardenStatus is absent when the Warden gave no response.
	WardenStatus int `json:"warden_status,omitempty"`
	// Reply is one of the eight Reply ids; absent on a scripted Lookup.
	Reply      string      `json:"reply,omitempty"`
	ModelCalls []ModelCall `json:"model_calls,omitempty"`
}

// Proposal is the Model's {target, permission}.
type Proposal struct {
	Target     string `json:"target"`
	Permission string `json:"permission"`
}

// ModelFailure is why the Model gave no Proposal: kind is retryable or fatal.
type ModelFailure struct {
	Kind string `json:"kind"`
	Code string `json:"code"`
}

// ModelCall is the audit data of one Model call.
type ModelCall struct {
	RequestID string  `json:"request_id,omitempty"`
	Provider  string  `json:"provider"`
	Cost      float64 `json:"cost"`
}

// backendFor labels a provider as the stand-in or live.
func backendFor(provider string) string {
	if provider == "stand-in" {
		return "stand-in"
	}
	return "live"
}

// modelCalls keeps only the audit fields of each attempt, never Raw.
func modelCalls(attempts []modelclient.Attempt) []ModelCall {
	out := make([]ModelCall, 0, len(attempts))
	for _, a := range attempts {
		out = append(out, ModelCall{RequestID: a.RequestID, Provider: a.Provider, Cost: a.Cost})
	}
	return out
}

// truncate cuts s to at most n characters.
func truncate(s string, n int) string {
	if r := []rune(s); len(r) > n {
		return string(r[:n])
	}
	return s
}

func (a *Agent) writeAudit(rec AuditRecord) {
	if a.cfg.Audit == nil {
		return
	}
	rec.TS = time.Now().UTC()
	line, err := json.Marshal(rec)
	if err != nil {
		return
	}
	a.auditMu.Lock()
	defer a.auditMu.Unlock()
	_, _ = a.cfg.Audit.Write(append(line, '\n'))
}
