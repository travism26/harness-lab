// Command eval scores the Model client on the hand-written cases in
// projects/agent-identity/evals/cases.jsonl and prints a report. It reaches the
// Model through the Broker as model-eval, so it holds no provider key and reads
// neither a key variable nor .env. It needs a running Broker and spiffecli, so it
// never runs in check. Exit codes: 0 passed, 1 below the bar, 2 bad usage or no
// Workload API socket.
package main

import (
	"context"
	"flag"
	"fmt"
	"io"
	"net/url"
	"os"
	"os/signal"
	"syscall"

	"github.com/travism26/harness-lab/projects/agent-identity/internal/eval"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/workloadsrc"
)

const (
	usage = "usage: eval --broker-url URL --model ID [--runs N] [--min-accuracy F] [--cases FILE] [--spiffe-socket path]\n"
	// defaultSocket is model-eval's own socket in projects/agent-identity/spiffecli/workloads.toml.
	defaultSocket = "/tmp/agent-identity/model-eval.sock"
)

func main() {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	os.Exit(runWith(ctx, os.Args[1:], os.Stdout, os.Stderr, deps{}))
}

// svidSource is what model-eval's Workload API socket gives: its JWT-SVIDs.
type svidSource interface {
	eval.SVIDSource
	Close() error
}

var _ svidSource = workloadsrc.Source{}

// deps are the outside things the command reaches, so tests can swap them. The
// zero value means the real ones.
type deps struct {
	// openJWT opens a JWT source on a Workload API socket. Nil means go-spiffe's.
	openJWT func(ctx context.Context, socket string) (svidSource, error)
}

func (d deps) withDefaults() deps {
	if d.openJWT == nil {
		d.openJWT = workloadsrc.OpenAs[svidSource]
	}
	return d
}

// runWith is the command.
func runWith(ctx context.Context, args []string, stdout, stderr io.Writer, d deps) int {
	d = d.withDefaults()
	fs := flag.NewFlagSet("eval", flag.ContinueOnError)
	fs.SetOutput(stderr)
	runs := fs.Int("runs", 3, "runs per case")
	minAcc := fs.Float64("min-accuracy", 0.9, "accuracy every counted category must reach; 0 is report-only")
	modelID := fs.String("model", "", "the model id to name; the Broker checks it against model-eval's Pin (required)")
	cases := fs.String("cases", "evals/cases.jsonl", "the cases file")
	brokerURL := fs.String("broker-url", "", "the Broker's base URL (required)")
	socket := fs.String("spiffe-socket", defaultSocket, "model-eval's spiffecli Workload API socket")
	if err := fs.Parse(args); err != nil || fs.NArg() != 0 || *runs < 1 || *minAcc < 0 || *minAcc > 1 {
		fmt.Fprint(stderr, usage)
		return 2
	}
	if u, err := url.Parse(*brokerURL); *brokerURL == "" || err != nil || u.Host == "" {
		fmt.Fprintf(stderr, "eval: --broker-url is required, such as http://127.0.0.1:8787\n%s", usage)
		return 2
	}
	if *modelID == "" {
		fmt.Fprintf(stderr, "eval: --model is required: the Broker's Pin for model-eval lists several models, so none is assumed\n%s", usage)
		return 2
	}

	f, err := os.Open(*cases)
	if err != nil {
		fmt.Fprintf(stderr, "eval: %v\n", err)
		return 2
	}
	defer f.Close()
	list, err := eval.LoadCases(f)
	if err != nil {
		fmt.Fprintf(stderr, "%v\n", err)
		return 2
	}

	src, err := d.openJWT(ctx, *socket)
	if err != nil {
		fmt.Fprintf(stderr, "eval: could not reach the Workload API socket %s: %v\n", *socket, err)
		fmt.Fprintln(stderr, "eval: "+workloadsrc.StartHint)
		return 2
	}
	defer src.Close()
	client, err := eval.NewClient(eval.ClientConfig{BrokerURL: *brokerURL, Model: *modelID, Source: src})
	if err != nil {
		fmt.Fprintf(stderr, "eval: %v\n", err)
		return 2
	}
	fmt.Fprintf(stderr, "eval: asking the Broker at %s for model %s\n", *brokerURL, *modelID)
	rep := eval.Run(ctx, client, list, *runs)
	rep.Write(stdout, *minAcc)
	return rep.ExitCode(*minAcc)
}
