package warden_test

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"io"
	"net/http"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/spiffe/go-spiffe/v2/spiffeid"
	"github.com/spiffe/go-spiffe/v2/svid/jwtsvid"

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
	source *workload.Source
	url    string

	mu        sync.Mutex
	decisions []warden.Decision
}

func newFixture(t *testing.T) *fixture {
	t.Helper()
	source, err := workload.New(trustDomain)
	if err != nil {
		t.Fatal(err)
	}
	f := &fixture{source: source}
	w, err := warden.New(warden.Config{
		Audience:  wardenAudience,
		Bundles:   source,
		Allowlist: []spiffeid.ID{agentID},
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

type response struct {
	status int
	body   string
}

// post sends a Lookup with the given Authorization header ("" sends none).
func (f *fixture) post(t *testing.T, authorization wire.Bearer) response {
	t.Helper()
	body, _ := json.Marshal(wire.LookupRequest{Target: "acme/tom", Permission: "invoice:approve"})
	req, err := http.NewRequest(http.MethodPost, f.url+wire.PathLookup, bytes.NewReader(body))
	if err != nil {
		t.Fatal(err)
	}
	if authorization != "" {
		req.Header.Set(wire.HeaderAuthorization, string(authorization))
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
	return response{status: resp.StatusCode, body: strings.TrimSpace(string(raw))}
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

	got := f.post(t, wire.BearerFor(f.fetch(t, agentID, wardenAudience)))

	if got.status != http.StatusOK {
		t.Fatalf("status = %d, body %s; want 200", got.status, got.body)
	}
	d := f.lastDecision(t)
	if d.Outcome != warden.OutcomeAllowed || d.Agent != agentID.String() {
		t.Errorf("decision = %+v; want outcome allowed for %s", d, agentID)
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
			got := f.post(t, tc.authorization)

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

	got := f.post(t, wire.BearerFor(f.sign(t, agentID, []string{wardenAudience}, time.Time{}, time.Now().Add(time.Minute))))

	if got.status != http.StatusUnauthorized || got.body != unauthenticatedBody {
		t.Errorf("response = %d %s; want 401 unauthenticated", got.status, got.body)
	}
	if d := f.lastDecision(t); d.Reason != warden.ReasonJWTSVIDLifetime {
		t.Errorf("reason = %s; want %s", d.Reason, warden.ReasonJWTSVIDLifetime)
	}
}

func TestVerifiedAgentOffTheAllowlistGets403(t *testing.T) {
	f := newFixture(t)

	got := f.post(t, wire.BearerFor(f.fetch(t, unlistedID, wardenAudience)))

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

			got := f.post(t, wire.BearerFor(token))

			if got.status != http.StatusOK {
				t.Errorf("status = %d, body %s; want 200", got.status, got.body)
			}
		})
	}
}

func TestExactlyMaxLifetimeTokenIsAccepted(t *testing.T) {
	f := newFixture(t)
	now := time.Now().Truncate(time.Second)

	got := f.post(t, wire.BearerFor(f.sign(t, agentID, []string{wardenAudience}, now, now.Add(5*time.Minute))))

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
