// Package noinsecureparse implements trustlint rule R4: functions that skip
// token signature verification may be used only in _test.go files. Its real
// configuration lives in projects/agent-identity/internal/trustlint/config.go.
package noinsecureparse

import (
	"go/types"
	"slices"
	"strings"

	"golang.org/x/tools/go/analysis"
)

// Config lists the forbidden functions as types.Func.FullName strings.
type Config struct {
	Funcs []string
}

// New returns the R4 analyzer for cfg.
func New(cfg Config) *analysis.Analyzer {
	return &analysis.Analyzer{
		Name: "noinsecureparse",
		Doc:  "R4: signature-skipping parse functions may be used only in _test.go files",
		Run:  func(pass *analysis.Pass) (any, error) { return nil, run(pass, cfg) },
	}
}

func run(pass *analysis.Pass, cfg Config) error {
	for id, obj := range pass.TypesInfo.Uses {
		fn, ok := obj.(*types.Func)
		if !ok || !slices.Contains(cfg.Funcs, fn.FullName()) {
			continue
		}
		if strings.HasSuffix(pass.Fset.Position(id.Pos()).Filename, "_test.go") {
			continue
		}
		pass.Reportf(id.Pos(), "R4: %s skips signature verification; use it only in _test.go", fn.FullName())
	}
	return nil
}
