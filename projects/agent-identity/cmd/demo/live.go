package main

import (
	"context"
	"errors"
	"fmt"
	"path/filepath"

	"github.com/spiffe/go-spiffe/v2/bundle/jwtbundle"
	"github.com/spiffe/go-spiffe/v2/spiffeid"

	"github.com/travism26/harness-lab/projects/agent-identity/internal/agent"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/standin/workload"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/workloadsrc"
)

// deps are the outside things a run reaches, so tests can swap them for
// stand-ins behind the same interfaces. The zero value means the real ones.
type deps struct {
	// openJWT opens a JWT source on a Workload API socket. Nil means go-spiffe's
	// workloadapi.JWTSource.
	openJWT func(ctx context.Context, socket string) (jwtSource, error)
}

func (d deps) withDefaults() deps {
	if d.openJWT == nil {
		// An unreachable socket is an error after workloadsrc.Timeout.
		d.openJWT = workloadsrc.OpenAs[jwtSource]
	}
	return d
}

// jwtSource is what a Workload API socket gives: the Agent's JWT-SVIDs and the
// trust bundles the Warden verifies them with. go-spiffe's workloadapi.JWTSource
// is one; the in-process stand-in is another.
type jwtSource interface {
	agent.SVIDSource
	jwtbundle.Source
	Close() error
}

var _ jwtSource = workloadsrc.Source{}

// errNoSource means no source was given for a workload.
var errNoSource = errors.New("no Workload API socket for that workload")

// identities is where a run gets workload JWT-SVIDs and the bundle the Warden
// verifies them with: the in-process stand-in, or spiffecli's sockets.
type identities interface {
	Bundles() jwtbundle.Source
	// Workload returns the source of id's JWT-SVIDs, or errNoSource.
	Workload(id spiffeid.ID) (agent.SVIDSource, error)
	Close()
}

// standInIdentities is the offline default.
type standInIdentities struct{ src *workload.Source }

func newStandInIdentities() (identities, error) {
	td, err := spiffeid.TrustDomainFromString("example.com")
	if err != nil {
		return nil, err
	}
	src, err := workload.New(td)
	if err != nil {
		return nil, err
	}
	return standInIdentities{src}, nil
}

func (s standInIdentities) Bundles() jwtbundle.Source { return s.src }
func (s standInIdentities) Close()                    {}
func (s standInIdentities) Workload(id spiffeid.ID) (agent.SVIDSource, error) {
	return s.src.Workload(id)
}

// spiffeIdentities is the --spiffe-socket mode: the permission-agent's socket,
// the Warden's own socket for its bundle, and optionally the unlisted-agent's.
type spiffeIdentities struct {
	agent, warden, other jwtSource
}

// openSpiffe opens the sockets a run names. The Warden's defaults to
// warden.sock beside the Agent's, as in projects/agent-identity/spiffecli/workloads.toml.
func openSpiffe(ctx context.Context, d deps, agentSock, wardenSock, otherSock string) (identities, error) {
	if wardenSock == "" {
		wardenSock = filepath.Join(filepath.Dir(agentSock), "warden.sock")
	}
	s := &spiffeIdentities{}
	var err error
	if s.agent, err = d.openJWT(ctx, agentSock); err != nil {
		return nil, fmt.Errorf("Workload API socket %s: %w", agentSock, err)
	}
	if s.warden, err = d.openJWT(ctx, wardenSock); err != nil {
		s.Close()
		return nil, fmt.Errorf("Workload API socket %s: %w", wardenSock, err)
	}
	if otherSock != "" {
		if s.other, err = d.openJWT(ctx, otherSock); err != nil {
			s.Close()
			return nil, fmt.Errorf("Workload API socket %s: %w", otherSock, err)
		}
	}
	return s, nil
}

func (s *spiffeIdentities) Bundles() jwtbundle.Source { return s.warden }

func (s *spiffeIdentities) Workload(id spiffeid.ID) (agent.SVIDSource, error) {
	switch id {
	case permissionAgent:
		return s.agent, nil
	case unlistedAgent:
		if s.other != nil {
			return s.other, nil
		}
	}
	return nil, errNoSource
}

func (s *spiffeIdentities) Close() {
	for _, src := range []jwtSource{s.agent, s.warden, s.other} {
		if src != nil {
			src.Close()
		}
	}
}
