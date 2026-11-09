// Package wardenisolation implements trustlint rule R2: workloads stay
// separate. The Warden must not import the agent, the model client or the
// Broker, and the Broker (its module and its command) must not import the agent,
// the Warden, the model client or the Eval, tests
// included, directly or transitively. Its real configuration lives in
// projects/agent-identity/internal/trustlint/config.go.
//
// Transitive reach is computed with analysis facts: every package exports a
// reachFact recording which forbidden packages it imports, and by what chain.
package wardenisolation

import (
	"fmt"
	"go/ast"
	"slices"
	"sort"
	"strconv"
	"strings"

	"golang.org/x/tools/go/analysis"
)

// Config is a set of isolation rules.
type Config struct {
	Rules []Rule
}

// Rule names the packages of one workload and the packages they must not
// import. Name says who is isolated, for the message.
type Rule struct {
	Name      string
	Isolated  []string
	Forbidden []string
}

// forbidden is every package any rule forbids: the facts track them all, so a
// package's reach is the same whichever rule reads it.
func (c Config) forbidden() []string {
	var out []string
	for _, r := range c.Rules {
		for _, f := range r.Forbidden {
			if !slices.Contains(out, f) {
				out = append(out, f)
			}
		}
	}
	return out
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
		Doc:       "R2: the Warden must not import the agent, the model client or the Broker, and the Broker process must not import the agent, the Warden, the model client or the Eval, directly or transitively",
		FactTypes: []analysis.Fact{(*reachFact)(nil)},
		Run:       func(pass *analysis.Pass) (any, error) { return nil, run(pass, cfg) },
	}
}

func run(pass *analysis.Pass, cfg Config) error {
	self := strings.TrimSuffix(pass.Pkg.Path(), "_test")
	all := cfg.forbidden()
	var rules []Rule
	for _, r := range cfg.Rules {
		if underAny(self, r.Isolated) {
			rules = append(rules, r)
		}
	}

	own := map[string]string{}
	for _, f := range pass.Files {
		for _, spec := range f.Imports {
			path, err := strconv.Unquote(spec.Path.Value)
			if err != nil {
				continue
			}
			via := reach(pass, all, spec, path)
			keys := make([]string, 0, len(via))
			for k := range via {
				keys = append(keys, k)
			}
			sort.Strings(keys)
			for _, k := range keys {
				if _, seen := own[k]; !seen {
					own[k] = via[k]
				}
				for _, r := range rules {
					// Importing a package the rule forbids is one finding, not one
					// per package that package reaches.
					if !slices.Contains(r.Forbidden, k) || (k != path && underAny(path, r.Forbidden)) {
						continue
					}
					if k == path {
						pass.Reportf(spec.Pos(), "R2: %s may not import %s; %s must not depend on it", self, path, r.Name)
					} else {
						pass.Reportf(spec.Pos(), "R2: %s may not import %s, which reaches %s (%s)", self, path, k, via[k])
					}
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
func reach(pass *analysis.Pass, forbidden []string, spec *ast.ImportSpec, path string) map[string]string {
	out := map[string]string{}
	if underAny(path, forbidden) {
		out[path] = path
	}
	// A forbidden package is followed too: what it reaches is reached by every
	// importer, though a rule that forbids the package itself says only that.
	if imported := pass.TypesInfo.PkgNameOf(spec); imported != nil {
		var f reachFact
		if pass.ImportPackageFact(imported.Imported(), &f) {
			for _, e := range f.Via {
				if _, ok := out[e.Forbidden]; !ok {
					out[e.Forbidden] = path + " -> " + e.Chain
				}
			}
		}
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
