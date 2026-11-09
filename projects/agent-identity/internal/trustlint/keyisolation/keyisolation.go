// Package keyisolation implements trustlint rule R5: outside the exempt
// packages (the Broker module and the Broker command), no package may
// reference the chosen provider key, use the .env loader, or pass a provider
// key variable name to os.Getenv or os.LookupEnv. There are no per-package
// exceptions beyond Config.Exempt. Its real configuration lives in
// projects/agent-identity/internal/trustlint/config.go.
//
// References are matched by object, not by text: a use of a configured
// "importpath.Name" (a function, variable, constant or type) or
// "importpath.Type.Field" or "importpath.Type.Method". A key variable name is
// matched by the constant value of the first argument of os.Getenv or
// os.LookupEnv, so a named constant or a concatenation is caught; a name
// computed at run time is not.
package keyisolation

import (
	"go/ast"
	"go/constant"
	"go/types"
	"slices"
	"strings"

	"golang.org/x/tools/go/analysis"
	"golang.org/x/tools/go/analysis/passes/inspect"
	"golang.org/x/tools/go/ast/inspector"
	"golang.org/x/tools/go/types/typeutil"
)

// Config names the exempt packages and what may not be referenced elsewhere.
type Config struct {
	// Exempt are package paths (and everything under them) R5 does not apply to.
	Exempt []string
	// KeyRefs reference the chosen provider key.
	KeyRefs []string
	// Loaders are the .env loader.
	Loaders []string
	// KeyVars are the provider key variable names.
	KeyVars []string
}

// New returns the R5 analyzer for cfg.
func New(cfg Config) *analysis.Analyzer {
	return &analysis.Analyzer{
		Name:     "keyisolation",
		Doc:      "R5: only the Broker module and command may reference the chosen provider key, use the .env loader or read a provider key variable",
		Requires: []*analysis.Analyzer{inspect.Analyzer},
		Run:      func(pass *analysis.Pass) (any, error) { return nil, run(pass, cfg) },
	}
}

func run(pass *analysis.Pass, cfg Config) error {
	// An external test package is path_test, and its test main is path.test.
	self := strings.TrimSuffix(strings.TrimSuffix(pass.Pkg.Path(), ".test"), "_test")
	for _, e := range cfg.Exempt {
		if self == e || strings.HasPrefix(self, e+"/") {
			return nil
		}
	}

	names := map[types.Object]string{}
	for id, obj := range pass.TypesInfo.Uses {
		name := qualified(obj, names)
		switch {
		case name == "":
		case slices.Contains(cfg.KeyRefs, name):
			pass.Reportf(id.Pos(), "R5: %s references the chosen provider key %s; only the Broker may", self, name)
		case slices.Contains(cfg.Loaders, name):
			pass.Reportf(id.Pos(), "R5: %s uses the .env loader %s; only the Broker may", self, name)
		}
	}

	insp := pass.ResultOf[inspect.Analyzer].(*inspector.Inspector)
	insp.Preorder([]ast.Node{(*ast.CallExpr)(nil)}, func(n ast.Node) {
		call := n.(*ast.CallExpr)
		fn, ok := typeutil.Callee(pass.TypesInfo, call).(*types.Func)
		if !ok || fn.Pkg() == nil || fn.Pkg().Path() != "os" || len(call.Args) == 0 ||
			(fn.Name() != "Getenv" && fn.Name() != "LookupEnv") {
			return
		}
		tv := pass.TypesInfo.Types[call.Args[0]]
		if tv.Value == nil || tv.Value.Kind() != constant.String {
			return
		}
		if v := constant.StringVal(tv.Value); slices.Contains(cfg.KeyVars, v) {
			pass.Reportf(call.Args[0].Pos(), "R5: %s passes the provider key variable %s to os.%s; only the Broker may", self, v, fn.Name())
		}
	})
	return nil
}

// qualified names obj as "path.Name", "path.Type.Method" or "path.Type.Field",
// or "" for anything else (locals, parameters, methods of unnamed types).
func qualified(obj types.Object, cache map[types.Object]string) string {
	if obj.Pkg() == nil {
		return ""
	}
	if name, ok := cache[obj]; ok {
		return name
	}
	path, name := obj.Pkg().Path(), ""
	switch o := obj.(type) {
	case *types.Func:
		if sig := o.Type().(*types.Signature); sig.Recv() != nil {
			t := sig.Recv().Type()
			if p, ok := t.(*types.Pointer); ok {
				t = p.Elem()
			}
			if named, ok := types.Unalias(t).(*types.Named); ok {
				name = path + "." + named.Obj().Name() + "." + o.Name()
			}
		} else if o.Parent() == o.Pkg().Scope() {
			name = path + "." + o.Name()
		}
	case *types.Var:
		if o.IsField() {
			name = fieldName(o)
		} else if o.Parent() == o.Pkg().Scope() {
			name = path + "." + o.Name()
		}
	case *types.Const, *types.TypeName:
		if obj.Parent() == obj.Pkg().Scope() {
			name = path + "." + obj.Name()
		}
	}
	cache[obj] = name
	return name
}

// fieldName finds the named struct type in f's package that declares f.
func fieldName(f *types.Var) string {
	scope := f.Pkg().Scope()
	for _, n := range scope.Names() {
		tn, ok := scope.Lookup(n).(*types.TypeName)
		if !ok {
			continue
		}
		st, ok := tn.Type().Underlying().(*types.Struct)
		if !ok {
			continue
		}
		for i := range st.NumFields() {
			if st.Field(i) == f {
				return f.Pkg().Path() + "." + tn.Name() + "." + f.Name()
			}
		}
	}
	return ""
}
