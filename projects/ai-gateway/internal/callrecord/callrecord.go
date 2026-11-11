// Package callrecord defines the Call record: the one closed JSON object the
// Gateway appends for a Call. It has no field that can hold a Forwarded
// credential; projects/ai-gateway/internal/secrettype checks that.
package callrecord

import (
	"encoding/json"
	"io"
	"sync"
)

// Usage holds the token counts of a response.
type Usage struct {
	InputTokens              int64 `json:"input_tokens"`
	OutputTokens             int64 `json:"output_tokens"`
	CacheCreationInputTokens int64 `json:"cache_creation_input_tokens"`
	CacheReadInputTokens     int64 `json:"cache_read_input_tokens"`
}

// Record is one Call record. A Hint field is nil, and so absent from the JSON,
// when its request header was not sent.
type Record struct {
	Ts            string `json:"ts"`
	SessionID     string `json:"x-claude-code-session-id"`
	AgentID       string `json:"x-claude-code-agent-id"`
	ParentAgentID string `json:"x-claude-code-parent-agent-id"`
	Model         string `json:"model"`
	RequestBody   string `json:"request_body"`
	ResponseBody  string `json:"response_body"`
	Status        int    `json:"status"`
	Failure       bool   `json:"failure"`
	LatencyMS     int64  `json:"latency_ms"`
	Usage         Usage  `json:"usage"`

	RequestClass      *string `json:"x-claude-code-request-class,omitempty"`
	AgentType         *string `json:"x-claude-code-agent-type,omitempty"`
	Compaction        *string `json:"x-claude-code-compaction,omitempty"`
	ContextCompacted  *string `json:"x-claude-code-context-compacted,omitempty"`
	PrevToolDurations *string `json:"x-claude-code-prev-tool-durations,omitempty"`
	PromptID          *string `json:"x-claude-code-prompt-id,omitempty"`
}

// Writer appends Call records to w, one line each, under a mutex.
type Writer struct {
	mu sync.Mutex
	w  io.Writer
}

// NewWriter returns a Writer. w must not buffer: each line is one Write.
func NewWriter(w io.Writer) *Writer { return &Writer{w: w} }

// Append writes r as one JSON line.
func (w *Writer) Append(r Record) error {
	b, err := json.Marshal(r)
	if err != nil {
		return err
	}
	b = append(b, '\n')
	w.mu.Lock()
	defer w.mu.Unlock()
	_, err = w.w.Write(b)
	return err
}
