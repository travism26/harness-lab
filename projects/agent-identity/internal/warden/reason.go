package warden

import (
	"errors"
	"strings"

	"github.com/go-jose/go-jose/v4/jwt"
)

// Reason is a closed-set code for why a token failed. It is safe to record: it
// never carries the raw error.
type Reason string

const (
	ReasonJWTSVIDMissing   Reason = "jwt_svid_missing"
	ReasonJWTSVIDMalformed Reason = "jwt_svid_malformed"
	ReasonJWTSVIDSignature Reason = "jwt_svid_signature"
	ReasonJWTSVIDExpired   Reason = "jwt_svid_expired"
	ReasonJWTSVIDAudience  Reason = "jwt_svid_audience"
	ReasonJWTSVIDLifetime  Reason = "jwt_svid_lifetime"
	ReasonJWTSVIDOther     Reason = "jwt_svid_other"

	ReasonAssertionMissing        Reason = "assertion_missing"
	ReasonAssertionMalformed      Reason = "assertion_malformed"
	ReasonAssertionSignature      Reason = "assertion_signature"
	ReasonAssertionExpired        Reason = "assertion_expired"
	ReasonAssertionAudience       Reason = "assertion_audience"
	ReasonAssertionLifetime       Reason = "assertion_lifetime"
	ReasonAssertionOther          Reason = "assertion_other"
	ReasonAssertionMayActMismatch Reason = "assertion_may_act_mismatch"
	ReasonAssertionUnknownCaller  Reason = "assertion_unknown_caller"
)

// jwtsvidReasons maps go-spiffe's error text to a Reason, first match wins. It
// is pinned by reason_test.go.
var jwtsvidReasons = []struct {
	prefix string
	reason Reason
}{
	{"jwtsvid: unable to parse JWT token", ReasonJWTSVIDMalformed},
	{"jwtsvid: token header missing key id", ReasonJWTSVIDMalformed},
	{"jwtsvid: token header type not equal", ReasonJWTSVIDMalformed},
	{"jwtsvid: token missing ", ReasonJWTSVIDMalformed},
	{"jwtsvid: token has an invalid subject claim", ReasonJWTSVIDMalformed},
	{"jwtsvid: no JWT authority ", ReasonJWTSVIDSignature},
	{"jwtsvid: unable to get claims from token: go-jose/go-jose: error in cryptographic primitive", ReasonJWTSVIDSignature},
	{"jwtsvid: token has expired", ReasonJWTSVIDExpired},
	{"jwtsvid: expected audience in ", ReasonJWTSVIDAudience},
}

// JWTSVIDReason maps an error from jwtsvid.ParseAndValidate to a Reason. An
// error it does not know is ReasonJWTSVIDOther.
func JWTSVIDReason(err error) Reason {
	msg := err.Error()
	for _, r := range jwtsvidReasons {
		if strings.HasPrefix(msg, r.prefix) {
			return r.reason
		}
	}
	return ReasonJWTSVIDOther
}

// AssertionReason maps a go-jose claim validation error to a Reason. An error it
// does not know, including a token issued in the future, is ReasonAssertionOther.
func AssertionReason(err error) Reason {
	switch {
	case errors.Is(err, jwt.ErrExpired):
		return ReasonAssertionExpired
	case errors.Is(err, jwt.ErrInvalidAudience):
		return ReasonAssertionAudience
	}
	return ReasonAssertionOther
}
