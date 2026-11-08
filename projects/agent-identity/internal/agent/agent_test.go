package agent_test

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/spiffe/go-spiffe/v2/spiffeid"

	"github.com/travism26/harness-lab/projects/agent-identity/internal/agent"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/login"
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
	lg, err := login.New(nil)
	if err != nil {
		t.Fatal(err)
	}
	w, err := warden.New(warden.Config{
		Audience:  wardenAudience,
		Bundles:   source,
		Allowlist: []spiffeid.ID{listedID},
		LoginKey:  lg.PublicKey(),
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
	assertion, err := lg.Sign("acme/alice", wardenAudience, id.String())
	if err != nil {
		t.Fatal(err)
	}
	res, err := a.Lookup(context.Background(), assertion, wire.LookupRequest{Target: "acme/tom", Permission: "invoice:approve"})
	if err != nil {
		t.Fatal(err)
	}
	return res
}

func TestLookupAllowlistedAgent(t *testing.T) {
	if got := lookupAs(t, listedID); got != (agent.Response{Status: 200, Holds: true, Role: "Finance Approver"}) {
		t.Fatalf("got %+v, want 200 holds true as Finance Approver", got)
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

func TestLookupSendsTheAssertionHeaderUntouchedAndOmitsItWhenEmpty(t *testing.T) {
	source, err := workload.New(trustDomain)
	if err != nil {
		t.Fatal(err)
	}
	wl, err := source.Workload(listedID)
	if err != nil {
		t.Fatal(err)
	}
	var got []http.Header
	srv := httptest.NewServer(http.HandlerFunc(func(rw http.ResponseWriter, r *http.Request) {
		got = append(got, r.Header.Clone())
		rw.Write([]byte(`{"holds":false}`))
	}))
	t.Cleanup(srv.Close)
	a, err := agent.New(agent.Config{WardenURL: srv.URL, Audience: wardenAudience, Source: wl})
	if err != nil {
		t.Fatal(err)
	}
	req := wire.LookupRequest{Target: "acme/tom", Permission: "invoice:approve"}

	for _, assertion := range []wire.CallerAssertion{"a.b.c", ""} {
		if _, err := a.Lookup(context.Background(), assertion, req); err != nil {
			t.Fatal(err)
		}
	}

	if len(got) != 2 {
		t.Fatalf("server saw %d requests; want 2", len(got))
	}
	if v := got[0].Get(wire.HeaderCallerAssertion); v != "a.b.c" {
		t.Errorf("header = %q; want a.b.c", v)
	}
	if _, present := got[1][http.CanonicalHeaderKey(wire.HeaderCallerAssertion)]; present {
		t.Error("an empty assertion still sent the header")
	}
}

func TestLookupSendsOnlyTargetAndPermissionAndDecodesTheAnswer(t *testing.T) {
	source, err := workload.New(trustDomain)
	if err != nil {
		t.Fatal(err)
	}
	wl, err := source.Workload(listedID)
	if err != nil {
		t.Fatal(err)
	}
	var (
		method, path string
		header       http.Header
		body         map[string]any
	)
	srv := httptest.NewServer(http.HandlerFunc(func(rw http.ResponseWriter, r *http.Request) {
		method, path, header = r.Method, r.URL.Path, r.Header.Clone()
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			t.Errorf("decode body: %v", err)
		}
		rw.Header().Set("Content-Type", "application/json")
		rw.Write([]byte(`{"holds":false}`))
	}))
	t.Cleanup(srv.Close)
	a, err := agent.New(agent.Config{WardenURL: srv.URL, Audience: wardenAudience, Source: wl})
	if err != nil {
		t.Fatal(err)
	}

	got, err := a.Lookup(context.Background(), "a.b.c", wire.LookupRequest{Target: "acme/tom", Permission: "invoice:approve"})

	if err != nil {
		t.Fatal(err)
	}
	if got != (agent.Response{Status: 200, Holds: false}) {
		t.Errorf("got %+v; want status 200, holds false", got)
	}
	if method != http.MethodPost || path != "/lookup" {
		t.Errorf("request = %s %s; want POST /lookup", method, path)
	}
	if auth := header.Get("Authorization"); !strings.HasPrefix(auth, "Bearer ") || len(auth) == len("Bearer ") {
		t.Error("Authorization is not a Bearer with a token")
	}
	if v := header.Get("Caller-Assertion"); v != "a.b.c" {
		t.Errorf("Caller-Assertion = %q; want a.b.c", v)
	}
	want := map[string]any{"target": "acme/tom", "permission": "invoice:approve"}
	if len(body) != len(want) || body["target"] != want["target"] || body["permission"] != want["permission"] {
		t.Errorf("body = %v; want exactly %v", body, want)
	}
}
