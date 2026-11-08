// Package modelclient turns a question into a Proposal {target, permission} or
// a typed Failure, through a Messages endpoint (Anthropic's API or
// OpenRouter's) with a strict lookup_permission tool. It knows nothing about the
// Caller. Only projects/agent-identity/internal/agent and projects/agent-identity/internal/eval may import it (trustlint R1).
package modelclient

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"regexp"
	"strings"
	"time"

	"github.com/travism26/harness-lab/projects/agent-identity/internal/provider"
)

const (
	anthropicVersion = "2026-10-21"
	toolName         = "lookup_permission"
	maxTokens        = 1024
	callTimeout      = 20 * time.Second
	maxBody          = 1 << 20
)

// Config is what a Client is given at startup.
type Config struct {
	// BaseURL is the API root; the client posts to BaseURL + "/v1/messages".
	BaseURL string
	APIKey  string
	// Model defaults to the Provider's DefaultModel in projects/agent-identity/internal/provider.
	Model string
	// Provider is "anthropic", "openrouter" or "stand-in". It labels each
	// Attempt and sets the auth style and the default Model (projects/agent-identity/internal/provider).
	Provider string
	// HTTPClient makes the request. Nil means http.DefaultClient; every call
	// also gets a 20s context deadline.
	HTTPClient *http.Client
}

// Model is the model id the Client calls.
func (c *Client) Model() string { return c.cfg.Model }

// Client calls the Model.
type Client struct {
	cfg  Config
	prov provider.Provider
}

// New builds a Client. An empty BaseURL or APIKey is an error.
func New(cfg Config) (*Client, error) {
	switch {
	case cfg.BaseURL == "":
		return nil, errors.New("modelclient: a base URL is required")
	case cfg.APIKey == "":
		return nil, errors.New("modelclient: an API key is required")
	}
	prov, _ := provider.Lookup(cfg.Provider)
	if cfg.Model == "" {
		cfg.Model = prov.DefaultModel
	}
	if cfg.HTTPClient == nil {
		cfg.HTTPClient = http.DefaultClient
	}
	cfg.BaseURL = strings.TrimSuffix(cfg.BaseURL, "/")
	return &Client{cfg: cfg, prov: prov}, nil
}

// Proposal is what the Model proposes: a name from the question or "self", and
// a permission.
type Proposal struct {
	Target     string `json:"target"`
	Permission string `json:"permission"`
}

// Attempt is the audit data of one Model call.
type Attempt struct {
	RequestID string
	Provider  string
	// Cost is in USD: reported by OpenRouter, computed from usage for
	// Anthropic, 0 for the stand-in.
	Cost float64
	// Raw is the reply body as received, for the Eval report. Empty when no
	// reply was read.
	Raw string
}

// Result is what Propose returns, with or without a Proposal.
type Result struct {
	Proposal Proposal
	Attempts []Attempt
}

// Kind says whether a failure gets a repair retry.
type Kind string

const (
	Retryable Kind = "retryable"
	Fatal     Kind = "fatal"
)

// FailureCode is the closed set of short names a Failure carries.
type FailureCode string

const (
	// CodeRefusal, CodeTextOnly, CodeStopReason and CodeProviderError are fatal.
	CodeRefusal       FailureCode = "refusal"
	CodeTextOnly      FailureCode = "text_only"
	CodeStopReason    FailureCode = "stop_reason"
	CodeProviderError FailureCode = "provider_error"
	// CodeToolUseCount, CodeToolName, CodeDecode and CodeFormat are retryable.
	CodeToolUseCount FailureCode = "tool_use_count"
	CodeToolName     FailureCode = "tool_name"
	CodeDecode       FailureCode = "decode"
	CodeFormat       FailureCode = "format"
)

// Failure is the typed failure Propose returns as its error.
type Failure struct {
	Kind Kind
	Code FailureCode
	// Text is the Model's text on a text-only reply, else empty.
	Text string
	msg  string
}

func (f *Failure) Error() string { return fmt.Sprintf("modelclient: %s %s: %s", f.Kind, f.Code, f.msg) }

var (
	targetRe     = regexp.MustCompile(`^[a-z][a-z0-9-]*$`)
	permissionRe = regexp.MustCompile(`^[a-z]+:[a-z]+$`)
)

const system = "You turn one question about who holds a permission into one call of the " +
	"lookup_permission tool. target is the name of the person or agent from the question, or " +
	"\"self\" when the question is about the asker. permission is resource:action in lowercase " +
	"letters, such as invoice:approve. The resource is singular: invoices becomes invoice, " +
	"permissions becomes permission. Two actions are known: read, which also covers view, see " +
	"and look up, and approve, which also covers sign off. Write any other permission as asked, " +
	"without mapping it onto these. Call the tool exactly once. If the question cannot be " +
	"turned into one lookup, do not call it."

var toolDef = map[string]any{
	"name":        toolName,
	"description": "Look up whether one target holds one permission.",
	"strict":      true,
	"input_schema": map[string]any{
		"type": "object",
		"properties": map[string]any{
			"target":     map[string]any{"type": "string", "description": "a name from the question in lowercase (Tom becomes tom), or self"},
			"permission": map[string]any{"type": "string", "description": "resource:action, lowercase"},
		},
		"required":             []string{"target", "permission"},
		"additionalProperties": false,
	},
}

// block is one content block of a reply. It keeps its bytes as received, so a
// repair retry echoes it unchanged: the API rejects a thinking block that comes
// back without its thinking and signature fields.
type block struct {
	Type  string          `json:"type"`
	ID    string          `json:"id,omitempty"`
	Name  string          `json:"name,omitempty"`
	Text  string          `json:"text,omitempty"`
	Input json.RawMessage `json:"input,omitempty"`
	raw   json.RawMessage
}

func (b *block) UnmarshalJSON(data []byte) error {
	type fields block
	var f fields
	if err := json.Unmarshal(data, &f); err != nil {
		return err
	}
	*b = block(f)
	b.raw = append(json.RawMessage(nil), data...)
	return nil
}

func (b block) MarshalJSON() ([]byte, error) {
	if b.raw != nil {
		return b.raw, nil
	}
	type fields block
	return json.Marshal(fields(b))
}

type response struct {
	ID         string  `json:"id"`
	StopReason string  `json:"stop_reason"`
	Content    []block `json:"content"`
	Usage      struct {
		InputTokens  float64  `json:"input_tokens"`
		OutputTokens float64  `json:"output_tokens"`
		Cost         *float64 `json:"cost"`
	} `json:"usage"`
}

// Propose asks the Model about one question: at most two calls, the second a
// repair retry after a retryable failure. On failure the error is a *Failure
// and the Result still lists the attempts made.
func (c *Client) Propose(ctx context.Context, question string) (Result, error) {
	var res Result
	messages := []any{map[string]any{"role": "user", "content": question}}
	for try := 0; ; try++ {
		resp, attempt, err := c.call(ctx, messages)
		res.Attempts = append(res.Attempts, attempt)
		if err != nil {
			return res, err
		}
		p, ferr := gate(resp)
		if ferr == nil {
			res.Proposal = p
			return res, nil
		}
		if ferr.Kind != Retryable || try == 1 {
			return res, ferr
		}
		// Echo the Model's turn, then answer it. Every tool_use block needs a
		// tool_result; with none, the error goes back as plain user text. Neither
		// message may carry null or empty content.
		assistant := any(resp.Content)
		if len(resp.Content) == 0 {
			assistant = []any{map[string]any{"type": "text", "text": "(no content)"}}
		}
		messages = append(messages, map[string]any{"role": "assistant", "content": assistant})
		var results []any
		for _, b := range resp.Content {
			if b.Type == "tool_use" {
				results = append(results, map[string]any{
					"type": "tool_result", "tool_use_id": b.ID, "is_error": true, "content": ferr.msg,
				})
			}
		}
		var reply any = results
		if len(results) == 0 {
			reply = ferr.msg
		}
		messages = append(messages, map[string]any{"role": "user", "content": reply})
	}
}

func providerError(msg string) *Failure {
	return &Failure{Kind: Fatal, Code: CodeProviderError, msg: msg}
}

func (c *Client) call(ctx context.Context, messages []any) (response, Attempt, error) {
	attempt := Attempt{Provider: c.cfg.Provider}
	body, err := json.Marshal(map[string]any{
		"model":         c.cfg.Model,
		"max_tokens":    maxTokens,
		"system":        system,
		"messages":      messages,
		"tools":         []any{toolDef},
		"tool_choice":   map[string]any{"type": "auto", "disable_parallel_tool_use": true},
		"output_config": map[string]any{"effort": "low"},
	})
	if err != nil {
		return response{}, attempt, providerError("could not encode the request")
	}
	ctx, cancel := context.WithTimeout(ctx, callTimeout)
	defer cancel()
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.cfg.BaseURL+"/v1/messages", bytes.NewReader(body))
	if err != nil {
		return response{}, attempt, providerError("could not build the request")
	}
	req.Header.Set("Content-Type", "application/json")
	if c.prov.BearerAuth {
		req.Header.Set("Authorization", "Bearer "+c.cfg.APIKey)
	} else {
		req.Header.Set("x-api-key", c.cfg.APIKey)
		req.Header.Set("anthropic-version", anthropicVersion)
	}
	hr, err := c.cfg.HTTPClient.Do(req)
	if err != nil {
		// The raw error may carry the URL; keep only that the call failed.
		return response{}, attempt, providerError("request failed")
	}
	defer hr.Body.Close()
	attempt.RequestID = hr.Header.Get("Request-Id")
	raw, err := io.ReadAll(io.LimitReader(hr.Body, maxBody))
	attempt.Raw = string(raw)
	if err != nil || hr.StatusCode != http.StatusOK {
		return response{}, attempt, providerError(fmt.Sprintf("status %d", hr.StatusCode))
	}
	var out response
	if err := json.Unmarshal(raw, &out); err != nil {
		return response{}, attempt, providerError("unreadable reply")
	}
	if attempt.RequestID == "" {
		attempt.RequestID = out.ID
	}
	attempt.Cost = c.cost(out)
	return out, attempt, nil
}

// price is USD per million input and output tokens.
type price struct{ input, output float64 }

// pricesPerMillion is the price per model id (projects/agent-identity/docs/adr/0003-anthropic-api-as-a-second-model-provider.md).
var pricesPerMillion = map[string]price{
	"claude-haiku-5-5":  {input: 0.10, output: 0.50},
	"claude-sonnet-5-5": {input: 2, output: 10},
	"claude-opus-5-5":   {input: 4, output: 20},
}

func (c *Client) cost(r response) float64 {
	if r.Usage.Cost != nil {
		return *r.Usage.Cost
	}
	if !c.prov.PricedByTable {
		return 0
	}
	p := pricesPerMillion[c.cfg.Model]
	return (r.Usage.InputTokens*p.input + r.Usage.OutputTokens*p.output) / 1e6
}

// gate applies the five rules in order.
func gate(r response) (Proposal, *Failure) {
	if r.StopReason == "refusal" {
		return Proposal{}, &Failure{Kind: Fatal, Code: CodeRefusal, msg: "the Model refused"}
	}
	if r.StopReason != "tool_use" {
		var text []string
		for _, b := range r.Content {
			if b.Type == "text" {
				text = append(text, b.Text)
			}
		}
		if r.StopReason == "end_turn" && len(text) > 0 {
			return Proposal{}, &Failure{Kind: Fatal, Code: CodeTextOnly, Text: strings.Join(text, "\n"), msg: "text-only reply"}
		}
		return Proposal{}, &Failure{Kind: Fatal, Code: CodeStopReason, msg: "stop_reason " + r.StopReason}
	}
	var uses []block
	for _, b := range r.Content {
		if b.Type == "tool_use" {
			uses = append(uses, b)
		}
	}
	if len(uses) != 1 {
		return Proposal{}, &Failure{Kind: Retryable, Code: CodeToolUseCount, msg: fmt.Sprintf("call %s exactly once, not %d times", toolName, len(uses))}
	}
	if uses[0].Name != toolName {
		return Proposal{}, &Failure{Kind: Retryable, Code: CodeToolName, msg: "the only tool is " + toolName}
	}
	var p Proposal
	dec := json.NewDecoder(bytes.NewReader(uses[0].Input))
	dec.DisallowUnknownFields()
	if err := dec.Decode(&p); err != nil || p.Target == "" || p.Permission == "" {
		return Proposal{}, &Failure{Kind: Retryable, Code: CodeDecode, msg: "input must be exactly {target, permission}, both non-empty strings"}
	}
	if p.Target != "self" && !targetRe.MatchString(p.Target) {
		return Proposal{}, &Failure{Kind: Retryable, Code: CodeFormat, msg: "target must be self or match ^[a-z][a-z0-9-]*$"}
	}
	if !permissionRe.MatchString(p.Permission) {
		return Proposal{}, &Failure{Kind: Retryable, Code: CodeFormat, msg: "permission must match ^[a-z]+:[a-z]+$"}
	}
	return p, nil
}
