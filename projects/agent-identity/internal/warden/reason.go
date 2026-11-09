package warden

import (
	"errors"

	"github.com/go-jose/go-jose/v4/jwt"

	"github.com/travism26/harness-lab/projects/agent-identity/internal/svidverify"
)

// Reason is a closed-set code for why a token failed. It is safe to record: it
// never carries the raw error. The jwt_svid_* codes are the Broker's too, so
// they live in svidverify.
type Reason = svidverify.Reason

const (
	ReasonJWTSVIDMissing   = svidverify.ReasonMissing
	ReasonJWTSVIDMalformed = svidverify.ReasonMalformed
	ReasonJWTSVIDSignature = svidverify.ReasonSignature
	ReasonJWTSVIDExpired   = svidverify.ReasonExpired
	ReasonJWTSVIDAudience  = svidverify.ReasonAudience
	ReasonJWTSVIDLifetime  = svidverify.ReasonLifetime
	ReasonJWTSVIDOther     = svidverify.ReasonOther

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

// JWTSVIDReason maps an error from jwtsvid.ParseAndValidate to a Reason. An
// error it does not know is ReasonJWTSVIDOther.
func JWTSVIDReason(err error) Reason { return svidverify.ReasonFor(err) }

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
