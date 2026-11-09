// Package broker is the Broker: the one workload that holds a Model provider
// key. It verifies the caller's JWT-SVID (the Warden's check, audience and
// leeway included), checks the caller's SPIFFE ID against the Broker allowlist,
// holds it to its Pin (model, max_tokens and request shape), adds the provider's
// auth headers and forwards the Messages request, returning
// the provider's body unchanged plus who served it and what it cost. It never
// reads the Caller assertion, and imports neither the Agent nor the Warden
// (trustlint R2). See projects/agent-identity/docs/adr/0004-the-provider-key-lives-only-in-the-broker.md.
package broker

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net"
	"net/http"
	"slices"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/spiffe/go-spiffe/v2/bundle/jwtbundle"
	"github.com/spiffe/go-spiffe/v2/spiffeid"

	"github.com/travism26/harness-lab/projects/agent-identity/internal/pin"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/provider"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/svidverify"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/wire"
)

// ID is the Broker's own SPIFFE ID, the audience every JWT-SVID sent to it carries.
var ID = spiffeid.RequireFromString("spiffe://example.com/model-broker")

// DefaultAllowlist is the Broker allowlist: the SPIFFE IDs that may ask for a
// Model reply. It is defined here once, for the Broker command and the tour.
var DefaultAllowlist = []spiffeid.ID{
	spiffeid.RequireFromString("spiffe://example.com/permission-agent"),
	spiffeid.RequireFromString("spiffe://example.com/model-eval"),
}

// Outcome is how the Broker settled one request.
type Outcome string

const (
	OutcomeAllowed       Outcome = "allowed"
	OutcomeRefused       Outcome = "refused"
	OutcomeUpstreamError Outcome = "upstream_error"
)

// Config is what the Broker is given at startup.
type Config struct {
	// Audience is the Broker's own SPIFFE ID, required in every JWT-SVID's aud.
	Audience string
	// Bundles verifies JWT-SVID signatures.
	Bundles jwtbundle.Source
	// Allowlist is the Broker allowlist. Nil means DefaultAllowlist.
	Allowlist []spiffeid.ID
	// Provider is the one provider the Broker chose at startup. Key is its key,
	// required unless the provider is the stand-in.
	Provider provider.Provider
	Key      string
	// UpstreamURL is the provider's API root; the Broker posts to it +
	// "/v1/messages". Empty means Provider.BaseURL.
	UpstreamURL string
	// Pins holds each allowlisted workload to what it may send. A workload with
	// no Pin may send nothing.
	Pins map[spiffeid.ID]pin.Pin
	// HTTPClient calls the provider. Nil means a client with no redirects.
	HTTPClient *http.Client
	// Now stamps the Audit record. Nil means time.Now.
	Now func() time.Time
	// Audit, if set, takes one JSON-lines Audit record per Model request.
	Audit io.Writer
	// Logger takes operational noise, including raw verification errors at
	// debug level. Nil means slog.Default().
	Logger *slog.Logger
}

// Broker is the HTTP handler for POST /v1/messages.
type Broker struct {
	audience  string
	bundles   jwtbundle.Source
	allowlist map[spiffeid.ID]bool
	prov      provider.Provider
	key       string
	upstream  string
	pins      map[spiffeid.ID]pin.Pin
	client    *http.Client
	now       func() time.Time
	audit     io.Writer
	auditMu   sync.Mutex
	log       *slog.Logger
	mux       *http.ServeMux
}

// New builds a Broker. An empty Audience is an error, as is a missing bundle
// source or, for a keyed provider, a missing key: a Broker that cannot call its
// provider must not start.
func New(cfg Config) (*Broker, error) {
	switch {
	case cfg.Audience == "":
		return nil, errors.New("broker: audience is required")
	case cfg.Bundles == nil:
		return nil, errors.New("broker: a JWT bundle source is required")
	case cfg.Key == "" && cfg.Provider.Name != provider.StandIn.Name:
		return nil, fmt.Errorf("broker: provider %q needs a key", cfg.Provider.Name)
	}
	b := &Broker{
		audience:  cfg.Audience,
		bundles:   cfg.Bundles,
		allowlist: map[spiffeid.ID]bool{},
		prov:      cfg.Provider,
		key:       cfg.Key,
		upstream:  strings.TrimSuffix(cfg.UpstreamURL, "/"),
		pins:      cfg.Pins,
		client:    cfg.HTTPClient,
		now:       cfg.Now,
		audit:     cfg.Audit,
		log:       cfg.Logger,
		mux:       http.NewServeMux(),
	}
	if b.upstream == "" {
		b.upstream = strings.TrimSuffix(cfg.Provider.BaseURL, "/")
	}
	if b.client == nil {
		// A redirect would carry the provider key to wherever it points.
		b.client = &http.Client{CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	}
	if b.now == nil {
		b.now = time.Now
	}
	if b.log == nil {
		b.log = slog.Default()
	}
	allow := cfg.Allowlist
	if allow == nil {
		allow = DefaultAllowlist
	}
	for _, id := range allow {
		b.allowlist[id] = true
	}
	b.mux.HandleFunc("POST "+wire.PathMessages, b.messages)
	return b, nil
}

// ServeHTTP serves the Broker's routes.
func (b *Broker) ServeHTTP(rw http.ResponseWriter, r *http.Request) {
	b.mux.ServeHTTP(rw, r)
}

const (
	// maxRequestBytes caps the Messages request the Broker will read.
	maxRequestBytes = 1 << 20
	// maxReplyBytes caps the provider reply the Broker will read.
	maxReplyBytes = 1 << 20
	// upstreamTimeout is the deadline on the provider call.
	upstreamTimeout = 30 * time.Second
)

// settled is what the Broker decided, as it goes into the Audit record.
type settled struct {
	status         int
	outcome        Outcome
	reason         string
	upstreamStatus int
	model          string
	requestID      string
	usage          usage
	cost           float64
}

func (b *Broker) messages(rw http.ResponseWriter, r *http.Request) {
	corr, rejected := correlationID(r.Header.Get(wire.HeaderCorrelationID))
	rw.Header().Set(wire.HeaderCorrelationID, corr)
	rec := AuditRecord{CorrelationID: corr, Provider: b.prov.Name, RejectedCorrelationIDLen: rejected}
	refuse := func(status int, reason string) {
		b.respond(rw, rec, settled{status: status, outcome: OutcomeRefused, reason: reason}, wire.BrokerError{Reason: reason})
	}

	svid, reason, err := svidverify.Verify(wire.Bearer(r.Header.Get(wire.HeaderAuthorization)), b.bundles, b.audience)
	if svid == nil {
		if err != nil {
			b.log.Debug("jwt-svid rejected", "err", err)
		}
		refuse(http.StatusUnauthorized, string(reason))
		return
	}
	rec.SPIFFEID = svid.ID.String()
	if !b.allowlist[svid.ID] {
		refuse(http.StatusForbidden, wire.ReasonNotAllowlisted)
		return
	}
	body, err := b.requestBody(http.MaxBytesReader(rw, r.Body, maxRequestBytes), b.pins[svid.ID])
	if errors.Is(err, errOutsidePin) {
		b.log.Debug("request outside the pin", "err", err)
		refuse(http.StatusForbidden, wire.ReasonOutsidePin)
		return
	}
	if err != nil {
		b.log.Debug("request body rejected", "err", err)
		refuse(http.StatusBadRequest, wire.ReasonBadRequest)
		return
	}
	b.forward(r.Context(), rw, rec, body.bytes, body.model)
}

// request is a Messages request after the Broker has set its model and
// max_tokens.
type request struct {
	bytes []byte
	model string
}

// errOutsidePin marks a request the workload's Pin does not allow.
var errOutsidePin = errors.New("outside the pin")

// requestBody reads the Messages request and holds it to p: the model is filled
// in when absent and the Pin lists exactly one for this provider, else it must
// be listed; max_tokens is filled in with the ceiling when absent and may not
// exceed it; and every field but messages, model and max_tokens must hash to
// the Pin's request shape. Messages is passed on as received.
func (b *Broker) requestBody(r io.Reader, p pin.Pin) (request, error) {
	raw, err := io.ReadAll(r)
	if err != nil {
		return request{}, err
	}
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(raw, &fields); err != nil || fields == nil {
		return request{}, errors.New("not a JSON object")
	}
	models := p.Models[b.prov.Name]
	var model string
	if named, ok := fields["model"]; ok {
		if err := json.Unmarshal(named, &model); err != nil || model == "" {
			return request{}, errors.New("model is not a string")
		}
	} else if len(models) == 1 {
		model = models[0]
		fields["model"], _ = json.Marshal(model)
	} else {
		return request{}, fmt.Errorf("%w: no model named and %d listed", errOutsidePin, len(models))
	}
	if !slices.Contains(models, model) {
		return request{}, fmt.Errorf("%w: model not listed", errOutsidePin)
	}
	if p.MaxTokens <= 0 || p.Shape == "" {
		return request{}, fmt.Errorf("%w: the pin has no ceiling or no request shape", errOutsidePin)
	}
	if given, ok := fields["max_tokens"]; ok {
		var n float64
		if err := json.Unmarshal(given, &n); err != nil {
			return request{}, errors.New("max_tokens is not a number")
		}
		if n > float64(p.MaxTokens) {
			return request{}, fmt.Errorf("%w: max_tokens above the ceiling", errOutsidePin)
		}
	} else {
		fields["max_tokens"], _ = json.Marshal(p.MaxTokens)
	}
	shape, err := pin.ShapeOf(fields)
	if err != nil {
		return request{}, err
	}
	if shape != p.Shape {
		return request{}, fmt.Errorf("%w: request shape differs", errOutsidePin)
	}
	out, err := json.Marshal(fields)
	return request{bytes: out, model: model}, err
}

func (b *Broker) forward(ctx context.Context, rw http.ResponseWriter, rec AuditRecord, body []byte, model string) {
	rec.Model = model
	fail := func(upstreamStatus int) {
		b.respond(rw, rec, settled{status: http.StatusBadGateway, outcome: OutcomeUpstreamError, reason: wire.ReasonUpstreamError, upstreamStatus: upstreamStatus},
			wire.BrokerError{Reason: wire.ReasonUpstreamError, UpstreamStatus: upstreamStatus})
	}
	ctx, cancel := context.WithTimeout(ctx, upstreamTimeout)
	defer cancel()
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, b.upstream+wire.PathMessages, bytes.NewReader(body))
	if err != nil {
		fail(0)
		return
	}
	req.Header.Set("Content-Type", "application/json")
	if b.key != "" {
		b.prov.SetAuth(req.Header, b.key)
	}
	resp, err := b.client.Do(req)
	if err != nil {
		// The raw error may carry the URL; keep only that the call failed.
		b.log.Debug("upstream call failed", "err", err)
		fail(0)
		return
	}
	defer resp.Body.Close()
	reply, err := io.ReadAll(io.LimitReader(resp.Body, maxReplyBytes))
	if err != nil || resp.StatusCode < 200 || resp.StatusCode > 299 {
		fail(resp.StatusCode)
		return
	}
	var parsed struct {
		ID    string `json:"id"`
		Usage struct {
			InputTokens  float64  `json:"input_tokens"`
			OutputTokens float64  `json:"output_tokens"`
			Cost         *float64 `json:"cost"`
		} `json:"usage"`
	}
	// A reply that doesn't parse is still passed on; the Agent's gate refuses it.
	_ = json.Unmarshal(reply, &parsed)
	requestID := resp.Header.Get("Request-Id")
	if requestID == "" {
		requestID = parsed.ID
	}
	cost := b.prov.Cost(model, parsed.Usage.InputTokens, parsed.Usage.OutputTokens, parsed.Usage.Cost)
	s := settled{
		status: resp.StatusCode, outcome: OutcomeAllowed, model: model, requestID: requestID, cost: cost,
		usage: usage{in: int(parsed.Usage.InputTokens), out: int(parsed.Usage.OutputTokens)},
	}
	h := rw.Header()
	h.Set("Content-Type", "application/json")
	h.Set(wire.HeaderBrokerProvider, b.prov.Name)
	h.Set(wire.HeaderBrokerModel, model)
	h.Set(wire.HeaderBrokerCost, strconv.FormatFloat(cost, 'f', -1, 64))
	h.Set(wire.HeaderBrokerRequestID, requestID)
	b.respondRaw(rw, rec, s, reply)
}

// respond writes a JSON error body and the Audit record.
func (b *Broker) respond(rw http.ResponseWriter, rec AuditRecord, s settled, body wire.BrokerError) {
	rw.Header().Set("Content-Type", "application/json")
	raw, _ := json.Marshal(body)
	b.respondRaw(rw, rec, s, append(raw, '\n'))
}

// respondRaw writes the Audit record, then the status and body.
func (b *Broker) respondRaw(rw http.ResponseWriter, rec AuditRecord, s settled, body []byte) {
	b.writeAudit(rec, s)
	rw.WriteHeader(s.status)
	if _, err := rw.Write(body); err != nil {
		b.log.Debug("write response", "err", err)
	}
}

// Server is the Broker served over real HTTP on a loopback port.
type Server struct {
	// URL is the base URL, such as http://127.0.0.1:54321.
	URL string
	srv *http.Server
}

// ListenLoopback serves the Broker on 127.0.0.1 at a free port.
func (b *Broker) ListenLoopback() (*Server, error) {
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		return nil, err
	}
	srv := &http.Server{Handler: b, ReadHeaderTimeout: 5 * time.Second}
	go func() { _ = srv.Serve(ln) }()
	return &Server{URL: "http://" + ln.Addr().String(), srv: srv}, nil
}

// Close stops the server at once.
func (s *Server) Close() error {
	return s.srv.Close()
}
