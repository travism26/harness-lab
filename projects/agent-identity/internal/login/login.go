// Package login is the Login: it signs the short-lived ES256 Caller assertion
// the Agent carries to the Warden next to its JWT-SVID.
package login

import (
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"errors"
	"fmt"
	"time"

	"github.com/go-jose/go-jose/v4"
	"github.com/go-jose/go-jose/v4/jwt"

	"github.com/travism26/harness-lab/projects/agent-identity/internal/wire"
)

// Issuer is the iss the Login puts on every Caller assertion.
const Issuer = "agent-identity-login"

// Lifetime is exp - iat on every assertion.
const Lifetime = 5 * time.Minute

// Login signs Caller assertions with one key.
type Login struct {
	key *ecdsa.PrivateKey
	now func() time.Time
}

// New makes a Login with a fresh P-256 key. A nil now means time.Now.
func New(now func() time.Time) (*Login, error) {
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		return nil, fmt.Errorf("login: generate key: %w", err)
	}
	return NewWithKey(now, key)
}

// NewWithKey makes a Login that signs with key, which must be a P-256 key. A
// nil now means time.Now.
func NewWithKey(now func() time.Time, key *ecdsa.PrivateKey) (*Login, error) {
	if key == nil || key.Curve != elliptic.P256() {
		return nil, errors.New("login: key must be a non-nil P-256 key")
	}
	if now == nil {
		now = time.Now
	}
	return &Login{key: key, now: now}, nil
}

// PublicKey is the key the Warden trusts to verify assertions.
func (l *Login) PublicKey() *ecdsa.PublicKey {
	return &l.key.PublicKey
}

type mayAct struct {
	Sub string `json:"sub"`
}

// Sign signs an assertion that caller (a tenant/name User id) is asking, for the
// Warden at audience, through the Agent whose SPIFFE ID is agent.
func (l *Login) Sign(caller, audience, agent string) (wire.CallerAssertion, error) {
	signer, err := jose.NewSigner(jose.SigningKey{Algorithm: jose.ES256, Key: l.key}, (&jose.SignerOptions{}).WithType("JWT"))
	if err != nil {
		return "", fmt.Errorf("login: new signer: %w", err)
	}
	now := l.now()
	std := jwt.Claims{
		Issuer:   Issuer,
		Subject:  caller,
		Audience: jwt.Audience{audience},
		IssuedAt: jwt.NewNumericDate(now),
		Expiry:   jwt.NewNumericDate(now.Add(Lifetime)),
	}
	token, err := jwt.Signed(signer).Claims(std).Claims(struct {
		MayAct mayAct `json:"may_act"`
	}{mayAct{Sub: agent}}).Serialize()
	if err != nil {
		return "", fmt.Errorf("login: sign: %w", err)
	}
	return wire.CallerAssertion(token), nil
}
