// Package modelisolation implements trustlint rule R1: only the allowed
// packages may import the model client. Its real configuration lives in
// projects/agent-identity/internal/trustlint/config.go.
package modelisolation

import (
	"strconv"
	"strings"

	"golang.org/x/tools/go/analysis"
)

// Config names the guarded model-client package and the packages allowed to
// import it.
type Config struct {
	ModelClient string
	Allowed     []string
}

// New returns the R1 analyzer for cfg.
func New(cfg Config) *analysis.Analyzer {
	return &analysis.Analyzer{
		Name: "modelisolation",
		Doc:  "R1: only the allowed packages may import the model client",
		Run:  func(pass *analysis.Pass) (any, error) { return nil, run(pass, cfg) },
	}
}

func run(pass *analysis.Pass, cfg Config) error {
	// An external test package is path_test, and its test main is path.test.
	self := strings.TrimSuffix(strings.TrimSuffix(pass.Pkg.Path(), ".test"), "_test")
	if isUnder(self, cfg.ModelClient) {
		return nil
	}
	for _, a := range cfg.Allowed {
		if self == a {
			return nil
		}
	}
	for _, f := range pass.Files {
		for _, spec := range f.Imports {
			path, err := strconv.Unquote(spec.Path.Value)
			if err != nil || !isUnder(path, cfg.ModelClient) {
				continue
			}
			pass.Reportf(spec.Pos(), "R1: %s may not import %s; only %s may",
				self, path, strings.Join(cfg.Allowed, " and "))
		}
	}
	return nil
}

func isUnder(path, root string) bool {
	return path == root || strings.HasPrefix(path, root+"/")
}
