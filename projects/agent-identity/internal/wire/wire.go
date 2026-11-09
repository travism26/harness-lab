// Package wire holds what crosses the wire between the Agent and the Warden:
// the token named types, the header names, the Lookup path and the body shapes.
// It imports nothing else in the Project, so the Agent and the Warden share it
// without importing each other.
package wire

// JWTSVID is a serialized JWT-SVID. It is a named type so the trustlint R3
// analyzer can keep token values out of log calls.
type JWTSVID string

// CallerAssertion is a serialized Caller assertion signed by the Login.
type CallerAssertion string

// Bearer is the raw value of an Authorization header, "Bearer <JWT-SVID>".
type Bearer string

// BearerPrefix starts every Bearer value.
const BearerPrefix = "Bearer "

// BearerFor wraps a JWT-SVID as an Authorization header value.
func BearerFor(token JWTSVID) Bearer {
	return Bearer(BearerPrefix + string(token))
}

// Header names on a Lookup.
const (
	HeaderAuthorization   = "Authorization"
	HeaderCallerAssertion = "Caller-Assertion"
	HeaderCorrelationID   = "Correlation-Id"
)

// PathLookup is the Warden's one endpoint, served for POST only.
const PathLookup = "/lookup"

// LookupRequest is the Lookup body. It never names the Caller and has no
// Tenant field.
type LookupRequest struct {
	Target     string `json:"target"`
	Permission string `json:"permission"`
}

// Answer is the body of a 200: does the Target hold the Permission, and on
// yes, through which Role.
type Answer struct {
	Holds bool   `json:"holds"`
	Role  string `json:"role,omitempty"`
}

// ErrorBody is the body of every non-200 response.
type ErrorBody struct {
	Error string `json:"error"`
}

// PathMessages is the Broker's one endpoint, served for POST only. It is the
// Messages API path, so the Model client posts to the Broker as to a provider.
const PathMessages = "/v1/messages"

// Header names the Broker adds to a 2xx response: who served the request and
// what it cost (USD).
const (
	HeaderBrokerProvider  = "X-Broker-Provider"
	HeaderBrokerModel     = "X-Broker-Model"
	HeaderBrokerCost      = "X-Broker-Cost"
	HeaderBrokerRequestID = "X-Broker-Request-Id"
)

// BrokerError is the body of every non-2xx Broker response. Reason is a
// jwt_svid_* code or one of the Broker reasons below; UpstreamStatus is set
// only on upstream_error, and is 0 when the provider could not be reached.
type BrokerError struct {
	Reason         string `json:"reason"`
	UpstreamStatus int    `json:"upstream_status,omitempty"`
}

// The Broker's own reasons, beside the jwt_svid_* codes it shares with the Warden.
const (
	ReasonNotAllowlisted = "not_allowlisted"
	ReasonOutsidePin     = "outside_pin"
	ReasonBadRequest     = "bad_request"
	ReasonUpstreamError  = "upstream_error"
)

// The closed set of ErrorBody.Error values.
const (
	ErrUnauthenticated   = "unauthenticated"
	ErrAgentNotAllowed   = "agent not allowed"
	ErrDenied            = "denied"
	ErrUnknownPermission = "unknown permission"
)
