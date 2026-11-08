// Package wardenisolation implements trustlint rule R2: the Warden must not
// import the agent or the model client, tests included. Its real configuration
// lives in projects/agent-identity/internal/trustlint/config.go.
package wardenisolation

import (
	"strconv"
	"strings"

	"golang.org/x/tools/go/analysis"
)

// Config names the Warden packages and the packages they must not import.
type Config struct {
	Warden    []string
	Forbidden []string
}

// New returns the R2 analyzer for cfg.
func New(cfg Config) *analysis.Analyzer {
	return &analysis.Analyzer{
		Name: "wardenisolation",
		Doc:  "R2: the Warden must not import the agent or the model client",
		Run:  func(pass *analysis.Pass) (any, error) { return nil, run(pass, cfg) },
	}
}

func run(pass *analysis.Pass, cfg Config) error {
	self := strings.TrimSuffix(pass.Pkg.Path(), "_test")
	if !underAny(self, cfg.Warden) {
		return nil
	}
	for _, f := range pass.Files {
		for _, spec := range f.Imports {
			path, err := strconv.Unquote(spec.Path.Value)
			if err != nil || !underAny(path, cfg.Forbidden) {
				continue
			}
			pass.Reportf(spec.Pos(), "R2: %s may not import %s; the Warden must not depend on the agent or the model client", self, path)
		}
	}
	return nil
}

func underAny(path string, roots []string) bool {
	for _, r := range roots {
		if path == r || strings.HasPrefix(path, r+"/") {
			return true
		}
	}
	return false
}
