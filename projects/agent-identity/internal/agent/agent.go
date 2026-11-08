// Package agent is the minimal Agent client: it fetches a JWT-SVID through the
// Workload API and makes a Lookup against the Warden with it. It shares types
// with the Warden only through internal/wire and never imports the Warden.
package agent

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"

	"github.com/spiffe/go-spiffe/v2/svid/jwtsvid"

	"github.com/travism26/harness-lab/projects/agent-identity/internal/wire"
)

// SVIDSource is the small Workload API interface the Agent fetches its JWT-SVID
// through. The stand-in (internal/standin/workload) serves it in check;
// go-spiffe's workloadapi.JWTSource plugs in live.
type SVIDSource interface {
	FetchJWTSVID(ctx context.Context, params jwtsvid.Params) (*jwtsvid.SVID, error)
}

// Config is what an Agent is given at startup.
type Config struct {
	// WardenURL is the Warden's base URL, such as http://127.0.0.1:54321.
	WardenURL string
	// Audience is the Warden's SPIFFE ID, asked for as the JWT-SVID's aud.
	Audience string
	// Source is where the Agent fetches its JWT-SVID.
	Source SVIDSource
	// HTTPClient makes the request. Nil means http.DefaultClient.
	HTTPClient *http.Client
}

// Agent makes Lookups against the Warden as one workload.
type Agent struct {
	cfg Config
}

// New builds an Agent. An empty WardenURL or Audience, or a nil Source, is an
// error.
func New(cfg Config) (*Agent, error) {
	switch {
	case cfg.WardenURL == "":
		return nil, errors.New("agent: a Warden URL is required")
	case cfg.Audience == "":
		return nil, errors.New("agent: an audience is required")
	case cfg.Source == nil:
		return nil, errors.New("agent: a JWT-SVID source is required")
	}
	if cfg.HTTPClient == nil {
		cfg.HTTPClient = http.DefaultClient
	}
	return &Agent{cfg: cfg}, nil
}

// Response is what the Warden returned for one Lookup: the HTTP status and, on a non-200, the error body's value.
type Response struct {
	// Status is the HTTP status code.
	Status int
	// Error is the ErrorBody error field on a non-200, and "" on a 200.
	Error string
}

// Lookup fetches a fresh JWT-SVID and POSTs the Lookup to the Warden. A 401 or
// 403 is a normal Response, not an error; the error return is for a failed fetch
// or a failed transport. Errors never include the token.
func (a *Agent) Lookup(ctx context.Context, req wire.LookupRequest) (Response, error) {
	svid, err := a.cfg.Source.FetchJWTSVID(ctx, jwtsvid.Params{Audience: a.cfg.Audience})
	if err != nil {
		return Response{}, fmt.Errorf("agent: fetch JWT-SVID: %w", err)
	}
	body, err := json.Marshal(req)
	if err != nil {
		return Response{}, fmt.Errorf("agent: encode Lookup: %w", err)
	}
	httpReq, err := http.NewRequestWithContext(ctx, http.MethodPost, a.cfg.WardenURL+wire.PathLookup, bytes.NewReader(body))
	if err != nil {
		return Response{}, fmt.Errorf("agent: build Lookup request: %w", err)
	}
	httpReq.Header.Set("Content-Type", "application/json")
	httpReq.Header.Set(wire.HeaderAuthorization, string(wire.BearerFor(wire.JWTSVID(svid.Marshal()))))
	resp, err := a.cfg.HTTPClient.Do(httpReq)
	if err != nil {
		// The transport error is a *url.Error holding URL and cause, never headers.
		return Response{}, fmt.Errorf("agent: send Lookup: %w", err)
	}
	defer resp.Body.Close()
	res := Response{Status: resp.StatusCode}
	if resp.StatusCode != http.StatusOK {
		var eb wire.ErrorBody
		if err := json.NewDecoder(resp.Body).Decode(&eb); err != nil {
			return res, fmt.Errorf("agent: decode error body (status %d): %w", resp.StatusCode, err)
		}
		res.Error = eb.Error
	}
	return res, nil
}
