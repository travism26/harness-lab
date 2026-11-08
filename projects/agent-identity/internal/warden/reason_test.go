package warden_test

import (
	"crypto"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"errors"
	"fmt"
	"testing"
	"time"

	"github.com/go-jose/go-jose/v4"
	"github.com/go-jose/go-jose/v4/jwt"
	"github.com/spiffe/go-spiffe/v2/bundle/jwtbundle"
	"github.com/spiffe/go-spiffe/v2/spiffeid"
	"github.com/spiffe/go-spiffe/v2/svid/jwtsvid"

	"github.com/travism26/harness-lab/projects/agent-identity/internal/warden"
)

func TestJWTSVIDReasonMapsGoSpiffeErrors(t *testing.T) {
	wrapped := func(msg string) error { return fmt.Errorf("jwtsvid: %w", errors.New(msg)) }
	cases := []struct {
		name string
		err  error
		want warden.Reason
	}{
		{"parse", wrapped("unable to parse JWT token"), "jwt_svid_malformed"},
		{"no kid", wrapped("token header missing key id"), "jwt_svid_malformed"},
		{"bad typ", wrapped("token header type not equal to either JWT or JOSE"), "jwt_svid_malformed"},
		{"no sub", wrapped("token missing subject claim"), "jwt_svid_malformed"},
		{"no exp", wrapped("token missing exp claim"), "jwt_svid_malformed"},
		{"bad sub", wrapped("token has an invalid subject claim: x"), "jwt_svid_malformed"},
		{"unknown authority", wrapped(`no JWT authority "k" found for trust domain "example.com"`), "jwt_svid_signature"},
		{"bad signature", wrapped("unable to get claims from token: go-jose/go-jose: error in cryptographic primitive"), "jwt_svid_signature"},
		{"other claims error", wrapped("unable to get claims from token: something else"), "jwt_svid_other"},
		{"expired", wrapped("token has expired"), "jwt_svid_expired"},
		{"audience", wrapped(`expected audience in ["a"] (audience=["b"])`), "jwt_svid_audience"},
		{"no bundle", wrapped(`no bundle found for trust domain "other.org"`), "jwt_svid_other"},
		{"unwrapped go-jose", errors.New("go-jose/go-jose/jwt: validation failed, token not valid yet (nbf)"), "jwt_svid_other"},
		{"unknown", errors.New("something nobody planned for"), "jwt_svid_other"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := warden.JWTSVIDReason(tc.err); got != tc.want {
				t.Errorf("JWTSVIDReason(%q) = %s; want %s", tc.err, got, tc.want)
			}
		})
	}
}

func TestJWTSVIDReasonOnRealGoSpiffeErrors(t *testing.T) {
	const audience = "spiffe://example.com/warden"
	const kid = "test-kid"
	newKey := func() *ecdsa.PrivateKey {
		k, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
		if err != nil {
			t.Fatal(err)
		}
		return k
	}
	key := newKey()
	td := spiffeid.RequireTrustDomainFromString("example.com")
	bundle := jwtbundle.FromJWTAuthorities(td, map[string]crypto.PublicKey{kid: key.Public()})

	// token signs claims with k; kid "" omits the kid header, typ "" means JWT.
	token := func(k *ecdsa.PrivateKey, kid, typ string, claims map[string]any) string {
		opts := (&jose.SignerOptions{}).WithType(jose.ContentType(typ))
		if typ == "" {
			opts = (&jose.SignerOptions{}).WithType("JWT")
		}
		if kid != "" {
			opts = opts.WithHeader(jose.HeaderKey("kid"), kid)
		}
		signer, err := jose.NewSigner(jose.SigningKey{Algorithm: jose.ES256, Key: k}, opts)
		if err != nil {
			t.Fatal(err)
		}
		s, err := jwt.Signed(signer).Claims(claims).Serialize()
		if err != nil {
			t.Fatal(err)
		}
		return s
	}
	now := time.Now()
	good := func() map[string]any {
		return map[string]any{
			"sub": "spiffe://example.com/agent",
			"aud": []string{audience},
			"iat": now.Unix(),
			"exp": now.Add(time.Minute).Unix(),
		}
	}
	with := func(mut func(map[string]any)) map[string]any {
		c := good()
		mut(c)
		return c
	}

	cases := []struct {
		name  string
		token string
		want  warden.Reason
	}{
		{"unparseable", "not-a-jwt", "jwt_svid_malformed"},
		{"no kid", token(key, "", "", good()), "jwt_svid_malformed"},
		{"bad typ", token(key, kid, "foo", good()), "jwt_svid_malformed"},
		{"no sub", token(key, kid, "", with(func(c map[string]any) { delete(c, "sub") })), "jwt_svid_malformed"},
		{"no exp", token(key, kid, "", with(func(c map[string]any) { delete(c, "exp") })), "jwt_svid_malformed"},
		{"sub not a SPIFFE ID", token(key, kid, "", with(func(c map[string]any) { c["sub"] = "not a spiffe id" })), "jwt_svid_malformed"},
		{"other trust domain", token(key, kid, "", with(func(c map[string]any) { c["sub"] = "spiffe://other.org/agent" })), "jwt_svid_other"},
		{"kid not in bundle", token(key, "unknown-kid", "", good()), "jwt_svid_signature"},
		{"signed by another key", token(newKey(), kid, "", good()), "jwt_svid_signature"},
		{"expired", token(key, kid, "", with(func(c map[string]any) { c["exp"] = now.Add(-5 * time.Minute).Unix() })), "jwt_svid_expired"},
		{"wrong audience", token(key, kid, "", with(func(c map[string]any) { c["aud"] = []string{"spiffe://example.com/other"} })), "jwt_svid_audience"},
		{"not yet valid", token(key, kid, "", with(func(c map[string]any) { c["nbf"] = now.Add(10 * time.Minute).Unix() })), "jwt_svid_other"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			_, err := jwtsvid.ParseAndValidate(tc.token, bundle, []string{audience})
			if err == nil {
				t.Fatal("ParseAndValidate accepted the token")
			}
			if got := warden.JWTSVIDReason(err); got != tc.want {
				t.Errorf("JWTSVIDReason(%q) = %s; want %s", err, got, tc.want)
			}
		})
	}
}

func TestAssertionReasonMapsGoJoseErrors(t *testing.T) {
	cases := []struct {
		name string
		err  error
		want warden.Reason
	}{
		{"expired", jwt.ErrExpired, "assertion_expired"},
		{"wrapped expired", fmt.Errorf("x: %w", jwt.ErrExpired), "assertion_expired"},
		{"audience", jwt.ErrInvalidAudience, "assertion_audience"},
		{"issued in the future", jwt.ErrIssuedInTheFuture, "assertion_other"},
		{"not yet valid", jwt.ErrNotValidYet, "assertion_other"},
		{"unknown", errors.New("something nobody planned for"), "assertion_other"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := warden.AssertionReason(tc.err); got != tc.want {
				t.Errorf("AssertionReason(%q) = %s; want %s", tc.err, got, tc.want)
			}
		})
	}
}
