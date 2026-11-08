// Command eval scores the live Model client on the hand-written cases in
// projects/agent-identity/evals/cases.jsonl and prints a report. It needs a
// provider key, so it never runs in check. Exit codes: 0 passed, 1 below the
// bar, 2 bad usage or no key.
package main

import (
	"context"
	"flag"
	"fmt"
	"io"
	"os"

	"github.com/travism26/harness-lab/projects/agent-identity/internal/eval"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/provider"
)

func main() {
	os.Exit(run(os.Args[1:], os.Stdout, os.Stderr, os.Getenv))
}

func run(args []string, stdout, stderr io.Writer, getenv func(string) string) int {
	fs := flag.NewFlagSet("eval", flag.ContinueOnError)
	fs.SetOutput(stderr)
	runs := fs.Int("runs", 3, "runs per case")
	minAcc := fs.Float64("min-accuracy", 0.9, "accuracy every counted category must reach; 0 is report-only")
	modelID := fs.String("model", "", "model id (default by provider)")
	providerName := fs.String("provider", "", "anthropic or openrouter (default: anthropic if its key is set, else openrouter)")
	cases := fs.String("cases", "evals/cases.jsonl", "the cases file")
	baseURL := fs.String("base-url", "", "override the provider's API root (for tests against the stand-in Model)")
	envFile := fs.String("env-file", provider.DotEnvPath, "file of KEY=VALUE provider keys; the process environment overrides it; a missing file is fine")
	if err := fs.Parse(args); err != nil || fs.NArg() != 0 || *runs < 1 || *minAcc < 0 || *minAcc > 1 {
		fmt.Fprintln(stderr, "usage: eval [--runs N] [--min-accuracy F] [--model ID] [--provider anthropic|openrouter] [--cases FILE] [--env-file FILE]")
		return 2
	}

	// The shared selection rule, fed the process environment over the .env file.
	getenv, err := provider.WithDotEnv(*envFile, getenv)
	if err != nil {
		fmt.Fprintf(stderr, "eval: %v\n", err)
		return 2
	}
	choice, err := provider.Select(*providerName, getenv)
	if err != nil {
		fmt.Fprintf(stderr, "eval: %v\n", err)
		return 2
	}
	name, key := choice.Name, choice.Key

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
	client, usedModel, err := eval.NewClient(eval.ClientConfig{Provider: name, Model: *modelID, BaseURL: *baseURL, APIKey: key})
	if err != nil {
		fmt.Fprintf(stderr, "eval: %v\n", err)
		return 2
	}
	fmt.Fprintf(stderr, "eval: provider %s, model %s\n", name, usedModel)
	rep := eval.Run(context.Background(), client, name, list, *runs)
	rep.Write(stdout, usedModel, *minAcc)
	return rep.ExitCode(*minAcc)
}
