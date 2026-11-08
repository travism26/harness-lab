// Package warden is the Warden: it verifies the Agent's JWT-SVID, checks the
// Agent allowlist and answers Lookups with fixed rules, never a model.
package warden

import (
	"encoding/json"
	"errors"
	"log/slog"
	"net"
	"net/http"
	"strings"
	"time"

	"github.com/spiffe/go-spiffe/v2/bundle/jwtbundle"
	"github.com/spiffe/go-spiffe/v2/spiffeid"
	"github.com/spiffe/go-spiffe/v2/svid/jwtsvid"

	"github.com/travism26/harness-lab/projects/agent-identity/internal/wire"
)

// Outcome is how the Warden settled one request.
type Outcome string

const (
	// OutcomeAllowed is M1's placeholder for a request that passed the token
	// gate and the allowlist. The Lookup check and Answers replace it.
	OutcomeAllowed         Outcome = "allowed"
	OutcomeAgentNotAllowed Outcome = "agent_not_allowed"
	OutcomeUnauthenticated Outcome = "unauthenticated"
)

// FailedCheck names the check that refused a request.
type FailedCheck string

const (
	CheckJWTSVID   FailedCheck = "jwt_svid"
	CheckAllowlist FailedCheck = "allowlist"
)

// Decision is what the Warden decided for one request. Agent is set only once
// the JWT-SVID has verified. It never holds a token or a raw error.
type Decision struct {
	Status      int
	Outcome     Outcome
	FailedCheck FailedCheck
	Reason      Reason
	Agent       string
}

// Config is what the Warden is given at startup.
type Config struct {
	// Audience is the Warden's own SPIFFE ID, required in every JWT-SVID's aud.
	Audience string
	// Bundles verifies JWT-SVID signatures.
	Bundles jwtbundle.Source
	// Allowlist is the Agent allowlist: the SPIFFE IDs that may make Lookups.
	Allowlist []spiffeid.ID
	// OnDecision, if set, is called with each Decision before the response is
	// written.
	OnDecision func(Decision)
	// Logger takes operational noise, including raw verification errors at
	// debug level. Nil means slog.Default().
	Logger *slog.Logger
}

// MaxLifetime is the longest exp - iat the Warden accepts on a token,
// whatever the clock says.
const MaxLifetime = 5 * time.Minute

// Warden is the HTTP handler for POST /lookup.
type Warden struct {
	audience   string
	bundles    jwtbundle.Source
	allowlist  map[spiffeid.ID]bool
	onDecision func(Decision)
	log        *slog.Logger
	mux        *http.ServeMux
}

// New builds a Warden. An empty Audience is an error: go-spiffe skips the
// audience check when it is given none.
func New(cfg Config) (*Warden, error) {
	if cfg.Audience == "" {
		return nil, errors.New("warden: audience is required")
	}
	if cfg.Bundles == nil {
		return nil, errors.New("warden: a JWT bundle source is required")
	}
	w := &Warden{
		audience:   cfg.Audience,
		bundles:    cfg.Bundles,
		allowlist:  make(map[spiffeid.ID]bool, len(cfg.Allowlist)),
		onDecision: cfg.OnDecision,
		log:        cfg.Logger,
		mux:        http.NewServeMux(),
	}
	if w.log == nil {
		w.log = slog.Default()
	}
	for _, id := range cfg.Allowlist {
		w.allowlist[id] = true
	}
	w.mux.HandleFunc("POST "+wire.PathLookup, w.lookup)
	return w, nil
}

// ServeHTTP serves the Warden's routes.
func (w *Warden) ServeHTTP(rw http.ResponseWriter, r *http.Request) {
	w.mux.ServeHTTP(rw, r)
}

func (w *Warden) lookup(rw http.ResponseWriter, r *http.Request) {
	svid, reason := w.verifyJWTSVID(wire.Bearer(r.Header.Get(wire.HeaderAuthorization)))
	if svid == nil {
		w.respond(rw, Decision{
			Status:      http.StatusUnauthorized,
			Outcome:     OutcomeUnauthenticated,
			FailedCheck: CheckJWTSVID,
			Reason:      reason,
		}, wire.ErrorBody{Error: wire.ErrUnauthenticated})
		return
	}
	agent := svid.ID.String()
	if !w.allowlist[svid.ID] {
		w.respond(rw, Decision{
			Status:      http.StatusForbidden,
			Outcome:     OutcomeAgentNotAllowed,
			FailedCheck: CheckAllowlist,
			Agent:       agent,
		}, wire.ErrorBody{Error: wire.ErrAgentNotAllowed})
		return
	}
	w.respond(rw, Decision{Status: http.StatusOK, Outcome: OutcomeAllowed, Agent: agent}, struct{}{})
}

// verifyJWTSVID checks the Authorization header's JWT-SVID: signature against
// the bundle, audience, expiry, then the maximum lifetime. On failure it
// returns a nil SVID and the reason code.
func (w *Warden) verifyJWTSVID(authorization wire.Bearer) (*jwtsvid.SVID, Reason) {
	token, ok := strings.CutPrefix(string(authorization), wire.BearerPrefix)
	switch {
	case authorization == "" || (ok && strings.TrimSpace(token) == ""):
		return nil, ReasonJWTSVIDMissing
	case !ok:
		return nil, ReasonJWTSVIDMalformed
	}
	svid, err := jwtsvid.ParseAndValidate(token, w.bundles, []string{w.audience})
	if err != nil {
		w.log.Debug("jwt-svid rejected", "err", err)
		return nil, JWTSVIDReason(err)
	}
	if !withinLifetime(svid) {
		return nil, ReasonJWTSVIDLifetime
	}
	return svid, ""
}

// withinLifetime reports whether the SVID has an iat and exp - iat is at most
// MaxLifetime. A token without iat can't show its lifetime, so it fails.
func withinLifetime(svid *jwtsvid.SVID) bool {
	iat, ok := svid.Claims["iat"].(float64)
	if !ok {
		return false
	}
	issued := time.Unix(int64(iat), 0)
	return svid.Expiry.Sub(issued) <= MaxLifetime
}

func (w *Warden) respond(rw http.ResponseWriter, d Decision, body any) {
	if w.onDecision != nil {
		w.onDecision(d)
	}
	rw.Header().Set("Content-Type", "application/json")
	rw.WriteHeader(d.Status)
	if err := json.NewEncoder(rw).Encode(body); err != nil {
		w.log.Debug("write response", "err", err)
	}
}

// Server is the Warden served over real HTTP on a loopback port.
type Server struct {
	// URL is the base URL, such as http://127.0.0.1:54321.
	URL string
	srv *http.Server
}

// ListenLoopback serves the Warden on 127.0.0.1 at a free port.
func (w *Warden) ListenLoopback() (*Server, error) {
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		return nil, err
	}
	srv := &http.Server{Handler: w, ReadHeaderTimeout: 5 * time.Second}
	go func() { _ = srv.Serve(ln) }()
	return &Server{URL: "http://" + ln.Addr().String(), srv: srv}, nil
}

// Close stops the server at once.
func (s *Server) Close() error {
	return s.srv.Close()
}
