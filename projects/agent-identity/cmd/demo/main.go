// Command demo runs the Agent identity scenarios against a real Warden on
// loopback and prints what happened.
package main

import (
	"context"
	"flag"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"os"
	"strings"
	"sync"

	"github.com/spiffe/go-spiffe/v2/spiffeid"

	"github.com/travism26/harness-lab/projects/agent-identity/internal/agent"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/login"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/standin/model"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/standin/workload"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/warden"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/wire"
)

func main() {
	os.Exit(run(os.Args[1:], os.Stdout, os.Stderr))
}

// options are the flags a scenario may read.
type options struct {
	// As is the Caller the scripted scenario signs for, as tenant/name.
	As string
	// Question is what ask asks; tour asks defaultQuestion.
	Question string
	// Out is the run directory for the Audit logs; empty means a new
	// timestamped one under runs/.
	Out string
	// audit is where this run's Audit records go.
	audit *auditSink
}

const defaultQuestion = "Can Tom approve invoices?"

// scenario is one named demo.
type scenario struct {
	name string
	run  func(ctx context.Context, stdout io.Writer, log *slog.Logger, opts options) error
}

// scenarios lists every scenario in tour order.
var scenarios = []scenario{
	{"tokens", runTokens},
	{"scripted", runScripted},
	{"ask", runAsk},
}

const usage = "usage: demo <tokens|scripted|tour> [--as tenant/name] [--out dir]\n       demo ask \"<question>\" [--as tenant/name] [--out dir]\n"

// run executes the subcommand and returns the exit code: 0 when the scenario
// ran (a 401 or 403 is a normal result), 1 when setup failed, 2 on bad usage.
func run(args []string, stdout, stderr io.Writer) int {
	if len(args) < 1 {
		io.WriteString(stderr, usage)
		return 2
	}
	fs := flag.NewFlagSet("demo", flag.ContinueOnError)
	fs.SetOutput(stderr)
	var opts options
	fs.StringVar(&opts.As, "as", "acme/alice", "the Caller to sign for, as tenant/name (scripted only)")
	fs.StringVar(&opts.Out, "out", "", "the directory for the Audit logs (default runs/<UTC timestamp>)")
	if err := fs.Parse(args[1:]); err != nil {
		io.WriteString(stderr, usage)
		return 2
	}
	if args[0] == "ask" && fs.NArg() > 0 {
		// The question may come before the flags, so parse the rest again.
		opts.Question = fs.Arg(0)
		if err := fs.Parse(fs.Args()[1:]); err != nil {
			io.WriteString(stderr, usage)
			return 2
		}
	}
	if fs.NArg() != 0 || (args[0] == "ask" && opts.Question == "") {
		io.WriteString(stderr, usage)
		return 2
	}
	if args[0] == "tour" {
		opts.Question = defaultQuestion
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
	sink, err := openAudit(opts.Out)
	if err != nil {
		log.Error("demo could not open the run directory", "err", err)
		return 1
	}
	defer sink.close()
	opts.audit = sink
	for _, s := range chosen {
		if s.name != "ask" || len(chosen) > 1 {
			// A lone ask prints only the Reply and its footer.
			fmt.Fprintf(stdout, "== %s\n", s.name)
		}
		if err := s.run(context.Background(), stdout, log, opts); err != nil {
			log.Error("demo could not run", "scenario", s.name, "err", err)
			return 1
		}
	}
	// The last stderr line names the run directory.
	log.Info("audit logs written", "dir", sink.dir)
	return 0
}

const (
	wardenAud = "spiffe://example.com/warden"
	wrongAud  = "spiffe://example.com/not-the-warden"
)

var (
	permissionAgent = spiffeid.RequireFromString("spiffe://example.com/permission-agent")
	unlistedAgent   = spiffeid.RequireFromString("spiffe://example.com/unlisted-agent")
)

// env is a running Warden with the pieces both scenarios share.
type env struct {
	source *workload.Source
	login  *login.Login
	url    string
	// audit takes the Agent's Audit records.
	audit io.Writer

	mu   sync.Mutex
	last warden.Decision
}

// lastDecision is the Decision the Warden made for the latest request.
func (e *env) lastDecision() warden.Decision {
	e.mu.Lock()
	defer e.mu.Unlock()
	return e.last
}

// setup starts a Warden on loopback that allowlists only the permission-agent.
// The returned func stops it.
func setup(log *slog.Logger, audit *auditSink) (*env, func(), error) {
	td, err := spiffeid.TrustDomainFromString("example.com")
	if err != nil {
		return nil, nil, err
	}
	source, err := workload.New(td)
	if err != nil {
		return nil, nil, err
	}
	lg, err := login.New(nil)
	if err != nil {
		return nil, nil, err
	}
	e := &env{source: source, login: lg, audit: audit.agent}
	w, err := warden.New(warden.Config{
		Audience:  wardenAud,
		Bundles:   source,
		Allowlist: []spiffeid.ID{permissionAgent},
		LoginKey:  lg.PublicKey(),
		Audit:     audit.warden,
		OnDecision: func(d warden.Decision) {
			e.mu.Lock()
			defer e.mu.Unlock()
			e.last = d
		},
	})
	if err != nil {
		return nil, nil, err
	}
	srv, err := w.ListenLoopback()
	if err != nil {
		return nil, nil, err
	}
	e.url = srv.URL
	log.Info("warden listening", "url", srv.URL)
	return e, func() { srv.Close() }, nil
}

// agentFor builds an Agent for the workload id that asks for audience aud.
func (e *env) agentFor(id spiffeid.ID, aud string) (*agent.Agent, error) {
	wl, err := e.source.Workload(id)
	if err != nil {
		return nil, err
	}
	return agent.New(agent.Config{WardenURL: e.url, Audience: aud, Source: wl, Audit: e.audit})
}

// runAsk asks the question through the permission-agent with the demo stand-in
// Model and prints the Reply. The step trace goes to the log.
func runAsk(ctx context.Context, stdout io.Writer, log *slog.Logger, opts options) error {
	e, stop, err := setup(log, opts.audit)
	if err != nil {
		return err
	}
	defer stop()
	m := model.NewDemo()
	defer m.Close()
	wl, err := e.source.Workload(permissionAgent)
	if err != nil {
		return err
	}
	a, err := agent.New(agent.Config{
		WardenURL: e.url, Audience: wardenAud, Source: wl, Audit: e.audit,
		Model: &agent.ModelConfig{BaseURL: m.URL, APIKey: "stand-in", Provider: "stand-in"},
	})
	if err != nil {
		return err
	}
	assertion, err := e.login.Sign(opts.As, wardenAud, permissionAgent.String())
	if err != nil {
		return err
	}
	reply, err := a.Ask(ctx, assertion, opts.Question)
	if err != nil {
		return err
	}
	opts.audit.trace(log, reply.CorrelationID)
	fmt.Fprintln(stdout, reply.Text)
	return nil
}

// runTokens makes three Lookups: allowed, wrong audience, not on the allowlist.
// It ignores --as.
func runTokens(ctx context.Context, stdout io.Writer, log *slog.Logger, opts options) error {
	e, stop, err := setup(log, opts.audit)
	if err != nil {
		return err
	}
	defer stop()

	req := wire.LookupRequest{Target: "acme/tom", Permission: "invoice:approve"}
	for _, c := range []struct {
		id  spiffeid.ID
		aud string
	}{
		{permissionAgent, wardenAud},
		{permissionAgent, wrongAud},
		{unlistedAgent, wardenAud},
	} {
		a, err := e.agentFor(c.id, c.aud)
		if err != nil {
			return err
		}
		assertion, err := e.login.Sign("acme/alice", wardenAud, c.id.String())
		if err != nil {
			return err
		}
		res, err := a.Lookup(ctx, assertion, req)
		if err != nil {
			return err
		}
		d := e.lastDecision()
		line := fmt.Sprintf("POST /lookup  agent=%s  aud=%s  -> %d  outcome=%s", c.id, c.aud, res.Status, d.Outcome)
		if d.Reason != "" {
			line += fmt.Sprintf("  reason=%s", d.Reason)
		}
		fmt.Fprintln(stdout, line)
	}
	return nil
}

// runScripted makes three Lookups through the permission-agent without a Model:
// the --as Caller asks about Tom, Bob asks about Tom, and the --as Caller
// reaches across Tenants.
func runScripted(ctx context.Context, stdout io.Writer, log *slog.Logger, opts options) error {
	e, stop, err := setup(log, opts.audit)
	if err != nil {
		return err
	}
	defer stop()
	a, err := e.agentFor(permissionAgent, wardenAud)
	if err != nil {
		return err
	}

	cross := wire.LookupRequest{Target: "globex/sam", Permission: "permission:read"}
	if strings.HasPrefix(opts.As, "globex/") {
		cross.Target = "acme/alice"
	}
	for _, c := range []struct {
		caller string
		req    wire.LookupRequest
	}{
		{opts.As, wire.LookupRequest{Target: "acme/tom", Permission: "invoice:approve"}},
		{"acme/bob", wire.LookupRequest{Target: "acme/tom", Permission: "invoice:approve"}},
		{opts.As, cross},
	} {
		assertion, err := e.login.Sign(c.caller, wardenAud, permissionAgent.String())
		if err != nil {
			return err
		}
		res, err := a.Lookup(ctx, assertion, c.req)
		if err != nil {
			return err
		}
		d := e.lastDecision()
		line := fmt.Sprintf("POST /lookup  caller=%s  target=%s  permission=%s  -> %d  outcome=%s",
			c.caller, c.req.Target, c.req.Permission, res.Status, d.Outcome)
		if res.Status == http.StatusOK {
			line += fmt.Sprintf("  holds=%t", res.Holds)
			if res.Role != "" {
				line += fmt.Sprintf("  role=%s", res.Role)
			}
		}
		if d.FailedCheck != "" {
			line += fmt.Sprintf("  failed_check=%s", d.FailedCheck)
		}
		if d.Reason != "" {
			line += fmt.Sprintf("  reason=%s", d.Reason)
		}
		fmt.Fprintln(stdout, line)
	}
	return nil
}
