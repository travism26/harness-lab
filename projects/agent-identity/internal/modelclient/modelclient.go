// Package modelclient turns a question into a Proposal {target, permission} or
// a typed Failure, through a Messages endpoint (Anthropic's API or
// OpenRouter's) with a strict lookup_permission tool. It knows nothing about the
// Caller. Only internal/agent and internal/eval may import it (trustlint R1).
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
)

// AuthStyle is how the API key is sent.
type AuthStyle int

const (
	// AuthAnthropic sends x-api-key and anthropic-version.
	AuthAnthropic AuthStyle = iota
	// AuthBearer sends Authorization: Bearer (OpenRouter).
	AuthBearer
)

const (
	anthropicVersion = "2026-10-21"
	toolName         = "lookup_permission"
	maxTokens        = 1024
	callTimeout      = 20 * time.Second
	maxBody          = 1 << 20

	// DefaultModel is the default Anthropic model id.
	DefaultModel = "claude-haiku-5-5"
	// DefaultOpenRouterModel is the default model id on OpenRouter.
	DefaultOpenRouterModel = "anthropic/claude-haiku-5.5"
)

// Config is what a Client is given at startup.
type Config struct {
	// BaseURL is the API root; the client posts to BaseURL + "/v1/messages".
	BaseURL string
	APIKey  string
	// Model defaults by Provider: DefaultOpenRouterModel for "openrouter",
	// DefaultModel otherwise.
	Model string
	// Provider labels each Attempt: "anthropic", "openrouter" or "stand-in".
	Provider string
	Auth     AuthStyle
	// HTTPClient makes the request. Nil means http.DefaultClient; every call
	// also gets a 20s context deadline.
	HTTPClient *http.Client
}

// Client calls the Model.
type Client struct{ cfg Config }

// New builds a Client. An empty BaseURL or APIKey is an error.
func New(cfg Config) (*Client, error) {
	switch {
	case cfg.BaseURL == "":
		return nil, errors.New("modelclient: a base URL is required")
	case cfg.APIKey == "":
		return nil, errors.New("modelclient: an API key is required")
	}
	if cfg.Model == "" {
		cfg.Model = DefaultModel
		if cfg.Provider == "openrouter" {
			cfg.Model = DefaultOpenRouterModel
		}
	}
	if cfg.HTTPClient == nil {
		cfg.HTTPClient = http.DefaultClient
	}
	cfg.BaseURL = strings.TrimSuffix(cfg.BaseURL, "/")
	return &Client{cfg: cfg}, nil
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

// Failure is the typed failure Propose returns as its error.
type Failure struct {
	Kind Kind
	// Code is a short closed-set name: stop_reason, refusal, text_only,
	// provider_error, tool_use_count, tool_name, decode or format.
	Code string
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
	"letters, such as invoice:approve. Call the tool exactly once. If the question cannot be " +
	"turned into one lookup, do not call it."

var toolDef = map[string]any{
	"name":        toolName,
	"description": "Look up whether one target holds one permission.",
	"strict":      true,
	"input_schema": map[string]any{
		"type": "object",
		"properties": map[string]any{
			"target":     map[string]any{"type": "string", "description": "a name from the question, or self"},
			"permission": map[string]any{"type": "string", "description": "resource:action, lowercase"},
		},
		"required":             []string{"target", "permission"},
		"additionalProperties": false,
	},
}

type block struct {
	Type  string          `json:"type"`
	ID    string          `json:"id,omitempty"`
	Name  string          `json:"name,omitempty"`
	Text  string          `json:"text,omitempty"`
	Input json.RawMessage `json:"input,omitempty"`
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
		messages = append(messages, map[string]any{"role": "assistant", "content": resp.Content})
		var results []any
		for _, b := range resp.Content {
			if b.Type == "tool_use" {
				results = append(results, map[string]any{
					"type": "tool_result", "tool_use_id": b.ID, "is_error": true, "content": ferr.msg,
				})
			}
		}
		messages = append(messages, map[string]any{"role": "user", "content": results})
	}
}

func providerError(msg string) *Failure {
	return &Failure{Kind: Fatal, Code: "provider_error", msg: msg}
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
	switch c.cfg.Auth {
	case AuthBearer:
		req.Header.Set("Authorization", "Bearer "+c.cfg.APIKey)
	default:
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

// pricesPerMillion is USD per million input and output tokens (ADR 0003).
var pricesPerMillion = map[string][2]float64{
	"claude-haiku-5-5":  {0.10, 0.50},
	"claude-sonnet-5-5": {2, 10},
	"claude-opus-5-5":   {4, 20},
}

func (c *Client) cost(r response) float64 {
	if r.Usage.Cost != nil {
		return *r.Usage.Cost
	}
	if c.cfg.Provider != "anthropic" {
		return 0
	}
	p := pricesPerMillion[c.cfg.Model]
	return (r.Usage.InputTokens*p[0] + r.Usage.OutputTokens*p[1]) / 1e6
}

// gate applies the five rules in order.
func gate(r response) (Proposal, *Failure) {
	if r.StopReason == "refusal" {
		return Proposal{}, &Failure{Kind: Fatal, Code: "refusal", msg: "the Model refused"}
	}
	if r.StopReason != "tool_use" {
		var text []string
		for _, b := range r.Content {
			if b.Type == "text" {
				text = append(text, b.Text)
			}
		}
		if r.StopReason == "end_turn" && len(text) > 0 {
			return Proposal{}, &Failure{Kind: Fatal, Code: "text_only", Text: strings.Join(text, "\n"), msg: "text-only reply"}
		}
		return Proposal{}, &Failure{Kind: Fatal, Code: "stop_reason", msg: "stop_reason " + r.StopReason}
	}
	var uses []block
	for _, b := range r.Content {
		if b.Type == "tool_use" {
			uses = append(uses, b)
		}
	}
	if len(uses) != 1 {
		return Proposal{}, &Failure{Kind: Retryable, Code: "tool_use_count", msg: fmt.Sprintf("call %s exactly once, not %d times", toolName, len(uses))}
	}
	if uses[0].Name != toolName {
		return Proposal{}, &Failure{Kind: Retryable, Code: "tool_name", msg: "the only tool is " + toolName}
	}
	var p Proposal
	dec := json.NewDecoder(bytes.NewReader(uses[0].Input))
	dec.DisallowUnknownFields()
	if err := dec.Decode(&p); err != nil || p.Target == "" || p.Permission == "" {
		return Proposal{}, &Failure{Kind: Retryable, Code: "decode", msg: "input must be exactly {target, permission}, both non-empty strings"}
	}
	if p.Target != "self" && !targetRe.MatchString(p.Target) {
		return Proposal{}, &Failure{Kind: Retryable, Code: "format", msg: "target must be self or match ^[a-z][a-z0-9-]*$"}
	}
	if !permissionRe.MatchString(p.Permission) {
		return Proposal{}, &Failure{Kind: Retryable, Code: "format", msg: "permission must match ^[a-z]+:[a-z]+$"}
	}
	return p, nil
}
