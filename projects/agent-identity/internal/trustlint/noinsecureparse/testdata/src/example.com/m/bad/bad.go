package bad

import (
	"github.com/go-jose/go-jose/v4"
	"github.com/go-jose/go-jose/v4/jwt"
	"github.com/spiffe/go-spiffe/v2/exp/svid/witsvid"
	"github.com/spiffe/go-spiffe/v2/svid/jwtsvid"
)

func parse(t *jwt.JSONWebToken, s jose.JSONWebSignature) {
	jwtsvid.ParseInsecure("x", nil)     // want `R4: github.com/spiffe/go-spiffe/v2/svid/jwtsvid.ParseInsecure skips signature verification; use it only in _test.go`
	t.UnsafeClaimsWithoutVerification() // want `R4: \(\*github.com/go-jose/go-jose/v4/jwt.JSONWebToken\).UnsafeClaimsWithoutVerification skips signature verification; use it only in _test.go`
	f := jwtsvid.ParseInsecure          // want `R4: github.com/spiffe/go-spiffe/v2/svid/jwtsvid.ParseInsecure skips signature verification`
	_ = f
	witsvid.ParseInsecure("x")           // want `R4: github.com/spiffe/go-spiffe/v2/exp/svid/witsvid.ParseInsecure skips signature verification; use it only in _test.go`
	s.UnsafePayloadWithoutVerification() // want `R4: \(github.com/go-jose/go-jose/v4.JSONWebSignature\).UnsafePayloadWithoutVerification skips signature verification; use it only in _test.go`
}
