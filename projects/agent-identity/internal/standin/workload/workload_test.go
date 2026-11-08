package workload_test

import (
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"testing"
	"time"

	"github.com/go-jose/go-jose/v4"
	"github.com/go-jose/go-jose/v4/jwt"
	"github.com/spiffe/go-spiffe/v2/spiffeid"

	"github.com/travism26/harness-lab/projects/agent-identity/internal/standin/workload"
)

func TestNewWithKeyRejectsANilOrNonP256KeyAndSignsWithAValidOne(t *testing.T) {
	td := spiffeid.RequireTrustDomainFromString("example.com")
	if _, err := workload.NewWithKey(td, nil); err == nil {
		t.Error("nil key accepted")
	}
	p384, err := ecdsa.GenerateKey(elliptic.P384(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := workload.NewWithKey(td, p384); err == nil {
		t.Error("P-384 key accepted")
	}

	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	src, err := workload.NewWithKey(td, key)
	if err != nil {
		t.Fatal(err)
	}
	svid, err := src.Sign(workload.Claims{
		Subject:  spiffeid.RequireFromString("spiffe://example.com/agent"),
		Audience: []string{"spiffe://example.com/warden"},
		IssuedAt: time.Now(),
		Expiry:   time.Now().Add(time.Minute),
	})
	if err != nil {
		t.Fatal(err)
	}
	tok, err := jwt.ParseSigned(string(svid), []jose.SignatureAlgorithm{jose.ES256})
	if err != nil {
		t.Fatal(err)
	}
	var std jwt.Claims
	if err := tok.Claims(&key.PublicKey, &std); err != nil {
		t.Errorf("SVID does not verify under the injected key: %v", err)
	}
}
