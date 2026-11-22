// Command redact copies a Call-record JSONL file with secret-shaped strings
// replaced by a kind tag such as [REDACTED:bearer]. It never writes over its
// input and never prints matched text. See projects/ai-gateway/README.md.
package main

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"

	"github.com/travism26/harness-lab/projects/ai-gateway/internal/redact"
)

func main() { os.Exit(run(os.Args[1:], os.Stderr)) }

// run redacts args[0] into args[1] and returns the process exit code. The
// per-kind redaction counts go to stderr.
func run(args []string, stderr io.Writer) int {
	if len(args) != 2 {
		fmt.Fprintln(stderr, "usage: redact <input.jsonl> <output.jsonl>")
		return 2
	}
	in, out := args[0], args[1]
	if sameFile(in, out) {
		fmt.Fprintln(stderr, "redact: output must not be the input file")
		return 2
	}
	src, err := os.Open(in)
	if err != nil {
		fmt.Fprintf(stderr, "redact: %v\n", err)
		return 1
	}
	defer src.Close()
	dst, err := os.OpenFile(out, os.O_WRONLY|os.O_CREATE|os.O_TRUNC, 0o600)
	if err != nil {
		fmt.Fprintf(stderr, "redact: %v\n", err)
		return 1
	}
	counts, err := redact.Stream(src, dst)
	if cerr := dst.Close(); err == nil {
		err = cerr
	}
	if err != nil {
		fmt.Fprintf(stderr, "redact: %v\n", err)
		return 1
	}
	kinds := make([]string, 0, len(counts))
	total := 0
	for k, n := range counts {
		kinds = append(kinds, k)
		total += n
	}
	sort.Strings(kinds)
	for _, k := range kinds {
		fmt.Fprintf(stderr, "redacted %s: %d\n", k, counts[k])
	}
	fmt.Fprintf(stderr, "redacted total: %d\n", total)
	return 0
}

// sameFile reports whether a and b name one file, including through a link or
// a different spelling of the path. A path that does not exist yet is compared
// by its absolute form.
func sameFile(a, b string) bool {
	ia, errA := os.Stat(a)
	ib, errB := os.Stat(b)
	if errA == nil && errB == nil {
		return os.SameFile(ia, ib)
	}
	aa, errA := filepath.Abs(a)
	ab, errB := filepath.Abs(b)
	return errA == nil && errB == nil && aa == ab
}
