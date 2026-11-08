// Package workload is the in-process stand-in for the SPIFFE Workload API. It
// makes one ES256 signing key at startup, hands each workload a JWT-SVID
// fetcher shaped like go-spiffe's jwtsvid.Source, and serves the matching
// static JWT bundle as a jwtbundle.Source for the Warden.
package workload

import (
	"context"
	"crypto"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"errors"
	"fmt"
	"time"

	"github.com/go-jose/go-jose/v4"
	"github.com/go-jose/go-jose/v4/jwt"
	"github.com/spiffe/go-spiffe/v2/bundle/jwtbundle"
	"github.com/spiffe/go-spiffe/v2/spiffeid"
	"github.com/spiffe/go-spiffe/v2/svid/jwtsvid"

	"github.com/travism26/harness-lab/projects/agent-identity/internal/wire"
)

// TTL is the lifetime of every JWT-SVID the stand-in issues, matching
// spiffecli's jwt_svid_ttl = "5m".
const TTL = 5 * time.Minute

// Source signs JWT-SVIDs for one trust domain with a key made at startup.
type Source struct {
	td     spiffeid.TrustDomain
	keyID  string
	signer jose.Signer
	bundle *jwtbundle.Bundle
	key    *ecdsa.PrivateKey
}

// New makes a Source for the trust domain with a fresh ES256 key.
func New(td spiffeid.TrustDomain) (*Source, error) {
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		return nil, fmt.Errorf("workload stand-in: generate key: %w", err)
	}
	return NewWithKey(td, key)
}

// NewWithKey makes a Source for the trust domain that signs with key, which
// must be a P-256 key.
func NewWithKey(td spiffeid.TrustDomain, key *ecdsa.PrivateKey) (*Source, error) {
	if key == nil || key.Curve != elliptic.P256() {
		return nil, errors.New("workload stand-in: key must be a non-nil P-256 key")
	}
	keyID := rand.Text()
	signer, err := jose.NewSigner(
		jose.SigningKey{Algorithm: jose.ES256, Key: key},
		(&jose.SignerOptions{}).WithType("JWT").WithHeader(jose.HeaderKey("kid"), keyID),
	)
	if err != nil {
		return nil, fmt.Errorf("workload stand-in: signer: %w", err)
	}
	return &Source{
		td:     td,
		keyID:  keyID,
		key:    key,
		signer: signer,
		bundle: jwtbundle.FromJWTAuthorities(td, map[string]crypto.PublicKey{keyID: key.Public()}),
	}, nil
}

// GetJWTBundleForTrustDomain serves the stand-in's static bundle, so the
// Source is the Warden's jwtbundle.Source.
func (s *Source) GetJWTBundleForTrustDomain(td spiffeid.TrustDomain) (*jwtbundle.Bundle, error) {
	return s.bundle.GetJWTBundleForTrustDomain(td)
}

// Claims are the claims of one JWT-SVID. Audience may be empty only to build a
// broken token.
type Claims struct {
	Subject  spiffeid.ID
	Audience []string
	// IssuedAt is the iat claim. The zero time omits iat, to build a token that
	// can't show its lifetime.
	IssuedAt time.Time
	Expiry   time.Time
}

// Sign signs claims with the stand-in's key. Workload fetches use it with a
// TTL lifetime; tests use it directly for expired and too-long-lived tokens.
func (s *Source) Sign(c Claims) (wire.JWTSVID, error) {
	claims := jwt.Claims{
		Subject:  c.Subject.String(),
		Audience: jwt.Audience(c.Audience),
		Expiry:   jwt.NewNumericDate(c.Expiry),
	}
	if !c.IssuedAt.IsZero() {
		claims.IssuedAt = jwt.NewNumericDate(c.IssuedAt)
	}
	token, err := jwt.Signed(s.signer).Claims(claims).Serialize()
	if err != nil {
		return "", fmt.Errorf("workload stand-in: sign: %w", err)
	}
	return wire.JWTSVID(token), nil
}

// Workload returns the JWT-SVID fetcher one workload sees: every SVID it
// fetches names id, the way the Workload API answers for the calling workload.
func (s *Source) Workload(id spiffeid.ID) (*Workload, error) {
	if !id.MemberOf(s.td) {
		return nil, fmt.Errorf("workload stand-in: %s is not in trust domain %s", id, s.td)
	}
	return &Workload{source: s, id: id, now: time.Now}, nil
}

// Workload fetches JWT-SVIDs for one SPIFFE ID. It satisfies jwtsvid.Source,
// the same interface go-spiffe's workloadapi.JWTSource offers live.
type Workload struct {
	source *Source
	id     spiffeid.ID
	now    func() time.Time
}

// FetchJWTSVID signs a JWT-SVID for this workload with a TTL lifetime.
func (w *Workload) FetchJWTSVID(_ context.Context, params jwtsvid.Params) (*jwtsvid.SVID, error) {
	if params.Audience == "" {
		return nil, errors.New("workload stand-in: audience is required")
	}
	if !params.Subject.IsZero() && params.Subject != w.id {
		return nil, fmt.Errorf("workload stand-in: no SVID for %s", params.Subject)
	}
	now := w.now()
	token, err := w.source.Sign(Claims{
		Subject:  w.id,
		Audience: append([]string{params.Audience}, params.ExtraAudiences...),
		IssuedAt: now,
		Expiry:   now.Add(TTL),
	})
	if err != nil {
		return nil, err
	}
	return jwtsvid.ParseAndValidate(string(token), w.source, []string{params.Audience})
}
