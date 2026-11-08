// Command demo runs the Agent identity scenarios against a real Warden on
// loopback and prints what happened.
package main

import (
	"context"
	"fmt"
	"io"
	"log/slog"
	"os"
	"sync"

	"github.com/spiffe/go-spiffe/v2/spiffeid"

	"github.com/travism26/harness-lab/projects/agent-identity/internal/agent"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/login"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/standin/workload"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/warden"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/wire"
)

func main() {
	os.Exit(run(os.Args[1:], os.Stdout, os.Stderr))
}

// scenario is one named demo.
type scenario struct {
	name string
	run  func(ctx context.Context, stdout io.Writer, log *slog.Logger) error
}

// scenarios lists every scenario in tour order.
var scenarios = []scenario{
	{"tokens", runTokens},
}

const usage = "usage: demo <tokens|tour>\n"

// run executes the subcommand and returns the exit code: 0 when the scenario
// ran (a 401 or 403 is a normal result), 1 when setup failed, 2 on bad usage.
func run(args []string, stdout, stderr io.Writer) int {
	if len(args) != 1 {
		io.WriteString(stderr, usage)
		return 2
	}
	var chosen []scenario
	if args[0] == "tour" {
		chosen = scenarios
	} else {
		for _, s := range scenarios {
			if s.name == args[0] {
				chosen = []scenario{s}
			}
		}
	}
	if chosen == nil {
		io.WriteString(stderr, usage)
		return 2
	}
	log := slog.New(slog.NewTextHandler(stderr, nil))
	for _, s := range chosen {
		fmt.Fprintf(stdout, "== %s\n", s.name)
		if err := s.run(context.Background(), stdout, log); err != nil {
			log.Error("demo could not run", "scenario", s.name, "err", err)
			return 1
		}
	}
	return 0
}

// runTokens makes three Lookups: allowed, wrong audience, not on the allowlist.
func runTokens(ctx context.Context, stdout io.Writer, log *slog.Logger) error {
	const (
		wardenAud = "spiffe://example.com/warden"
		wrongAud  = "spiffe://example.com/not-the-warden"
	)
	td, err := spiffeid.TrustDomainFromString("example.com")
	if err != nil {
		return err
	}
	permissionAgent := spiffeid.RequireFromString("spiffe://example.com/permission-agent")
	unlistedAgent := spiffeid.RequireFromString("spiffe://example.com/unlisted-agent")

	source, err := workload.New(td)
	if err != nil {
		return err
	}
	lg, err := login.New(nil)
	if err != nil {
		return err
	}
	var (
		mu   sync.Mutex
		last warden.Decision
	)
	w, err := warden.New(warden.Config{
		Audience:  wardenAud,
		Bundles:   source,
		Allowlist: []spiffeid.ID{permissionAgent},
		LoginKey:  lg.PublicKey(),
		OnDecision: func(d warden.Decision) {
			mu.Lock()
			defer mu.Unlock()
			last = d
		},
	})
	if err != nil {
		return err
	}
	srv, err := w.ListenLoopback()
	if err != nil {
		return err
	}
	defer srv.Close()
	log.Info("warden listening", "url", srv.URL)

	req := wire.LookupRequest{Target: "acme/tom", Permission: "invoice:approve"}
	for _, c := range []struct {
		id  spiffeid.ID
		aud string
	}{
		{permissionAgent, wardenAud},
		{permissionAgent, wrongAud},
		{unlistedAgent, wardenAud},
	} {
		wl, err := source.Workload(c.id)
		if err != nil {
			return err
		}
		a, err := agent.New(agent.Config{WardenURL: srv.URL, Audience: c.aud, Source: wl})
		if err != nil {
			return err
		}
		assertion, err := lg.Sign("acme/alice", wardenAud, c.id.String())
		if err != nil {
			return err
		}
		res, err := a.Lookup(ctx, assertion, req)
		if err != nil {
			return err
		}
		mu.Lock()
		d := last
		mu.Unlock()
		line := fmt.Sprintf("POST /lookup  agent=%s  aud=%s  -> %d  outcome=%s", c.id, c.aud, res.Status, d.Outcome)
		if d.Reason != "" {
			line += fmt.Sprintf("  reason=%s", d.Reason)
		}
		fmt.Fprintln(stdout, line)
	}
	return nil
}
