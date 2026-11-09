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
	"strconv"
	"strings"
	"time"

	"github.com/travism26/harness-lab/projects/agent-identity/internal/pin"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/provider"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/wire"
)

const (
	toolName    = "lookup_permission"
	maxTokens   = 1024
	callTimeout = 20 * time.Second
	maxBody     = 1 << 20
)

// Config is what a Client is given at startup.
type Config struct {
	// BaseURL is the API root; the client posts to BaseURL + "/v1/messages".
	BaseURL string
	// APIKey is the provider key, for the key mode (--live until the Broker runs
	// as its own process). Exactly one of APIKey and SVID is set.
	APIKey string
	// SVID is the Broker mode: it returns a fresh JWT-SVID for the Broker's
	// audience, called once per request (the repair retry included). BaseURL is
	// then the Broker's, the request names no model and carries no provider key.
	SVID func(ctx context.Context) (wire.JWTSVID, error)
	// CorrelationID is sent to the Broker in the Correlation-Id header.
	CorrelationID string
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

// New builds a Client. An empty BaseURL, or neither an APIKey nor an SVID
// function, is an error.
func New(cfg Config) (*Client, error) {
	switch {
	case cfg.BaseURL == "":
		return nil, errors.New("modelclient: a base URL is required")
	case cfg.APIKey == "" && cfg.SVID == nil:
		return nil, errors.New("modelclient: an API key or a JWT-SVID source is required")
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
	// Model and the token counts are set only in Broker mode, where Provider,
	// Model, Cost and RequestID are what the Broker reported.
	Model        string
	InputTokens  int
	OutputTokens int
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
	// Status is the HTTP status of a non-2xx Broker reply, else 0. Reason is the
	// Broker's reason code on a refusal, else empty; it is kept only if it looks
	// like a code, never as free text.
	Status int
	Reason string
	msg    string
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

// requestFields is every field of the Messages request but the model, which
// the Client or the Broker adds. The Pin's request-shape hash is computed from
// these same constants (DefaultPin), so a change here moves the hash with it.
func requestFields(messages []any) map[string]any {
	return map[string]any{
		"max_tokens":    maxTokens,
		"system":        system,
		"messages":      messages,
		"tools":         []any{toolDef},
		"tool_choice":   map[string]any{"type": "auto", "disable_parallel_tool_use": true},
		"output_config": map[string]any{"effort": "low"},
	}
}

// Request is the Messages request body the Client sends in Broker mode for a
// question's first call: no model, no key.
func Request(question string) ([]byte, error) {
	return json.Marshal(requestFields([]any{map[string]any{"role": "user", "content": question}}))
}

// DefaultPin is the Pin for a workload that asks through this Client: each
// provider's default model, the Client's max_tokens as the ceiling, and the
// request-shape hash of the Client's own request fields. It is computed from
// the request constants, never written down.
func DefaultPin() pin.Pin {
	raw, err := json.Marshal(requestFields(nil))
	if err != nil {
		panic(err) // the constants always encode
	}
	shape, err := pin.Shape(raw)
	if err != nil {
		panic(err)
	}
	models := map[string][]string{}
	for name, p := range provider.Providers {
		models[name] = []string{p.DefaultModel}
	}
	models[provider.StandIn.Name] = []string{provider.StandIn.DefaultModel}
	return pin.Pin{Models: models, MaxTokens: maxTokens, Shape: shape}
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

var reasonRe = regexp.MustCompile(`^[a-z0-9_]{1,40}$`)

// brokerFailure is the provider error for a non-2xx Broker reply, keeping its
// status and its reason code.
func brokerFailure(status int, raw []byte) *Failure {
	f := providerError(fmt.Sprintf("status %d", status))
	f.Status = status
	var body wire.BrokerError
	if json.Unmarshal(raw, &body) == nil && reasonRe.MatchString(body.Reason) {
		f.Reason = body.Reason
	}
	return f
}

func (c *Client) call(ctx context.Context, messages []any) (response, Attempt, error) {
	attempt := Attempt{Provider: c.cfg.Provider}
	fields := requestFields(messages)
	if c.cfg.SVID == nil {
		// The Broker sets the model; in key mode the client does.
		fields["model"] = c.cfg.Model
	}
	body, err := json.Marshal(fields)
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
	if c.cfg.SVID != nil {
		// A fresh token for every request, so none is sent twice or expires
		// between attempts. The error is dropped: it may name the socket.
		svid, err := c.cfg.SVID(ctx)
		if err != nil {
			return response{}, attempt, providerError("could not fetch a JWT-SVID")
		}
		req.Header.Set(wire.HeaderAuthorization, string(wire.BearerFor(svid)))
		if c.cfg.CorrelationID != "" {
			req.Header.Set(wire.HeaderCorrelationID, c.cfg.CorrelationID)
		}
	} else {
		c.prov.SetAuth(req.Header, c.cfg.APIKey)
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
		if c.cfg.SVID != nil && err == nil {
			return response{}, attempt, brokerFailure(hr.StatusCode, raw)
		}
		return response{}, attempt, providerError(fmt.Sprintf("status %d", hr.StatusCode))
	}
	var out response
	if err := json.Unmarshal(raw, &out); err != nil {
		return response{}, attempt, providerError("unreadable reply")
	}
	if attempt.RequestID == "" {
		attempt.RequestID = out.ID
	}
	if c.cfg.SVID != nil {
		// The Broker reports who served the request and what it cost.
		attempt.Provider = hr.Header.Get(wire.HeaderBrokerProvider)
		attempt.Model = hr.Header.Get(wire.HeaderBrokerModel)
		attempt.Cost, _ = strconv.ParseFloat(hr.Header.Get(wire.HeaderBrokerCost), 64)
		attempt.InputTokens, attempt.OutputTokens = int(out.Usage.InputTokens), int(out.Usage.OutputTokens)
		if id := hr.Header.Get(wire.HeaderBrokerRequestID); id != "" {
			attempt.RequestID = id
		}
		return out, attempt, nil
	}
	attempt.Cost = c.cost(out)
	return out, attempt, nil
}

func (c *Client) cost(r response) float64 {
	return c.prov.Cost(c.cfg.Model, r.Usage.InputTokens, r.Usage.OutputTokens, r.Usage.Cost)
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
