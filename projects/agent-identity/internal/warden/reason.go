package warden

import "strings"

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
