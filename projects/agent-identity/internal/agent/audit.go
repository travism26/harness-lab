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
	Reply      ReplyID     `json:"reply,omitempty"`
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
	// BrokerStatus and BrokerReason are the Broker's status and reason code
	// when it refused or failed the request, so this log explains a
	// Model-unreachable Reply on its own.
	BrokerStatus int    `json:"broker_status,omitempty"`
	BrokerReason string `json:"broker_reason,omitempty"`
}

// ModelCall is the audit data of one Model call.
type ModelCall struct {
	RequestID string  `json:"request_id,omitempty"`
	Provider  string  `json:"provider"`
	Cost      float64 `json:"cost"`
	// Model, the token counts and BrokerReported are set only through the
	// Broker. BrokerReported says provider, model, cost and request id are what
	// the Broker told the Agent; the Broker's own record is the authoritative one.
	Model          string `json:"model,omitempty"`
	InputTokens    int    `json:"input_tokens,omitempty"`
	OutputTokens   int    `json:"output_tokens,omitempty"`
	BrokerReported bool   `json:"broker_reported,omitempty"`
}

// backendFor labels a provider as the stand-in or live.
func backendFor(provider string) string {
	if provider == backendStandIn {
		return backendStandIn
	}
	return "live"
}

const backendStandIn = "stand-in"

// modelCalls keeps only the audit fields of each attempt, never Raw.
func modelCalls(attempts []modelclient.Attempt) []ModelCall {
	out := make([]ModelCall, 0, len(attempts))
	for _, a := range attempts {
		out = append(out, ModelCall{
			RequestID: a.RequestID, Provider: a.Provider, Cost: a.Cost,
			Model: a.Model, InputTokens: a.InputTokens, OutputTokens: a.OutputTokens, BrokerReported: true,
		})
	}
	return out
}

// brokerServed is the backend and model the Broker reported on the last call
// that got a reply, both empty if none did. A stand-in never shows a model id.
func brokerServed(calls []ModelCall) (backend, model string) {
	for i := len(calls) - 1; i >= 0; i-- {
		if p := calls[i].Provider; p != "" {
			if p == backendStandIn {
				return backendStandIn, backendStandIn
			}
			return backendFor(p), calls[i].Model
		}
	}
	return "", ""
}

// brokerFooter names what served the question and that the Broker did:
// "stand-in via broker", "anthropic/claude-haiku-5-5 via broker", or "unknown
// via broker" when the Broker gave no reply to say.
func brokerFooter(calls []ModelCall) string {
	for i := len(calls) - 1; i >= 0; i-- {
		switch p := calls[i].Provider; p {
		case "":
		case backendStandIn:
			return backendStandIn + " via broker"
		default:
			return p + "/" + calls[i].Model + " via broker"
		}
	}
	return "unknown via broker"
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
