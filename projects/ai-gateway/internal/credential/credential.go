// Package credential holds the one type that may carry a Forwarded credential.
// The type is copied onto the Upstream request and nowhere else; the analyzer
// in projects/ai-gateway/internal/secrettype keeps it out of the Call record
// and out of log and fmt calls.
package credential

import "net/http"

// Credential is the value of a header that carries a caller's secret.
type Credential string

// String never returns the value, so an accidental format does not print it.
func (Credential) String() string { return "[redacted]" }

// GoString never returns the value.
func (Credential) GoString() string { return "credential.Credential([redacted])" }

// Value returns the secret. Only the code that sets the Upstream request header calls it.
func (c Credential) Value() string { return string(c) }

// Names are the request headers that carry a Forwarded credential.
var Names = []string{"Authorization", "X-Api-Key", "Cookie"}

// Forwarded is the set of Forwarded credentials taken off a client request.
// A header the client did not send has no entry.
type Forwarded map[string][]Credential

// Take removes the credential headers from h and returns them.
func Take(h http.Header) Forwarded {
	f := Forwarded{}
	for _, name := range Names {
		for _, v := range h.Values(name) {
			f[name] = append(f[name], Credential(v))
		}
		h.Del(name)
	}
	return f
}

// Apply sets the credentials on the Upstream request header h.
func (f Forwarded) Apply(h http.Header) {
	for name, vs := range f {
		for _, v := range vs {
			h.Add(name, v.Value())
		}
	}
}
