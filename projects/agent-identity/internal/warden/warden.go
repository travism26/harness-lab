// Package warden is the Warden: it verifies the Agent's JWT-SVID, checks the
// Agent allowlist and the Caller assertion, applies the Lookup check against
// the Seed data and answers whether the Target holds the Permission, with fixed
// rules and never a model.
package warden

import (
	"crypto/ecdsa"
	"encoding/json"
	"errors"
	"log/slog"
	"net"
	"net/http"
	"strings"
	"time"

	"github.com/go-jose/go-jose/v4"
	"github.com/go-jose/go-jose/v4/jwt"
	"github.com/spiffe/go-spiffe/v2/bundle/jwtbundle"
	"github.com/spiffe/go-spiffe/v2/spiffeid"
	"github.com/spiffe/go-spiffe/v2/svid/jwtsvid"

	"github.com/travism26/harness-lab/projects/agent-identity/internal/wire"
)

// Outcome is how the Warden settled one request.
type Outcome string

const (
	OutcomeAgentNotAllowed Outcome = "agent_not_allowed"
	OutcomeUnauthenticated Outcome = "unauthenticated"
	// OutcomeAnswerYes and OutcomeAnswerNo are the 200 Answers.
	OutcomeAnswerYes Outcome = "answer_yes"
	OutcomeAnswerNo  Outcome = "answer_no"
	// OutcomeDenial is a refused Lookup or a missing Target, one 403 body for both.
	OutcomeDenial Outcome = "denial"
	// OutcomeUnknownPermission is a 422 for a Permission outside the catalog,
	// reached only once the Lookup check and the Target check have passed.
	OutcomeUnknownPermission Outcome = "unknown_permission"
)

// FailedCheck names the check that refused a request.
type FailedCheck string

const (
	CheckJWTSVID   FailedCheck = "jwt_svid"
	CheckAllowlist FailedCheck = "allowlist"

	CheckCallerAssertion FailedCheck = "caller_assertion"
	CheckLookup          FailedCheck = "lookup_check"
	CheckTargetMissing   FailedCheck = "target_missing"
)

// Decision is what the Warden decided for one request. Agent is set only once
// the JWT-SVID has verified, and Caller only once the Caller assertion has too.
// Target and Permission are set once the Lookup body has decoded, and Role only
// on answer_yes. It never holds a token or a raw error.
type Decision struct {
	Status      int
	Outcome     Outcome
	FailedCheck FailedCheck
	Reason      Reason
	Agent       string
	Caller      string
	Target      string
	Permission  string
	Role        string
}

// Config is what the Warden is given at startup.
type Config struct {
	// Audience is the Warden's own SPIFFE ID, required in every JWT-SVID's aud.
	Audience string
	// Bundles verifies JWT-SVID signatures.
	Bundles jwtbundle.Source
	// Allowlist is the Agent allowlist: the SPIFFE IDs that may make Lookups.
	Allowlist []spiffeid.ID
	// LoginKey is the one Login public key that verifies Caller assertions.
	LoginKey *ecdsa.PublicKey
	// Now is the clock for the Caller assertion only. Nil means time.Now.
	Now func() time.Time
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
	loginKey   *ecdsa.PublicKey
	now        func() time.Time
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
	if cfg.LoginKey == nil {
		return nil, errors.New("warden: a Login public key is required")
	}
	w := &Warden{
		audience:   cfg.Audience,
		bundles:    cfg.Bundles,
		allowlist:  make(map[spiffeid.ID]bool, len(cfg.Allowlist)),
		loginKey:   cfg.LoginKey,
		now:        cfg.Now,
		onDecision: cfg.OnDecision,
		log:        cfg.Logger,
		mux:        http.NewServeMux(),
	}
	if w.now == nil {
		w.now = time.Now
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
	caller, reason := w.verifyCallerAssertion(wire.CallerAssertion(r.Header.Get(wire.HeaderCallerAssertion)), agent)
	if caller == "" {
		w.respond(rw, Decision{
			Status:      http.StatusUnauthorized,
			Outcome:     OutcomeUnauthenticated,
			FailedCheck: CheckCallerAssertion,
			Reason:      reason,
			Agent:       agent,
		}, wire.ErrorBody{Error: wire.ErrUnauthenticated})
		return
	}
	w.answer(rw, r, agent, caller)
}

// maxBodyBytes caps the Lookup body.
const maxBodyBytes = 4 << 10

// answer runs the Lookup check and answers. The Caller's Tenant comes from the
// Seed data, never from the request, and the check never reads the Target's
// Seed entry, so a refusal looks the same whether or not the Target exists.
func (w *Warden) answer(rw http.ResponseWriter, r *http.Request, agent, caller string) {
	d := Decision{Agent: agent, Caller: caller}
	denied := func(check FailedCheck) {
		d.Status, d.Outcome, d.FailedCheck = http.StatusForbidden, OutcomeDenial, check
		w.respond(rw, d, wire.ErrorBody{Error: wire.ErrDenied})
	}
	var req wire.LookupRequest
	dec := json.NewDecoder(http.MaxBytesReader(rw, r.Body, maxBodyBytes))
	dec.DisallowUnknownFields()
	// A body that won't decode, or names anything beyond target and permission
	// (a Caller, a Tenant), names no Target the Caller may ask about, so it is a
	// lookup_check Denial; the failed_check set stays the spec's closed one.
	if err := dec.Decode(&req); err != nil {
		w.log.Debug("lookup body rejected", "err", err)
		denied(CheckLookup)
		return
	}
	d.Target, d.Permission = req.Target, req.Permission
	if req.Target != caller && !w.mayLookUp(caller, req.Target) {
		denied(CheckLookup)
		return
	}
	target, ok := seedUsers[req.Target]
	if !ok {
		denied(CheckTargetMissing)
		return
	}
	if !knownPermission(req.Permission) {
		d.Status, d.Outcome = http.StatusUnprocessableEntity, OutcomeUnknownPermission
		w.respond(rw, d, wire.ErrorBody{Error: wire.ErrUnknownPermission})
		return
	}
	d.Status = http.StatusOK
	if !roleHolds(target.Role, req.Permission) {
		d.Outcome = OutcomeAnswerNo
		w.respond(rw, d, wire.Answer{})
		return
	}
	d.Outcome, d.Role = OutcomeAnswerYes, target.Role
	w.respond(rw, d, wire.Answer{Holds: true, Role: target.Role})
}

// mayLookUp is the Lookup check for a Target other than the Caller: the Target
// is in the Caller's Tenant and the Caller's Role holds permission:read.
func (w *Warden) mayLookUp(caller, target string) bool {
	tenant, _, hasTenant := strings.Cut(target, "/")
	c := seedUsers[caller]
	return hasTenant && tenant == c.Tenant && roleHolds(c.Role, permissionRead)
}

// verifyCallerAssertion checks the Caller-Assertion header: ES256 signature
// against the Login key, the maximum lifetime (whatever the clock says),
// audience and expiry, that
// may_act names the Agent, and that the Caller is a known User. On failure it
// returns an empty Caller and the reason code.
func (w *Warden) verifyCallerAssertion(raw wire.CallerAssertion, agent string) (string, Reason) {
	if strings.TrimSpace(string(raw)) == "" {
		return "", ReasonAssertionMissing
	}
	tok, err := jwt.ParseSigned(string(raw), []jose.SignatureAlgorithm{jose.ES256})
	if err != nil {
		w.log.Debug("caller assertion rejected", "err", err)
		return "", ReasonAssertionMalformed
	}
	var std jwt.Claims
	var extra struct {
		MayAct *struct {
			Sub string `json:"sub"`
		} `json:"may_act"`
	}
	if err := tok.Claims(w.loginKey, &std, &extra); err != nil {
		w.log.Debug("caller assertion rejected", "err", err)
		return "", ReasonAssertionSignature
	}
	if std.IssuedAt == nil || std.Expiry == nil || std.Expiry.Time().Sub(std.IssuedAt.Time()) > MaxLifetime {
		return "", ReasonAssertionLifetime
	}
	expected := jwt.Expected{AnyAudience: jwt.Audience{w.audience}, Time: w.now()}
	if err := std.ValidateWithLeeway(expected, jwt.DefaultLeeway); err != nil {
		w.log.Debug("caller assertion rejected", "err", err)
		return "", AssertionReason(err)
	}
	if extra.MayAct == nil || extra.MayAct.Sub != agent {
		return "", ReasonAssertionMayActMismatch
	}
	if _, ok := seedUsers[std.Subject]; !ok {
		return "", ReasonAssertionUnknownCaller
	}
	return std.Subject, ""
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
