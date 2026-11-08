// Package nosecretlogs implements trustlint rule R3: token-typed values must
// not reach logging or printing sinks. Its real configuration lives in
// projects/agent-identity/internal/trustlint/config.go.
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

var fmtSinks = []string{"Print", "Printf", "Println", "Fprint", "Fprintf", "Fprintln"}

// New returns the R3 analyzer for cfg.
func New(cfg Config) *analysis.Analyzer {
	return &analysis.Analyzer{
		Name:     "nosecretlogs",
		Doc:      "R3: token-typed values must not be logged or printed",
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
		for _, arg := range call.Args {
			if tok := tokenType(pass.TypesInfo, arg, cfg.TokenTypes); tok != "" {
				pass.Reportf(arg.Pos(), "R3: value of token type %s passed to %s", tok, fn.FullName())
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

// tokenType peels parentheses and conversions off e and returns the first
// layer's token type name, or "" if none is a token type.
func tokenType(info *types.Info, e ast.Expr, tokens []string) string {
	for {
		e = ast.Unparen(e)
		if name := matchToken(info.TypeOf(e), tokens); name != "" {
			return name
		}
		call, ok := e.(*ast.CallExpr)
		if !ok || len(call.Args) != 1 || !info.Types[call.Fun].IsType() {
			return ""
		}
		e = call.Args[0]
	}
}

func matchToken(t types.Type, tokens []string) string {
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
