// Package nosecretlogs implements trustlint rule R3: token-typed values must
// not reach logging or printing sinks. Its real configuration lives in
// projects/agent-identity/internal/trustlint/config.go.
//
// Sinks are the log and log/slog packages plus fmt.Print*, fmt.Fprint*,
// fmt.Sprint*, fmt.Errorf and fmt.Append*: a token formatted into a string or
// error is a leak once that value is logged. A token nested inside a struct,
// slice, array, map or pointer argument counts. Elements of a composite
// literal spread with "..." are checked; values appended into a []any
// variable and then spread are NOT tracked.
package nosecretlogs

import (
	"go/ast"
	"go/types"
	"slices"

	"golang.org/x/tools/go/analysis"
	"golang.org/x/tools/go/analysis/passes/inspect"
	"golang.org/x/tools/go/ast/inspector"
	"golang.org/x/tools/go/types/typeutil"
)

// Config lists the token types as "importpath.TypeName" strings.
type Config struct {
	TokenTypes []string
}

var fmtSinks = []string{
	"Print", "Printf", "Println", "Fprint", "Fprintf", "Fprintln",
	"Sprint", "Sprintf", "Sprintln", "Errorf", "Append", "Appendf", "Appendln",
}

// New returns the R3 analyzer for cfg.
func New(cfg Config) *analysis.Analyzer {
	return &analysis.Analyzer{
		Name:     "nosecretlogs",
		Doc:      "R3: token-typed values (including nested in composites) must not be logged, printed or formatted by log, log/slog or fmt",
		Requires: []*analysis.Analyzer{inspect.Analyzer},
		Run:      func(pass *analysis.Pass) (any, error) { return nil, run(pass, cfg) },
	}
}

func run(pass *analysis.Pass, cfg Config) error {
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
			layer, tok, direct := findToken(pass.TypesInfo, arg, cfg.TokenTypes)
			switch {
			case tok == "":
			case direct:
				pass.Reportf(arg.Pos(), "R3: value of token type %s passed to %s", tok, fn.FullName())
			default:
				pass.Reportf(arg.Pos(), "R3: value of type %s contains token type %s, passed to %s",
					types.TypeString(layer, func(p *types.Package) string { return p.Path() }), tok, fn.FullName())
			}
		}
	})
	return nil
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

// findToken peels parentheses and conversions off e and returns the first
// layer's type that is or contains a token type, with the token's name.
// direct reports that the layer's type is the token type itself (optionally
// behind one pointer) rather than a composite holding one.
func findToken(info *types.Info, e ast.Expr, tokens []string) (layer types.Type, tok string, direct bool) {
	for {
		e = ast.Unparen(e)
		if t := info.TypeOf(e); t != nil {
			if name := tokenName(t, tokens); name != "" {
				return t, name, true
			}
			if name := contains(t, tokens, map[*types.Named]bool{}); name != "" {
				return t, name, false
			}
		}
		call, ok := e.(*ast.CallExpr)
		if !ok || len(call.Args) != 1 || !info.Types[call.Fun].IsType() {
			return nil, "", false
		}
		e = call.Args[0]
	}
}

// tokenName returns t's token name if t is a token type, optionally behind one pointer.
func tokenName(t types.Type, tokens []string) string {
	t = types.Unalias(t)
	if p, ok := t.(*types.Pointer); ok {
		t = types.Unalias(p.Elem())
	}
	named, ok := t.(*types.Named)
	if !ok || named.Obj().Pkg() == nil {
		return ""
	}
	name := named.Obj().Pkg().Path() + "." + named.Obj().Name()
	if slices.Contains(tokens, name) {
		return name
	}
	return ""
}

// contains walks t for a token type. It stops at interfaces, funcs, chans and
// basics, and uses seen to terminate on recursive types.
func contains(t types.Type, tokens []string, seen map[*types.Named]bool) string {
	switch t := types.Unalias(t).(type) {
	case *types.Pointer:
		return contains(t.Elem(), tokens, seen)
	case *types.Named:
		if name := tokenName(t, tokens); name != "" {
			return name
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
