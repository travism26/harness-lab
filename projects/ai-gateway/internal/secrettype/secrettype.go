// Package secrettype holds the analyzer that keeps a Forwarded credential out
// of the Call record and the logs. It reports a struct type declared in a
// package named callrecord that has the credential type anywhere inside it,
// and a value that is or contains the credential type passed to a log,
// log/slog or fmt print or format function.
//
// The idea comes from projects/agent-identity/internal/trustlint/nosecretlogs/nosecretlogs.go,
// which this package does not import.
package secrettype

import (
	"go/ast"
	"go/types"
	"path"
	"slices"
	"strings"

	"golang.org/x/tools/go/analysis"
	"golang.org/x/tools/go/analysis/passes/inspect"
	"golang.org/x/tools/go/ast/inspector"
	"golang.org/x/tools/go/types/typeutil"
)

const (
	defaultCredential = "github.com/travism26/harness-lab/projects/ai-gateway/internal/credential.Credential"
	recordPackage     = "callrecord"
)

var fmtSinks = []string{
	"Print", "Printf", "Println", "Fprint", "Fprintf", "Fprintln",
	"Sprint", "Sprintf", "Sprintln", "Errorf", "Append", "Appendf", "Appendln",
}

// Analyzer is the secret-type analyzer. Its -credential flag names the
// credential types as comma-separated "importpath.TypeName"; tests set it.
var Analyzer = &analysis.Analyzer{
	Name:     "secrettype",
	Doc:      "reports the credential type in a Call record type or passed to log, log/slog or fmt print and format functions",
	Requires: []*analysis.Analyzer{inspect.Analyzer},
	Run:      run,
}

var credentialFlag string

func init() {
	Analyzer.Flags.StringVar(&credentialFlag, "credential", defaultCredential, "comma-separated credential types, importpath.TypeName")
}

func run(pass *analysis.Pass) (any, error) {
	tokens := strings.Split(credentialFlag, ",")

	if path.Base(pass.Pkg.Path()) == recordPackage {
		for _, name := range pass.Pkg.Scope().Names() {
			tn, ok := pass.Pkg.Scope().Lookup(name).(*types.TypeName)
			if !ok {
				continue
			}
			if tok := contains(tn.Type(), tokens, map[*types.Named]bool{}); tok != "" {
				pass.Reportf(tn.Pos(), "Call record type %s contains credential type %s", name, tok)
			}
		}
	}

	insp := pass.ResultOf[inspect.Analyzer].(*inspector.Inspector)
	insp.Preorder([]ast.Node{(*ast.CallExpr)(nil)}, func(n ast.Node) {
		call := n.(*ast.CallExpr)
		fn, ok := typeutil.Callee(pass.TypesInfo, call).(*types.Func)
		if !ok || !isSink(fn) {
			return
		}
		args := slices.Clone(call.Args)
		if call.Ellipsis.IsValid() && len(args) > 0 {
			if lit, ok := ast.Unparen(args[len(args)-1]).(*ast.CompositeLit); ok {
				for _, elt := range lit.Elts {
					if kv, ok := elt.(*ast.KeyValueExpr); ok {
						elt = kv.Value
					}
					args = append(args, elt)
				}
			}
		}
		for _, arg := range args {
			t := pass.TypesInfo.TypeOf(arg)
			if t == nil {
				continue
			}
			if tok := contains(t, tokens, map[*types.Named]bool{}); tok != "" {
				pass.Reportf(arg.Pos(), "value containing credential type %s passed to %s", tok, fn.FullName())
			}
		}
	})
	return nil, nil
}

func isSink(fn *types.Func) bool {
	pkg := fn.Pkg()
	if pkg == nil {
		return false
	}
	switch pkg.Path() {
	case "log", "log/slog":
		return true
	case "fmt":
		return slices.Contains(fmtSinks, fn.Name())
	}
	return false
}

// contains walks t for a credential type and returns its name, or "". It stops
// at interfaces, funcs, chans and basics.
func contains(t types.Type, tokens []string, seen map[*types.Named]bool) string {
	switch t := types.Unalias(t).(type) {
	case *types.Pointer:
		return contains(t.Elem(), tokens, seen)
	case *types.Named:
		if t.Obj().Pkg() != nil {
			if name := t.Obj().Pkg().Path() + "." + t.Obj().Name(); slices.Contains(tokens, name) {
				return name
			}
		}
		if seen[t] {
			return ""
		}
		seen[t] = true
		return contains(t.Underlying(), tokens, seen)
	case *types.Struct:
		for f := range t.Fields() {
			if name := contains(f.Type(), tokens, seen); name != "" {
				return name
			}
		}
	case *types.Slice:
		return contains(t.Elem(), tokens, seen)
	case *types.Array:
		return contains(t.Elem(), tokens, seen)
	case *types.Map:
		if name := contains(t.Key(), tokens, seen); name != "" {
			return name
		}
		return contains(t.Elem(), tokens, seen)
	}
	return ""
}
