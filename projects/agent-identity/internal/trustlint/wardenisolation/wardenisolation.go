// Package wardenisolation implements trustlint rule R2: the Warden must not
// import the agent or the model client, tests included, directly or
// transitively. Its real configuration lives in
// projects/agent-identity/internal/trustlint/config.go.
//
// Transitive reach is computed with analysis facts: every package exports a
// reachFact recording which forbidden packages it imports, and by what chain.
package wardenisolation

import (
	"fmt"
	"go/ast"
	"sort"
	"strconv"
	"strings"

	"golang.org/x/tools/go/analysis"
)

// Config names the Warden packages and the packages they must not import.
type Config struct {
	Warden    []string
	Forbidden []string
}

// reachFact records the forbidden packages a package imports, directly or
// transitively. Via holds one edge per forbidden package, sorted by Forbidden.
// It is a sorted slice rather than a map because gob encodes maps in random
// order and the analysis checker rejects facts whose encoding is nondeterministic.
type reachFact struct{ Via []reachEdge }

// reachEdge maps a forbidden package path to the import chain that reaches it,
// e.g. "a/helper -> a/agent".
type reachEdge struct{ Forbidden, Chain string }

func (*reachFact) AFact() {}

func (f *reachFact) String() string {
	parts := make([]string, len(f.Via))
	for i, e := range f.Via {
		parts[i] = fmt.Sprintf("%s via %s", e.Forbidden, e.Chain)
	}
	return "reaches " + strings.Join(parts, ", ")
}

// New returns the R2 analyzer for cfg.
func New(cfg Config) *analysis.Analyzer {
	return &analysis.Analyzer{
		Name:      "wardenisolation",
		Doc:       "R2: the Warden must not import the agent or the model client, directly or transitively",
		FactTypes: []analysis.Fact{(*reachFact)(nil)},
		Run:       func(pass *analysis.Pass) (any, error) { return nil, run(pass, cfg) },
	}
}

func run(pass *analysis.Pass, cfg Config) error {
	self := strings.TrimSuffix(pass.Pkg.Path(), "_test")
	isWarden := underAny(self, cfg.Warden)

	own := map[string]string{}
	for _, f := range pass.Files {
		for _, spec := range f.Imports {
			path, err := strconv.Unquote(spec.Path.Value)
			if err != nil {
				continue
			}
			via := reach(pass, cfg, spec, path)
			keys := make([]string, 0, len(via))
			for k := range via {
				keys = append(keys, k)
			}
			sort.Strings(keys)
			for _, k := range keys {
				if _, seen := own[k]; !seen {
					own[k] = via[k]
				}
				if !isWarden {
					continue
				}
				if k == path {
					pass.Reportf(spec.Pos(), "R2: %s may not import %s; the Warden must not depend on the agent or the model client", self, path)
				} else {
					pass.Reportf(spec.Pos(), "R2: %s may not import %s, which reaches %s (%s)", self, path, k, via[k])
				}
			}
		}
	}
	// A main package or an external test package cannot be imported, so its
	// reach is never needed downstream.
	if len(own) > 0 && pass.Pkg.Name() != "main" && !strings.HasSuffix(pass.Pkg.Path(), "_test") {
		fact := &reachFact{Via: make([]reachEdge, 0, len(own))}
		for k, chain := range own {
			fact.Via = append(fact.Via, reachEdge{k, chain})
		}
		sort.Slice(fact.Via, func(i, j int) bool { return fact.Via[i].Forbidden < fact.Via[j].Forbidden })
		pass.ExportPackageFact(fact)
	}
	return nil
}

// reach returns the forbidden packages that importing path (at spec) reaches,
// keyed by forbidden path, with the import chain starting at path.
func reach(pass *analysis.Pass, cfg Config, spec *ast.ImportSpec, path string) map[string]string {
	if underAny(path, cfg.Forbidden) {
		return map[string]string{path: path}
	}
	imported := pass.TypesInfo.PkgNameOf(spec)
	if imported == nil {
		return nil
	}
	var f reachFact
	if !pass.ImportPackageFact(imported.Imported(), &f) {
		return nil
	}
	out := make(map[string]string, len(f.Via))
	for _, e := range f.Via {
		out[e.Forbidden] = path + " -> " + e.Chain
	}
	return out
}

func underAny(path string, roots []string) bool {
	for _, r := range roots {
		if path == r || strings.HasPrefix(path, r+"/") {
			return true
		}
	}
	return false
}
