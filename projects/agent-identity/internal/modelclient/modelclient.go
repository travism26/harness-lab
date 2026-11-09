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

	"github.com/travism26/harness-lab/projects/agent-identity/internal/modelrequest"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/wire"
)

const (
	callTimeout = 20 * time.Second
	maxBody     = 1 << 20
)

// Config is what a Client is given at startup.
type Config struct {
	// BaseURL is the API root; the client posts to BaseURL + "/v1/messages".
	BaseURL string
	// SVID returns a fresh JWT-SVID for the Broker's audience, called once per
	// request (the repair retry included). It is required: the Broker is the
	// only way to a Model, so the client holds no provider key and sends no
	// provider auth header. BaseURL is the Broker's.
	SVID func(ctx context.Context) (wire.JWTSVID, error)
	// CorrelationID is sent to the Broker in the Correlation-Id header.
	CorrelationID string
	// Model names the model the request asks for. Empty means the request names
	// none and the Broker fills it in (the Agent); the Eval names one from its
	// sweep.
	Model string
	// HTTPClient makes the request. Nil means http.DefaultClient; every call
	// also gets a 20s context deadline.
	HTTPClient *http.Client
}

// Client calls the Model through the Broker.
type Client struct {
	cfg Config
}

// New builds a Client. An empty BaseURL, or no SVID function, is an error.
func New(cfg Config) (*Client, error) {
	switch {
	case cfg.BaseURL == "":
		return nil, errors.New("modelclient: a base URL is required")
	case cfg.SVID == nil:
		return nil, errors.New("modelclient: a JWT-SVID source is required")
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
	// Provider, Model, the token counts, Cost and RequestID are what the Broker
	// reported.
	Model        string
	InputTokens  int
	OutputTokens int
	// Cost is in USD, as the Broker reported it.
	Cost float64
	// Reported is true only when the Broker sent a usable reply, so the fields
	// above are what it told us; false when it was unreachable or refused.
	Reported bool
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
		InputTokens  float64 `json:"input_tokens"`
		OutputTokens float64 `json:"output_tokens"`
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
	attempt := Attempt{}
	fields := modelrequest.Fields(messages)
	if c.cfg.Model != "" {
		// The Broker sets the model unless the caller named one (the Eval does,
		// to pick from its sweep).
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
		if err == nil {
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
	// The Broker reports who served the request and what it cost.
	attempt.Reported = true
	attempt.Provider = hr.Header.Get(wire.HeaderBrokerProvider)
	attempt.Model = hr.Header.Get(wire.HeaderBrokerModel)
	attempt.Cost, _ = strconv.ParseFloat(hr.Header.Get(wire.HeaderBrokerCost), 64)
	attempt.InputTokens, attempt.OutputTokens = int(out.Usage.InputTokens), int(out.Usage.OutputTokens)
	if id := hr.Header.Get(wire.HeaderBrokerRequestID); id != "" {
		attempt.RequestID = id
	}
	return out, attempt, nil
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
		return Proposal{}, &Failure{Kind: Retryable, Code: CodeToolUseCount, msg: fmt.Sprintf("call %s exactly once, not %d times", modelrequest.ToolName, len(uses))}
	}
	if uses[0].Name != modelrequest.ToolName {
		return Proposal{}, &Failure{Kind: Retryable, Code: CodeToolName, msg: "the only tool is " + modelrequest.ToolName}
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
