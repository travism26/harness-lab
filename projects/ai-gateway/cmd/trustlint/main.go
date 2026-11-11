// Command trustlint runs the Project's analyzers over the packages it is given.
// The analyzers are listed in projects/ai-gateway/internal/secrettype.
package main

import (
	"golang.org/x/tools/go/analysis/multichecker"

	"github.com/travism26/harness-lab/projects/ai-gateway/internal/secrettype"
)

func main() { multichecker.Main(secrettype.Analyzer) }
