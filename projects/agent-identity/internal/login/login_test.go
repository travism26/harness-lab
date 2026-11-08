package login_test

import (
	"testing"
	"time"

	"github.com/go-jose/go-jose/v4"
	"github.com/go-jose/go-jose/v4/jwt"

	"github.com/travism26/harness-lab/projects/agent-identity/internal/login"
)

func TestSignProducesAnES256AssertionWithTheExpectedClaims(t *testing.T) {
	now := time.Unix(1_800_000_000, 0)
	lg, err := login.New(func() time.Time { return now })
	if err != nil {
		t.Fatal(err)
	}

	a, err := lg.Sign("acme/alice", "spiffe://example.com/warden", "spiffe://example.com/permission-agent")
	if err != nil {
		t.Fatal(err)
	}

	tok, err := jwt.ParseSigned(string(a), []jose.SignatureAlgorithm{jose.ES256})
	if err != nil {
		t.Fatal(err)
	}
	if alg := tok.Headers[0].Algorithm; alg != "ES256" {
		t.Errorf("alg = %s; want ES256", alg)
	}
	var std jwt.Claims
	var extra struct {
		MayAct *struct {
			Sub string `json:"sub"`
		} `json:"may_act"`
	}
	if err := tok.Claims(lg.PublicKey(), &std, &extra); err != nil {
		t.Fatalf("assertion does not verify: %v", err)
	}
	if std.Issuer != login.Issuer || std.Subject != "acme/alice" {
		t.Errorf("iss/sub = %q/%q", std.Issuer, std.Subject)
	}
	if len(std.Audience) != 1 || std.Audience[0] != "spiffe://example.com/warden" {
		t.Errorf("aud = %v", std.Audience)
	}
	if !std.IssuedAt.Time().Equal(now) {
		t.Errorf("iat = %v; want %v", std.IssuedAt.Time(), now)
	}
	if got := std.Expiry.Time().Sub(std.IssuedAt.Time()); got != 5*time.Minute {
		t.Errorf("exp - iat = %v; want 5m", got)
	}
	if extra.MayAct == nil || extra.MayAct.Sub != "spiffe://example.com/permission-agent" {
		t.Errorf("may_act = %+v", extra.MayAct)
	}
}

func TestNilClockMeansNow(t *testing.T) {
	lg, err := login.New(nil)
	if err != nil {
		t.Fatal(err)
	}
	a, err := lg.Sign("acme/alice", "aud", "agent")
	if err != nil {
		t.Fatal(err)
	}
	tok, _ := jwt.ParseSigned(string(a), []jose.SignatureAlgorithm{jose.ES256})
	var std jwt.Claims
	if err := tok.Claims(lg.PublicKey(), &std); err != nil {
		t.Fatal(err)
	}
	if d := time.Since(std.IssuedAt.Time()); d < -time.Second || d > time.Minute {
		t.Errorf("iat is %v from now", d)
	}
}
