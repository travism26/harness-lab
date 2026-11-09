// Package svidverify is the one JWT-SVID check the Warden and the Broker share:
// the Authorization header, the signature against the bundle, the audience, the
// expiry within go-spiffe's leeway and the maximum lifetime. Each failure is a
// closed-set Reason that never carries the raw error. It imports only the wire
// package, so the Warden and the Broker share it without importing each other.
package svidverify

import (
	"errors"
	"strings"
	"time"

	"github.com/spiffe/go-spiffe/v2/bundle/jwtbundle"
	"github.com/spiffe/go-spiffe/v2/svid/jwtsvid"

	"github.com/travism26/harness-lab/projects/agent-identity/internal/wire"
)

// MaxLifetime is the longest exp - iat accepted on a token, whatever the clock says.
const MaxLifetime = 5 * time.Minute

// Reason is a closed-set code for why a JWT-SVID failed. It is safe to record.
type Reason string

const (
	ReasonMissing   Reason = "jwt_svid_missing"
	ReasonMalformed Reason = "jwt_svid_malformed"
	ReasonSignature Reason = "jwt_svid_signature"
	ReasonExpired   Reason = "jwt_svid_expired"
	ReasonAudience  Reason = "jwt_svid_audience"
	ReasonLifetime  Reason = "jwt_svid_lifetime"
	ReasonOther     Reason = "jwt_svid_other"
)

// reasons maps go-spiffe's error text to a Reason, first match wins. The
// Warden's reason_test.go pins it.
var reasons = []struct {
	prefix string
	reason Reason
}{
	{"jwtsvid: unable to parse JWT token", ReasonMalformed},
	{"jwtsvid: token header missing key id", ReasonMalformed},
	{"jwtsvid: token header type not equal", ReasonMalformed},
	{"jwtsvid: token missing ", ReasonMalformed},
	{"jwtsvid: token has an invalid subject claim", ReasonMalformed},
	{"jwtsvid: no JWT authority ", ReasonSignature},
	{"jwtsvid: unable to get claims from token: go-jose/go-jose: error in cryptographic primitive", ReasonSignature},
	{"jwtsvid: token has expired", ReasonExpired},
	{"jwtsvid: expected audience in ", ReasonAudience},
}

// ReasonFor maps an error from jwtsvid.ParseAndValidate to a Reason. An error
// it does not know is ReasonOther.
func ReasonFor(err error) Reason {
	msg := err.Error()
	for _, r := range reasons {
		if strings.HasPrefix(msg, r.prefix) {
			return r.reason
		}
	}
	return ReasonOther
}

// Verify checks the Authorization header values' JWT-SVID: exactly one header, exactly one audience, signature against the
// bundle, audience, expiry, then the maximum lifetime. On failure it returns a
// nil SVID, the Reason and the raw error, which is for a debug log only because
// it may hold token detail. The error is nil for a missing or malformed header.
func Verify(authorization []string, bundles jwtbundle.Source, audience string) (*jwtsvid.SVID, Reason, error) {
	if len(authorization) > 1 {
		return nil, ReasonMalformed, nil
	}
	var header wire.Bearer
	if len(authorization) == 1 {
		header = wire.Bearer(authorization[0])
	}
	// net/http trims trailing spaces, so "Bearer " arrives as "Bearer".
	token, ok := strings.CutPrefix(string(header), wire.BearerPrefix)
	switch {
	case header == "" || strings.TrimSpace(string(header)) == strings.TrimSpace(wire.BearerPrefix) || (ok && strings.TrimSpace(token) == ""):
		return nil, ReasonMissing, nil
	case !ok:
		return nil, ReasonMalformed, nil
	}
	svid, err := jwtsvid.ParseAndValidate(token, bundles, []string{audience})
	if err != nil {
		return nil, ReasonFor(err), err
	}
	if len(svid.Audience) != 1 {
		return nil, ReasonAudience, errors.New("svidverify: token names more than one audience")
	}
	if !withinLifetime(svid) {
		return nil, ReasonLifetime, errors.New("svidverify: lifetime too long or unknown")
	}
	return svid, "", nil
}

// withinLifetime reports whether the SVID has an iat and exp - iat is at most
// MaxLifetime. A token without iat can't show its lifetime, so it fails.
func withinLifetime(svid *jwtsvid.SVID) bool {
	iat, ok := svid.Claims["iat"].(float64)
	if !ok {
		return false
	}
	return svid.Expiry.Sub(time.Unix(int64(iat), 0)) <= MaxLifetime
}
