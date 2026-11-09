// Command trustlint runs the trust-boundary analyzers R1–R5 over the packages
// it is given. The analyzers are configured in
// projects/agent-identity/internal/trustlint/config.go.
package main

import (
	"golang.org/x/tools/go/analysis/multichecker"

	"github.com/travism26/harness-lab/projects/agent-identity/internal/trustlint"
)

func main() { multichecker.Main(trustlint.Analyzers()...) }
