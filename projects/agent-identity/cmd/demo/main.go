// Command demo runs the Agent identity scenarios against a real Warden on
// loopback and prints what happened.
package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"os"
	"slices"
	"strings"
	"sync"

	"github.com/spiffe/go-spiffe/v2/spiffeid"

	"github.com/travism26/harness-lab/projects/agent-identity/internal/agent"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/login"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/provider"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/standin/model"
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
	// Live sends the Model call to a live provider; Model and Provider refine it.
	Live            bool
	Model, Provider string
	// SpiffeSocket is the permission-agent's spiffecli socket; empty means the
	// in-process stand-in. SpiffeSocketWarden defaults beside it. SpiffeSocketOther
	// is the unlisted-agent's, for the 403 in tokens.
	SpiffeSocket, SpiffeSocketWarden, SpiffeSocketOther string

	// audit is where this run's Audit records go.
	audit *auditSink
	// ids is where this run gets JWT-SVIDs and the Warden's bundle.
	ids identities
	// modelCfg is the live Model's config, nil for the stand-in.
	modelCfg *agent.ModelConfig
}

const defaultQuestion = "Can Tom approve invoices?"

// scenario is one named demo.
type scenario struct {
	name string
	// usesModel marks a scenario that calls the Model, so --live applies.
	usesModel bool
	run       func(ctx context.Context, stdout io.Writer, log *slog.Logger, opts options) error
}

// scenarios lists every scenario in tour order.
var scenarios = []scenario{
	{"tokens", false, runTokens},
	{"scripted", false, runScripted},
	{"ask", true, runAsk},
}

const usage = "usage: demo <tokens|scripted|tour> [--as tenant/name] [--out dir] [live flags]\n       demo ask \"<question>\" [--as tenant/name] [--out dir] [live flags]\n" +
	"live flags: [--live [--model id] [--provider anthropic|openrouter]] [--spiffe-socket path [--spiffe-socket-warden path] [--spiffe-socket-other path]]\n"

// run executes the subcommand and returns the exit code: 0 when the scenario
// ran (a 401 or 403 is a normal result), 1 when setup failed, 2 on bad usage.
func run(args []string, stdout, stderr io.Writer) int {
	return runWith(args, stdout, stderr, deps{})
}

// runWith is run with its outside dependencies given.
func runWith(args []string, stdout, stderr io.Writer, d deps) int {
	d = d.withDefaults()
	if len(args) < 1 {
		io.WriteString(stderr, usage)
		return 2
	}
	fs := flag.NewFlagSet("demo", flag.ContinueOnError)
	fs.SetOutput(stderr)
	var opts options
	fs.StringVar(&opts.As, "as", "acme/alice", "the Caller to sign for, as tenant/name (scripted only)")
	fs.StringVar(&opts.Out, "out", "", "the directory for the Audit logs (default runs/<UTC timestamp>)")
	fs.BoolVar(&opts.Live, "live", false, "send the Model call to a live provider (ask)")
	fs.StringVar(&opts.Model, "model", "", "with --live, the model id (default by provider)")
	fs.StringVar(&opts.Provider, "provider", "", "with --live, anthropic or openrouter (default: anthropic if its key is set, else openrouter)")
	fs.StringVar(&opts.SpiffeSocket, "spiffe-socket", "", "use the spiffecli Workload API on this socket (the permission-agent's)")
	fs.StringVar(&opts.SpiffeSocketWarden, "spiffe-socket-warden", "", "with --spiffe-socket, the Warden's socket (default warden.sock beside it)")
	fs.StringVar(&opts.SpiffeSocketOther, "spiffe-socket-other", "", "with --spiffe-socket, the unlisted-agent's socket, for the 403 in tokens")
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
	// Every choice that can fail is made here, before the first request.
	if opts.Live && slices.ContainsFunc(chosen, func(s scenario) bool { return s.usesModel }) {
		getenv := d.getenv
		if d.envFile != "" {
			var err error
			if getenv, err = provider.WithDotEnv(d.envFile, d.getenv); err != nil {
				fmt.Fprintf(stderr, "demo: --live: %v\n", err)
				return 2
			}
		}
		choice, err := provider.Select(opts.Provider, getenv)
		if err != nil {
			fmt.Fprintf(stderr, "demo: --live: %v\n", err)
			return 2
		}
		mc := &agent.ModelConfig{BaseURL: choice.BaseURL, APIKey: choice.Key, Model: opts.Model, Provider: choice.Name, BearerAuth: choice.Name == "openrouter"}
		if d.modelBaseURL != "" {
			mc.BaseURL = d.modelBaseURL
		}
		opts.modelCfg = mc
		used := opts.Model
		if used == "" {
			used = agent.DefaultModel(choice.Name)
		}
		fmt.Fprintf(stderr, "demo: live Model: provider %s, model %s\n", choice.Name, used)
	}
	if opts.SpiffeSocket != "" {
		ids, err := openSpiffe(context.Background(), d, opts.SpiffeSocket, opts.SpiffeSocketWarden, opts.SpiffeSocketOther)
		if err != nil {
			log.Error("demo could not reach the Workload API", "err", err)
			return 1
		}
		opts.ids = ids
	} else {
		ids, err := newStandInIdentities()
		if err != nil {
			log.Error("demo could not start", "err", err)
			return 1
		}
		opts.ids = ids
	}
	defer opts.ids.Close()
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
	ids   identities
	login *login.Login
	url   string
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
func setup(log *slog.Logger, opts options) (*env, func(), error) {
	audit := opts.audit
	lg, err := login.New(nil)
	if err != nil {
		return nil, nil, err
	}
	e := &env{ids: opts.ids, login: lg, audit: audit.agent}
	w, err := warden.New(warden.Config{
		Audience:  wardenAud,
		Bundles:   opts.ids.Bundles(),
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
	wl, err := e.ids.Workload(id)
	if err != nil {
		return nil, err
	}
	return agent.New(agent.Config{WardenURL: e.url, Audience: aud, Source: wl, Audit: e.audit})
}

// runAsk asks the question through the permission-agent with the demo stand-in
// Model and prints the Reply. The step trace goes to the log.
func runAsk(ctx context.Context, stdout io.Writer, log *slog.Logger, opts options) error {
	e, stop, err := setup(log, opts)
	if err != nil {
		return err
	}
	defer stop()
	mc := opts.modelCfg
	if mc == nil {
		m := model.NewDemo()
		defer m.Close()
		mc = &agent.ModelConfig{BaseURL: m.URL, APIKey: "stand-in", Provider: "stand-in"}
	}
	wl, err := e.ids.Workload(permissionAgent)
	if err != nil {
		return err
	}
	a, err := agent.New(agent.Config{
		WardenURL: e.url, Audience: wardenAud, Source: wl, Audit: e.audit, Model: mc,
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
	e, stop, err := setup(log, opts)
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
		if errors.Is(err, errNoSource) {
			fmt.Fprintf(stdout, "note: skipped the %s line: no --spiffe-socket-other given for that workload\n", c.id)
			continue
		}
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
	e, stop, err := setup(log, opts)
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
