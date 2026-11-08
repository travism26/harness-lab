package agent_test

import (
	"context"
	"testing"

	"github.com/spiffe/go-spiffe/v2/spiffeid"

	"github.com/travism26/harness-lab/projects/agent-identity/internal/agent"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/standin/workload"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/warden"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/wire"
)

const wardenAudience = "spiffe://example.com/warden"

var (
	trustDomain = spiffeid.RequireTrustDomainFromString("example.com")
	listedID    = spiffeid.RequireFromString("spiffe://example.com/permission-agent")
	unlistedID  = spiffeid.RequireFromString("spiffe://example.com/unlisted-agent")
)

func lookupAs(t *testing.T, id spiffeid.ID) agent.Response {
	t.Helper()
	source, err := workload.New(trustDomain)
	if err != nil {
		t.Fatal(err)
	}
	w, err := warden.New(warden.Config{
		Audience:  wardenAudience,
		Bundles:   source,
		Allowlist: []spiffeid.ID{listedID},
	})
	if err != nil {
		t.Fatal(err)
	}
	srv, err := w.ListenLoopback()
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { srv.Close() })
	wl, err := source.Workload(id)
	if err != nil {
		t.Fatal(err)
	}
	a, err := agent.New(agent.Config{WardenURL: srv.URL, Audience: wardenAudience, Source: wl})
	if err != nil {
		t.Fatal(err)
	}
	res, err := a.Lookup(context.Background(), wire.LookupRequest{Target: "acme/tom", Permission: "invoice:approve"})
	if err != nil {
		t.Fatal(err)
	}
	return res
}

func TestLookupAllowlistedAgent(t *testing.T) {
	if got := lookupAs(t, listedID); got != (agent.Response{Status: 200}) {
		t.Fatalf("got %+v, want status 200", got)
	}
}

func TestLookupUnlistedAgent(t *testing.T) {
	got := lookupAs(t, unlistedID)
	if got.Status != 403 || got.Error != wire.ErrAgentNotAllowed {
		t.Fatalf("got %+v, want 403 %q", got, wire.ErrAgentNotAllowed)
	}
}

func TestNewRejectsEmptyAudience(t *testing.T) {
	source, err := workload.New(trustDomain)
	if err != nil {
		t.Fatal(err)
	}
	wl, err := source.Workload(listedID)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := agent.New(agent.Config{WardenURL: "http://127.0.0.1:1", Source: wl}); err == nil {
		t.Fatal("New accepted an empty Audience")
	}
}
