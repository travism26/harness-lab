package warden_test

import (
	"bytes"
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"io"
	"net/http"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/go-jose/go-jose/v4"
	"github.com/go-jose/go-jose/v4/jwt"
	"github.com/spiffe/go-spiffe/v2/spiffeid"
	"github.com/spiffe/go-spiffe/v2/svid/jwtsvid"

	"github.com/travism26/harness-lab/projects/agent-identity/internal/login"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/standin/workload"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/warden"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/wire"
)

const wardenAudience = "spiffe://example.com/warden"

var (
	trustDomain = spiffeid.RequireTrustDomainFromString("example.com")
	agentID     = spiffeid.RequireFromString("spiffe://example.com/permission-agent")
	unlistedID  = spiffeid.RequireFromString("spiffe://example.com/unlisted-agent")
)

// fixture is a real Warden on loopback HTTP, trusting the stand-in's bundle,
// with the Decisions it made.
type fixture struct {
	source   *workload.Source
	url      string
	loginKey *ecdsa.PrivateKey

	audit syncBuffer
	// header is sent on every request, such as a Correlation-Id.
	header http.Header

	mu        sync.Mutex
	decisions []warden.Decision
	clock     time.Time
}

// now is the Warden's clock for the Caller assertion. It starts at the real time
// and tests move it with setNow.
func (f *fixture) now() time.Time {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.clock
}

func (f *fixture) setNow(t time.Time) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.clock = t
}

func newFixture(t *testing.T) *fixture {
	t.Helper()
	source, err := workload.New(trustDomain)
	if err != nil {
		t.Fatal(err)
	}
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	f := &fixture{source: source, loginKey: key, clock: time.Now().Truncate(time.Second), header: http.Header{}}
	w, err := warden.New(warden.Config{
		Audience:  wardenAudience,
		Bundles:   source,
		Allowlist: []spiffeid.ID{agentID},
		LoginKey:  &key.PublicKey,
		Now:       f.now,
		Audit:     &f.audit,
		OnDecision: func(d warden.Decision) {
			f.mu.Lock()
			defer f.mu.Unlock()
			f.decisions = append(f.decisions, d)
		},
	})
	if err != nil {
		t.Fatal(err)
	}
	srv, err := w.ListenLoopback()
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { srv.Close() })
	f.url = srv.URL
	return f
}

// fetch gets a JWT-SVID for id through the stand-in Workload API.
func (f *fixture) fetch(t *testing.T, id spiffeid.ID, audience string) wire.JWTSVID {
	t.Helper()
	wl, err := f.source.Workload(id)
	if err != nil {
		t.Fatal(err)
	}
	svid, err := wl.FetchJWTSVID(context.Background(), jwtsvid.Params{Audience: audience})
	if err != nil {
		t.Fatal(err)
	}
	return wire.JWTSVID(svid.Marshal())
}

// sign signs a token for id directly, for lifetimes the Workload API never issues.
func (f *fixture) sign(t *testing.T, id spiffeid.ID, audience []string, iat, exp time.Time) wire.JWTSVID {
	t.Helper()
	token, err := f.source.Sign(workload.Claims{Subject: id, Audience: audience, IssuedAt: iat, Expiry: exp})
	if err != nil {
		t.Fatal(err)
	}
	return token
}

// assertionClaims is the payload of a hand-signed Caller assertion.
type assertionClaims struct {
	Iss    string          `json:"iss"`
	Sub    string          `json:"sub"`
	Aud    string          `json:"aud"`
	Iat    *int64          `json:"iat,omitempty"`
	Exp    *int64          `json:"exp,omitempty"`
	MayAct *map[string]any `json:"may_act,omitempty"`
}

// goodClaims are the claims of a valid assertion for acme/alice through agentID,
// issued at the fixture clock.
func (f *fixture) goodClaims() assertionClaims {
	iat, exp := f.now().Unix(), f.now().Add(login.Lifetime).Unix()
	return assertionClaims{
		Iss:    login.Issuer,
		Sub:    "acme/alice",
		Aud:    wardenAudience,
		Iat:    &iat,
		Exp:    &exp,
		MayAct: &map[string]any{"sub": agentID.String()},
	}
}

// signAssertion signs claims with key. alg is ES256 or HS256 (HS256 ignores key
// and uses a fixed secret); kid "" omits the kid header.
func signAssertion(t *testing.T, key *ecdsa.PrivateKey, alg jose.SignatureAlgorithm, kid string, claims assertionClaims) wire.CallerAssertion {
	t.Helper()
	opts := (&jose.SignerOptions{}).WithType("JWT")
	if kid != "" {
		opts = opts.WithHeader(jose.HeaderKey("kid"), kid)
	}
	var k any = key
	if alg == jose.HS256 {
		k = []byte("0123456789abcdef0123456789abcdef")
	}
	signer, err := jose.NewSigner(jose.SigningKey{Algorithm: alg, Key: k}, opts)
	if err != nil {
		t.Fatal(err)
	}
	token, err := jwt.Signed(signer).Claims(claims).Serialize()
	if err != nil {
		t.Fatal(err)
	}
	return wire.CallerAssertion(token)
}

// valid is a good assertion signed by the fixture's Login key.
func (f *fixture) valid(t *testing.T) wire.CallerAssertion {
	t.Helper()
	return signAssertion(t, f.loginKey, jose.ES256, "", f.goodClaims())
}

// withClaims is a good assertion after mut has changed its claims.
func (f *fixture) withClaims(t *testing.T, mut func(*assertionClaims)) wire.CallerAssertion {
	t.Helper()
	c := f.goodClaims()
	mut(&c)
	return signAssertion(t, f.loginKey, jose.ES256, "", c)
}

type response struct {
	status int
	body   string
	header http.Header
}

// post sends a Lookup with the given Authorization and Caller-Assertion headers
// ("" sends none).
func (f *fixture) post(t *testing.T, authorization wire.Bearer, assertion wire.CallerAssertion) response {
	t.Helper()
	return f.postLookup(t, authorization, assertion, wire.LookupRequest{Target: "acme/tom", Permission: "invoice:approve"})
}

// postLookup sends the given Lookup with the given headers.
func (f *fixture) postLookup(t *testing.T, authorization wire.Bearer, assertion wire.CallerAssertion, lr wire.LookupRequest) response {
	t.Helper()
	body, _ := json.Marshal(lr)
	return f.postRaw(t, authorization, assertion, body)
}

// postRaw sends body as the Lookup body, byte for byte.
func (f *fixture) postRaw(t *testing.T, authorization wire.Bearer, assertion wire.CallerAssertion, body []byte) response {
	t.Helper()
	req, err := http.NewRequest(http.MethodPost, f.url+wire.PathLookup, bytes.NewReader(body))
	if err != nil {
		t.Fatal(err)
	}
	for k, v := range f.header {
		req.Header[k] = v
	}
	if authorization != "" {
		req.Header.Set(wire.HeaderAuthorization, string(authorization))
	}
	if assertion != "" {
		req.Header.Set(wire.HeaderCallerAssertion, string(assertion))
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	raw, err := io.ReadAll(resp.Body)
	if err != nil {
		t.Fatal(err)
	}
	return response{status: resp.StatusCode, body: strings.TrimSpace(string(raw)), header: resp.Header}
}

func (f *fixture) lastDecision(t *testing.T) warden.Decision {
	t.Helper()
	f.mu.Lock()
	defer f.mu.Unlock()
	if len(f.decisions) == 0 {
		t.Fatal("the Warden made no Decision")
	}
	return f.decisions[len(f.decisions)-1]
}

func TestAllowlistedAgentWithValidJWTSVIDGets200(t *testing.T) {
	f := newFixture(t)

	got := f.post(t, wire.BearerFor(f.fetch(t, agentID, wardenAudience)), f.valid(t))

	if got.status != http.StatusOK {
		t.Fatalf("status = %d, body %s; want 200", got.status, got.body)
	}
	d := f.lastDecision(t)
	if d.Outcome != warden.OutcomeAnswerYes || d.Agent != agentID.String() {
		t.Errorf("decision = %+v; want outcome answer_yes for %s", d, agentID)
	}
}

const unauthenticatedBody = `{"error":"unauthenticated"}`

// forge keeps the token's header and signature and swaps in a payload that
// names someone else.
func forge(t *testing.T, token wire.JWTSVID, sub string) wire.JWTSVID {
	t.Helper()
	parts := strings.Split(string(token), ".")
	if len(parts) != 3 {
		t.Fatalf("token has %d segments; want 3", len(parts))
	}
	raw, err := base64.RawURLEncoding.DecodeString(parts[1])
	if err != nil {
		t.Fatal(err)
	}
	var claims map[string]any
	if err := json.Unmarshal(raw, &claims); err != nil {
		t.Fatal(err)
	}
	claims["sub"] = sub
	payload, err := json.Marshal(claims)
	if err != nil {
		t.Fatal(err)
	}
	parts[1] = base64.RawURLEncoding.EncodeToString(payload)
	return wire.JWTSVID(strings.Join(parts, "."))
}

// audClaim decodes the token's payload and returns its raw aud claim.
func audClaim(t *testing.T, token wire.JWTSVID) json.RawMessage {
	t.Helper()
	parts := strings.Split(string(token), ".")
	raw, err := base64.RawURLEncoding.DecodeString(parts[1])
	if err != nil {
		t.Fatal(err)
	}
	var claims struct {
		Aud json.RawMessage `json:"aud"`
	}
	if err := json.Unmarshal(raw, &claims); err != nil {
		t.Fatal(err)
	}
	return claims.Aud
}

func TestUnauthenticatedCasesAnswer401WithOneBody(t *testing.T) {
	f := newFixture(t)
	other, err := workload.New(trustDomain)
	if err != nil {
		t.Fatal(err)
	}
	now := time.Now()

	cases := []struct {
		name          string
		authorization wire.Bearer
		want          warden.Reason
	}{
		{"no header", "", "jwt_svid_missing"},
		{"not a jwt", "Bearer not-a-jwt", "jwt_svid_malformed"},
		{"forged payload", wire.BearerFor(forge(t, f.fetch(t, agentID, wardenAudience), "spiffe://example.com/someone-else")), "jwt_svid_signature"},
		{"unknown signing key", func() wire.Bearer {
			wl, err := other.Workload(agentID)
			if err != nil {
				t.Fatal(err)
			}
			svid, err := wl.FetchJWTSVID(context.Background(), jwtsvid.Params{Audience: wardenAudience})
			if err != nil {
				t.Fatal(err)
			}
			return wire.BearerFor(wire.JWTSVID(svid.Marshal()))
		}(), "jwt_svid_signature"},
		{"wrong audience", wire.BearerFor(f.fetch(t, agentID, "spiffe://example.com/not-the-warden")), "jwt_svid_audience"},
		{"expired", wire.BearerFor(f.sign(t, agentID, []string{wardenAudience}, now.Add(-10*time.Minute), now.Add(-5*time.Minute))), "jwt_svid_expired"},
		{"lifetime too long", wire.BearerFor(f.sign(t, agentID, []string{wardenAudience}, now, now.Add(time.Hour))), "jwt_svid_lifetime"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got := f.post(t, tc.authorization, f.valid(t))

			if got.status != http.StatusUnauthorized {
				t.Errorf("status = %d; want 401", got.status)
			}
			if got.body != unauthenticatedBody {
				t.Errorf("body = %s; want %s", got.body, unauthenticatedBody)
			}
			d := f.lastDecision(t)
			if d.Outcome != warden.OutcomeUnauthenticated || d.FailedCheck != warden.CheckJWTSVID || d.Agent != "" || d.Reason != tc.want {
				t.Errorf("decision = %+v; want unauthenticated/jwt_svid/no agent/%s", d, tc.want)
			}
		})
	}
}

func TestJWTSVIDWithoutIATFailsTheLifetimeCheck(t *testing.T) {
	f := newFixture(t)

	got := f.post(t, wire.BearerFor(f.sign(t, agentID, []string{wardenAudience}, time.Time{}, time.Now().Add(time.Minute))), f.valid(t))

	if got.status != http.StatusUnauthorized || got.body != unauthenticatedBody {
		t.Errorf("response = %d %s; want 401 unauthenticated", got.status, got.body)
	}
	if d := f.lastDecision(t); d.Reason != warden.ReasonJWTSVIDLifetime {
		t.Errorf("reason = %s; want %s", d.Reason, warden.ReasonJWTSVIDLifetime)
	}
}

func TestVerifiedAgentOffTheAllowlistGets403(t *testing.T) {
	f := newFixture(t)

	got := f.post(t, wire.BearerFor(f.fetch(t, unlistedID, wardenAudience)), f.valid(t))

	if got.status != http.StatusForbidden || got.body != `{"error":"agent not allowed"}` {
		t.Errorf("response = %d %s; want 403 agent not allowed", got.status, got.body)
	}
	d := f.lastDecision(t)
	if d.Outcome != warden.OutcomeAgentNotAllowed || d.FailedCheck != warden.CheckAllowlist || d.Agent != unlistedID.String() {
		t.Errorf("decision = %+v; want agent_not_allowed/allowlist for %s", d, unlistedID)
	}
}

func TestAudienceAsStringOrArrayIsAccepted(t *testing.T) {
	f := newFixture(t)
	now := time.Now()
	cases := []struct {
		name     string
		audience []string
		wantJSON string
	}{
		{"string", []string{wardenAudience}, `"` + wardenAudience + `"`},
		{"array", []string{wardenAudience, "spiffe://example.com/other"}, `["` + wardenAudience + `","spiffe://example.com/other"]`},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			token := f.sign(t, agentID, tc.audience, now, now.Add(time.Minute))
			if got := string(audClaim(t, token)); got != tc.wantJSON {
				t.Fatalf("aud claim = %s; want %s", got, tc.wantJSON)
			}

			got := f.post(t, wire.BearerFor(token), f.valid(t))

			if got.status != http.StatusOK {
				t.Errorf("status = %d, body %s; want 200", got.status, got.body)
			}
		})
	}
}

func TestExactlyMaxLifetimeTokenIsAccepted(t *testing.T) {
	f := newFixture(t)
	now := time.Now().Truncate(time.Second)

	got := f.post(t, wire.BearerFor(f.sign(t, agentID, []string{wardenAudience}, now, now.Add(5*time.Minute))), f.valid(t))

	if got.status != http.StatusOK {
		t.Errorf("status = %d, body %s; want 200", got.status, got.body)
	}
}

func TestNewRefusesAnEmptyAudience(t *testing.T) {
	source, err := workload.New(trustDomain)
	if err != nil {
		t.Fatal(err)
	}

	w, err := warden.New(warden.Config{Audience: "", Bundles: source})

	if err == nil || w != nil {
		t.Errorf("New = %v, %v; want nil Warden and an error", w, err)
	}
}

func at(t time.Time) *int64 {
	n := t.Unix()
	return &n
}

func TestBadCallerAssertionsAnswer401WithTheSameBody(t *testing.T) {
	f := newFixture(t)
	otherKey, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	now := f.now()
	otherAgent := spiffeid.RequireFromString("spiffe://example.com/other-agent")

	cases := []struct {
		name      string
		assertion wire.CallerAssertion
		want      warden.Reason
	}{
		{"missing", "", "assertion_missing"},
		{"whitespace", "   ", "assertion_missing"},
		{"not a jwt", "not.a.jwt", "assertion_malformed"},
		{"HS256", signAssertion(t, nil, jose.HS256, "", f.goodClaims()), "assertion_malformed"},
		{"bad signature", signAssertion(t, otherKey, jose.ES256, "", f.goodClaims()), "assertion_signature"},
		{"expired", f.withClaims(t, func(c *assertionClaims) {
			c.Iat, c.Exp = at(now.Add(-10*time.Minute)), at(now.Add(-5*time.Minute))
		}), "assertion_expired"},
		{"wrong audience", f.withClaims(t, func(c *assertionClaims) { c.Aud = "spiffe://example.com/not-the-warden" }), "assertion_audience"},
		{"may_act mismatch", f.withClaims(t, func(c *assertionClaims) { c.MayAct = &map[string]any{"sub": otherAgent.String()} }), "assertion_may_act_mismatch"},
		{"may_act absent", f.withClaims(t, func(c *assertionClaims) { c.MayAct = nil }), "assertion_may_act_mismatch"},
		{"unknown caller", f.withClaims(t, func(c *assertionClaims) { c.Sub = "acme/nobody" }), "assertion_unknown_caller"},
		{"10 minute lifetime", f.withClaims(t, func(c *assertionClaims) { c.Exp = at(now.Add(10 * time.Minute)) }), "assertion_lifetime"},
		{"10 minute lifetime, long expired", f.withClaims(t, func(c *assertionClaims) {
			c.Iat, c.Exp = at(now.Add(-time.Hour)), at(now.Add(-50*time.Minute))
		}), "assertion_lifetime"},
		{"no iat", f.withClaims(t, func(c *assertionClaims) { c.Iat = nil }), "assertion_lifetime"},
		{"no exp", f.withClaims(t, func(c *assertionClaims) { c.Exp = nil }), "assertion_lifetime"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got := f.post(t, wire.BearerFor(f.fetch(t, agentID, wardenAudience)), tc.assertion)

			if got.status != http.StatusUnauthorized || got.body != unauthenticatedBody {
				t.Errorf("response = %d %s; want 401 %s", got.status, got.body, unauthenticatedBody)
			}
			d := f.lastDecision(t)
			if d.Outcome != warden.OutcomeUnauthenticated || d.FailedCheck != warden.CheckCallerAssertion || d.Reason != tc.want || d.Caller != "" || d.Agent != agentID.String() {
				t.Errorf("decision = %+v; want unauthenticated/caller_assertion/%s, agent set, no caller", d, tc.want)
			}
		})
	}
}

func TestCallerAssertionClockLeeway(t *testing.T) {
	f := newFixture(t)
	now := f.now()

	cases := []struct {
		name    string
		iat     time.Time
		exp     time.Time
		want    int
		wantWhy warden.Reason
	}{
		{"exp 30s ago", now.Add(-30*time.Second - 5*time.Minute), now.Add(-30 * time.Second), 200, ""},
		{"exp 61s ago", now.Add(-61*time.Second - 5*time.Minute), now.Add(-61 * time.Second), 401, "assertion_expired"},
		{"iat 30s ahead", now.Add(30 * time.Second), now.Add(30*time.Second + 5*time.Minute), 200, ""},
		{"iat 2m ahead", now.Add(2 * time.Minute), now.Add(2*time.Minute + 5*time.Minute), 401, "assertion_other"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			a := f.withClaims(t, func(c *assertionClaims) { c.Iat, c.Exp = at(tc.iat), at(tc.exp) })

			got := f.post(t, wire.BearerFor(f.fetch(t, agentID, wardenAudience)), a)

			if got.status != tc.want {
				t.Errorf("status = %d; want %d", got.status, tc.want)
			}
			if d := f.lastDecision(t); d.Reason != tc.wantWhy {
				t.Errorf("reason = %q; want %q", d.Reason, tc.wantWhy)
			}
		})
	}
}

func TestClockMovesWithTheInjectedNow(t *testing.T) {
	f := newFixture(t)
	a := f.valid(t)

	f.setNow(f.now().Add(10 * time.Minute))
	got := f.post(t, wire.BearerFor(f.fetch(t, agentID, wardenAudience)), a)

	if got.status != http.StatusUnauthorized || f.lastDecision(t).Reason != warden.ReasonAssertionExpired {
		t.Errorf("response = %d, reason %s; want 401 assertion_expired", got.status, f.lastDecision(t).Reason)
	}
}

func TestUnlistedAgentGets403WhateverItsAssertion(t *testing.T) {
	f := newFixture(t)
	named := f.withClaims(t, func(c *assertionClaims) { c.MayAct = &map[string]any{"sub": unlistedID.String()} })

	for name, assertion := range map[string]wire.CallerAssertion{
		"valid and naming it": named,
		"none":                "",
		"garbage":             "garbage",
	} {
		t.Run(name, func(t *testing.T) {
			got := f.post(t, wire.BearerFor(f.fetch(t, unlistedID, wardenAudience)), assertion)

			if got.status != http.StatusForbidden || got.body != `{"error":"agent not allowed"}` {
				t.Errorf("response = %d %s; want 403 agent not allowed", got.status, got.body)
			}
			if d := f.lastDecision(t); d.FailedCheck != warden.CheckAllowlist || d.Caller != "" {
				t.Errorf("decision = %+v; want allowlist, no caller", d)
			}
		})
	}
}

func TestAssertionKidHeaderIsIgnored(t *testing.T) {
	f := newFixture(t)
	a := signAssertion(t, f.loginKey, jose.ES256, "whatever-kid", f.goodClaims())

	got := f.post(t, wire.BearerFor(f.fetch(t, agentID, wardenAudience)), a)

	if got.status != http.StatusOK {
		t.Errorf("status = %d, body %s; want 200", got.status, got.body)
	}
}

func TestValidAssertionNamesTheCallerInTheDecision(t *testing.T) {
	f := newFixture(t)

	got := f.post(t, wire.BearerFor(f.fetch(t, agentID, wardenAudience)), f.valid(t))

	if got.status != http.StatusOK {
		t.Fatalf("status = %d, body %s; want 200", got.status, got.body)
	}
	if d := f.lastDecision(t); d.Caller != "acme/alice" || d.Agent != agentID.String() {
		t.Errorf("decision = %+v; want caller acme/alice, agent %s", d, agentID)
	}
}

func TestEverySeedUserIsAcceptedAsCaller(t *testing.T) {
	f := newFixture(t)
	for _, user := range []string{"acme/alice", "acme/tom", "acme/bob", "globex/tom", "globex/sam"} {
		t.Run(user, func(t *testing.T) {
			a := f.withClaims(t, func(c *assertionClaims) { c.Sub = user })

			got := f.postLookup(t, wire.BearerFor(f.fetch(t, agentID, wardenAudience)), a, wire.LookupRequest{Target: user, Permission: "invoice:read"})

			if got.status != http.StatusOK || f.lastDecision(t).Caller != user {
				t.Errorf("response = %d, decision %+v; want 200 for %s", got.status, f.lastDecision(t), user)
			}
		})
	}
}

func TestNewRefusesANilLoginKey(t *testing.T) {
	source, err := workload.New(trustDomain)
	if err != nil {
		t.Fatal(err)
	}

	w, err := warden.New(warden.Config{Audience: wardenAudience, Bundles: source})

	if err == nil || w != nil {
		t.Errorf("New = %v, %v; want nil Warden and an error", w, err)
	}
}

const deniedBody = `{"error":"denied"}`

// lookupAs makes a Lookup as caller through the allowlisted Agent.
func (f *fixture) lookupAs(t *testing.T, caller, target, permission string) response {
	t.Helper()
	a := f.withClaims(t, func(c *assertionClaims) { c.Sub = caller })
	return f.postLookup(t, wire.BearerFor(f.fetch(t, agentID, wardenAudience)), a, wire.LookupRequest{Target: target, Permission: permission})
}

func TestLookupCheckAndAnswers(t *testing.T) {
	cases := []struct {
		name                       string
		caller, target, permission string
		status                     int
		body                       string
		outcome                    warden.Outcome
		failed                     warden.FailedCheck
	}{
		{"self yes", "acme/bob", "acme/bob", "invoice:read", 200, `{"holds":true,"role":"Employee"}`, warden.OutcomeAnswerYes, ""},
		{"self no", "acme/bob", "acme/bob", "invoice:approve", 200, `{"holds":false}`, warden.OutcomeAnswerNo, ""},
		{"same tenant with permission:read yes", "acme/alice", "acme/tom", "invoice:approve", 200, `{"holds":true,"role":"Finance Approver"}`, warden.OutcomeAnswerYes, ""},
		{"same tenant with permission:read no", "acme/alice", "acme/bob", "invoice:approve", 200, `{"holds":false}`, warden.OutcomeAnswerNo, ""},
		{"same tenant without permission:read", "acme/bob", "acme/tom", "invoice:approve", 403, deniedBody, warden.OutcomeDenial, warden.CheckLookup},
		{"cross tenant auditor", "acme/alice", "globex/sam", "permission:read", 403, deniedBody, warden.OutcomeDenial, warden.CheckLookup},
		{"cross tenant other way", "globex/sam", "acme/tom", "invoice:approve", 403, deniedBody, warden.OutcomeDenial, warden.CheckLookup},
		{"missing target", "acme/alice", "acme/nobody", "invoice:read", 403, deniedBody, warden.OutcomeDenial, warden.CheckTargetMissing},
		{"target without tenant", "acme/alice", "tom", "invoice:read", 403, deniedBody, warden.OutcomeDenial, warden.CheckLookup},
		{"unknown permission", "acme/alice", "acme/tom", "invoices:approve", 422, `{"error":"unknown permission"}`, warden.OutcomeUnknownPermission, ""},
		{"422 only after the check: no read", "acme/bob", "acme/tom", "invoices:approve", 403, deniedBody, warden.OutcomeDenial, warden.CheckLookup},
		{"422 only after the check: cross tenant", "acme/alice", "globex/sam", "bogus:perm", 403, deniedBody, warden.OutcomeDenial, warden.CheckLookup},
		{"422 only after the check: missing target", "acme/alice", "acme/nobody", "bogus:perm", 403, deniedBody, warden.OutcomeDenial, warden.CheckTargetMissing},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			f := newFixture(t)

			got := f.lookupAs(t, tc.caller, tc.target, tc.permission)

			if got.status != tc.status || got.body != tc.body {
				t.Errorf("response = %d %s; want %d %s", got.status, got.body, tc.status, tc.body)
			}
			d := f.lastDecision(t)
			if d.Outcome != tc.outcome || d.FailedCheck != tc.failed || d.Caller != tc.caller {
				t.Errorf("decision = %+v; want %s/%q for %s", d, tc.outcome, tc.failed, tc.caller)
			}
		})
	}
}

func TestMissingTargetBodyIsByteIdenticalToARefusedLookup(t *testing.T) {
	f := newFixture(t)

	refused := f.lookupAs(t, "acme/bob", "acme/tom", "invoice:read")
	missing := f.lookupAs(t, "acme/alice", "acme/nobody", "invoice:read")

	if refused.status != missing.status || refused.body != missing.body {
		t.Errorf("refused = %d %s, missing = %d %s; want identical", refused.status, refused.body, missing.status, missing.body)
	}
}

func TestBodyNamingTheCallerOrMalformedIsRefused(t *testing.T) {
	cases := map[string]string{
		"names a caller": `{"target":"acme/tom","permission":"invoice:approve","caller":"acme/alice"}`,
		"names a tenant": `{"target":"acme/tom","permission":"invoice:approve","tenant":"acme"}`,
		"malformed":      `{"target":`,
		"empty":          ``,
	}
	for name, body := range cases {
		t.Run(name, func(t *testing.T) {
			f := newFixture(t)

			got := f.postRaw(t, wire.BearerFor(f.fetch(t, agentID, wardenAudience)), f.valid(t), []byte(body))

			if got.status != http.StatusForbidden || got.body != deniedBody {
				t.Errorf("response = %d %s; want 403 denied", got.status, got.body)
			}
			if d := f.lastDecision(t); d.Outcome != warden.OutcomeDenial || d.FailedCheck != warden.CheckLookup {
				t.Errorf("decision = %+v; want denial/lookup_check", d)
			}
		})
	}
}

func TestDecisionCarriesTargetPermissionAndRoleOnYes(t *testing.T) {
	f := newFixture(t)

	f.lookupAs(t, "acme/alice", "acme/tom", "invoice:approve")

	d := f.lastDecision(t)
	if d.Target != "acme/tom" || d.Permission != "invoice:approve" || d.Role != "Finance Approver" || d.Caller != "acme/alice" {
		t.Errorf("decision = %+v; want target acme/tom, permission invoice:approve, role Finance Approver, caller acme/alice", d)
	}
}

// go-spiffe verifies the JWT-SVID against the real clock with its own 60 second
// leeway; the Warden can't inject a clock there. So the boundary is tested with
// tokens backdated or future-dated, 30 s inside and 30 s beyond the leeway.
func TestJWTSVIDExpiryLeeway(t *testing.T) {
	f := newFixture(t)
	now := time.Now().Truncate(time.Second)

	cases := []struct {
		name    string
		iat     time.Time
		exp     time.Time
		want    int
		wantWhy warden.Reason
	}{
		{"exp 30s ago", now.Add(-30*time.Second - 5*time.Minute), now.Add(-30 * time.Second), 200, ""},
		{"exp 90s ago", now.Add(-90*time.Second - 5*time.Minute), now.Add(-90 * time.Second), 401, warden.ReasonJWTSVIDExpired},
		{"issued 4m ago, still valid", now.Add(-4 * time.Minute), now.Add(time.Minute), 200, ""},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			svid := f.sign(t, agentID, []string{wardenAudience}, tc.iat, tc.exp)

			got := f.post(t, wire.BearerFor(svid), f.valid(t))

			if got.status != tc.want {
				t.Errorf("status = %d, body %s; want %d", got.status, got.body, tc.want)
			}
			if d := f.lastDecision(t); d.Reason != tc.wantWhy {
				t.Errorf("reason = %q; want %q", d.Reason, tc.wantWhy)
			}
		})
	}
}
