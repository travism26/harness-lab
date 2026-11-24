// Command report prints a summary of a Call-record JSONL file: record count,
// sessions, token totals, a list-price cost estimate and latency percentiles.
// It never prints a request or response body. See projects/ai-gateway/README.md.
package main

import (
	"fmt"
	"io"
	"os"

	"github.com/travism26/harness-lab/projects/ai-gateway/internal/report"
)

func main() { os.Exit(run(os.Args[1:], os.Stdout, os.Stderr)) }

// run summarises args[0] to stdout and returns the process exit code.
func run(args []string, stdout, stderr io.Writer) int {
	if len(args) != 1 {
		fmt.Fprintln(stderr, "usage: report <calls.jsonl>")
		return 2
	}
	f, err := os.Open(args[0])
	if err != nil {
		fmt.Fprintf(stderr, "report: %v\n", err)
		return 1
	}
	defer f.Close()
	s, err := report.Summarize(f)
	if err != nil {
		fmt.Fprintf(stderr, "report: %v\n", err)
		return 1
	}
	report.Write(stdout, s)
	return 0
}
