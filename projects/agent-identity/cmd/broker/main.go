// Command broker runs the Broker as its own process: the one workload that
// holds a Model provider key. It chooses its provider once at start-up
// (ADR 0003), reads the key from the environment or .env, takes its trust
// bundle from its own Workload API socket and serves POST /v1/messages on
// loopback until interrupted. The demo reaches it with `--live --broker-url`.
// See projects/agent-identity/docs/adr/0004-the-provider-key-lives-only-in-the-broker.md.
package main

import (
	"context"
	"flag"
	"fmt"
	"io"
	"net"
	"os"
	"os/signal"
	"path/filepath"
	"syscall"

	"github.com/spiffe/go-spiffe/v2/bundle/jwtbundle"
	"github.com/spiffe/go-spiffe/v2/spiffeid"

	"github.com/travism26/harness-lab/projects/agent-identity/internal/broker"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/pin"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/provider"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/rundir"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/workloadsrc"
)

const (
	usage = "usage: broker [--provider anthropic|openrouter] [--out dir] [--spiffe-socket path] [--addr 127.0.0.1:8787]\n"
	// defaultSocket is the Broker's own socket in projects/agent-identity/spiffecli/workloads.toml.
	defaultSocket = "/tmp/agent-identity/model-broker.sock"
	// defaultAddr is where the Broker listens, so the demo's --broker-url is
	// the same on every run.
	defaultAddr = "127.0.0.1:8787"
)

func main() {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	os.Exit(run(ctx, os.Args[1:], os.Stdout, os.Stderr, deps{}))
}

// bundleSource is what the Broker's Workload API socket gives it: the trust
// bundle it verifies JWT-SVIDs with.
type bundleSource interface {
	jwtbundle.Source
	Close() error
}

var _ bundleSource = workloadsrc.Source{}

// deps are the outside things the command reaches, so tests can swap them. The
// zero value means the real ones.
type deps struct {
	// getenv reads provider keys. Nil means os.Getenv, with .env beneath it.
	getenv func(string) string
	// envFile is a .env file the keys fall back to. Empty means none; the real
	// run (nil getenv) uses broker.DotEnvPath.
	envFile string
	// openBundles opens the Workload API socket. Nil means go-spiffe's.
	openBundles func(ctx context.Context, socket string) (bundleSource, error)
	// upstreamURL, if set, replaces the provider's API root, so a test can
	// point the Broker at the stand-in Model.
	upstreamURL string
}

func (d deps) withDefaults() deps {
	if d.getenv == nil {
		d.getenv = os.Getenv
		d.envFile = broker.DotEnvPath
	}
	if d.openBundles == nil {
		d.openBundles = workloadsrc.OpenAs[bundleSource]
	}
	return d
}

// run starts the Broker and serves until ctx ends. It returns 0 on a clean
// stop, 1 when start-up failed (a missing key, an unreachable socket) and 2 on
// bad usage. Nothing is served and no run directory is made before the
// provider's key is found.
func run(ctx context.Context, args []string, stdout, stderr io.Writer, d deps) int {
	d = d.withDefaults()
	fs := flag.NewFlagSet("broker", flag.ContinueOnError)
	fs.SetOutput(stderr)
	providerName := fs.String("provider", "", "anthropic or openrouter (default: anthropic if its key is set, else openrouter)")
	out := fs.String("out", "", "the directory for broker.audit.jsonl (default runs/<UTC timestamp>); give the demo the same one")
	socket := fs.String("spiffe-socket", defaultSocket, "the Broker's own spiffecli Workload API socket")
	addr := fs.String("addr", defaultAddr, "the loopback address to listen on")
	if err := fs.Parse(args); err != nil || fs.NArg() != 0 {
		io.WriteString(stderr, usage)
		return 2
	}
	if _, ok := provider.Providers[*providerName]; *providerName != "" && !ok {
		fmt.Fprintf(stderr, "broker: unknown provider %q (anthropic or openrouter)\n%s", *providerName, usage)
		return 2
	}
	if !loopback(*addr) {
		fmt.Fprintf(stderr, "broker: --addr %q is not a loopback address; the Broker listens on loopback only\n", *addr)
		return 2
	}

	// The Broker alone reads .env. The provider is chosen once, here.
	getenv := d.getenv
	if d.envFile != "" {
		var err error
		if getenv, err = broker.WithDotEnv(d.envFile, d.getenv); err != nil {
			fmt.Fprintf(stderr, "broker: %v\n", err)
			return 1
		}
	}
	fmt.Fprintf(stderr, "broker: provider %s\n", broker.Choose(*providerName, getenv))
	choice, err := broker.Select(*providerName, getenv)
	if err != nil {
		fmt.Fprintf(stderr, "broker: not serving: %v\n", err)
		return 1
	}

	bundles, err := d.openBundles(ctx, *socket)
	if err != nil {
		fmt.Fprintf(stderr, "broker: could not reach the Workload API socket %s: %v\n", *socket, err)
		fmt.Fprintln(stderr, "broker: "+workloadsrc.StartHint)
		return 1
	}
	defer bundles.Close()

	dir, err := rundir.Make(*out, "runs")
	if err != nil {
		fmt.Fprintf(stderr, "broker: could not make the run directory: %v\n", err)
		return 1
	}
	logPath := filepath.Join(dir, "broker.audit.jsonl")
	logFile, err := os.OpenFile(logPath, os.O_WRONLY|os.O_CREATE|os.O_TRUNC, 0o644)
	if err != nil {
		fmt.Fprintf(stderr, "broker: could not open the Audit log: %v\n", err)
		return 1
	}
	defer logFile.Close()

	b, err := broker.New(broker.Config{
		Audience:    broker.ID.String(),
		Bundles:     bundles,
		Provider:    choice.Provider,
		Key:         choice.Key,
		UpstreamURL: d.upstreamURL,
		Audit:       logFile,
		// The Agent may use its default model; the Eval may use any in its sweep.
		Pins: map[spiffeid.ID]pin.Pin{broker.PermissionAgent: pin.Agent(), broker.ModelEval: pin.ModelEval()},
	})
	if err != nil {
		fmt.Fprintf(stderr, "broker: %v\n", err)
		return 1
	}
	srv, err := b.Listen(*addr)
	if err != nil {
		fmt.Fprintf(stderr, "broker: %v\n", err)
		return 1
	}
	defer srv.Close()
	fmt.Fprintf(stderr, "broker: Audit log %s\n", logPath)
	fmt.Fprintf(stderr, "broker: listening on %s (demo: --live --broker-url %s --out %s)\n", srv.URL, srv.URL, dir)
	<-ctx.Done()
	return 0
}

// loopback reports whether addr is a host:port on the loopback interface.
func loopback(addr string) bool {
	host, _, err := net.SplitHostPort(addr)
	if err != nil {
		return false
	}
	if host == "localhost" {
		return true
	}
	ip := net.ParseIP(host)
	return ip != nil && ip.IsLoopback()
}
