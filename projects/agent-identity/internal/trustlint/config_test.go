package trustlint

import (
	"go/types"
	"path/filepath"
	"slices"
	"strings"
	"testing"

	"golang.org/x/tools/go/analysis"
	"golang.org/x/tools/go/packages"

	"github.com/travism26/harness-lab/projects/agent-identity/internal/provider"
)

// splitQualified splits "pkg/path.Name" at the last dot.
func splitQualified(s string) (pkg, name string) {
	i := strings.LastIndex(s, ".")
	return s[:i], s[i+1:]
}

// parseFuncName splits a types.Func.FullName into package path and receiver
// type name ("" for a plain function): "(*p.T).M" -> p, T; "p.F" -> p, "".
func parseFuncName(s string) (pkg, recv string) {
	if !strings.HasPrefix(s, "(") {
		pkg, _ = splitQualified(s)
		return pkg, ""
	}
	inner, _, _ := strings.Cut(s[1:], ")")
	inner = strings.TrimPrefix(inner, "*")
	return splitQualified(inner)
}

func moduleRoot(t *testing.T) string {
	t.Helper()
	return filepath.Join("..", "..") // tests run in internal/trustlint
}

func loadPackages(t *testing.T, paths []string) map[string]*packages.Package {
	t.Helper()
	cfg := &packages.Config{
		Mode: packages.NeedName | packages.NeedTypes | packages.NeedModule | packages.NeedDeps | packages.NeedImports,
		Dir:  moduleRoot(t),
	}
	pkgs, err := packages.Load(cfg, paths...)
	if err != nil {
		t.Fatalf("loading packages: %v", err)
	}
	out := map[string]*packages.Package{}
	for _, p := range pkgs {
		out[p.PkgPath] = p
		for _, e := range p.Errors {
			t.Errorf("package %s: load error: %v", p.PkgPath, e)
		}
	}
	return out
}

func TestConfigNamesRealPackages(t *testing.T) {
	wirePath := prefix + "/internal/wire"

	var paths []string
	add := func(p string) {
		if !slices.Contains(paths, p) {
			paths = append(paths, p)
		}
	}
	add(wirePath)
	add(Agent)
	add(Warden)
	add(Broker)
	for _, tt := range TokenTypes {
		p, _ := splitQualified(tt)
		add(p)
	}
	for _, f := range InsecureFuncs {
		p, _ := parseFuncName(f)
		add(p)
	}
	pkgs := loadPackages(t, paths)
	for _, p := range paths {
		if pkgs[p] == nil || pkgs[p].Types == nil {
			t.Errorf("package %q not loaded", p)
		}
	}

	// A wrong prefix would also break ModelClient and the eval importer, which
	// cannot be loaded yet, so pin prefix against a package that exists.
	if w := pkgs[wirePath]; w != nil {
		if w.Module == nil || w.Module.Path != prefix {
			t.Errorf("prefix %q does not match the module path of %s (%+v)", prefix, wirePath, w.Module)
		}
	}

	// ModelClient and the eval importer do not exist yet, so they cannot be
	// loaded; check only that they sit under this module's internal/ tree.
	for _, p := range append([]string{ModelClient}, ModelClientImporters...) {
		if !strings.HasPrefix(p, prefix+"/internal/") {
			t.Errorf("%q is not under %s/internal/", p, prefix)
		}
	}

	for _, tt := range TokenTypes {
		pp, name := splitQualified(tt)
		pkg := pkgs[pp]
		if pkg == nil || pkg.Types == nil {
			continue
		}
		tn, ok := pkg.Types.Scope().Lookup(name).(*types.TypeName)
		if !ok {
			t.Errorf("TokenTypes entry %q: %s has no type %q", tt, pp, name)
			continue
		}
		if _, ok := tn.Type().(*types.Named); !ok {
			t.Errorf("TokenTypes entry %q: %q is not a named type", tt, name)
		}
	}

	for _, f := range InsecureFuncs {
		pp, _ := parseFuncName(f)
		pkg := pkgs[pp]
		if pkg == nil || pkg.Types == nil {
			continue
		}
		if !slices.Contains(funcNames(pkg.Types), f) {
			t.Errorf("InsecureFuncs entry %q matches no function or method in %s", f, pp)
		}
	}
}

// funcNames returns FullName of every package-scope func and every method of
// each named type in scope (value and pointer receivers).
func funcNames(pkg *types.Package) []string {
	var names []string
	scope := pkg.Scope()
	for _, n := range scope.Names() {
		switch obj := scope.Lookup(n).(type) {
		case *types.Func:
			names = append(names, obj.FullName())
		case *types.TypeName:
			named, ok := obj.Type().(*types.Named)
			if !ok {
				continue
			}
			for _, t := range []types.Type{named, types.NewPointer(named)} {
				ms := types.NewMethodSet(t)
				for i := range ms.Len() {
					if fn, ok := ms.At(i).Obj().(*types.Func); ok {
						names = append(names, fn.FullName())
					}
				}
			}
		}
	}
	return names
}

// R5's references must name real objects, or the rule would guard nothing.
func TestKeyIsolationNamesRealObjectsAndEveryKeyVariable(t *testing.T) {
	pkgs := loadPackages(t, []string{Broker, BrokerCommand})
	for _, p := range []string{Broker, BrokerCommand} {
		if pkgs[p] == nil || pkgs[p].Types == nil {
			t.Fatalf("package %q not loaded", p)
		}
	}
	scope := pkgs[Broker].Types.Scope()
	for _, ref := range append(slices.Clone(KeyRefs), Loaders...) {
		parts := strings.Split(strings.TrimPrefix(ref, Broker+"."), ".")
		obj := scope.Lookup(parts[0])
		if !strings.HasPrefix(ref, Broker+".") || obj == nil {
			t.Errorf("R5 reference %q names nothing in %s", ref, Broker)
			continue
		}
		if len(parts) == 2 {
			if f, _, _ := types.LookupFieldOrMethod(obj.Type(), true, obj.Pkg(), parts[1]); f == nil {
				t.Errorf("R5 reference %q: %s has no field or method %q", ref, parts[0], parts[1])
			}
		}
	}
	var envs []string
	for _, p := range provider.Providers {
		envs = append(envs, p.KeyEnv)
	}
	slices.Sort(envs)
	if got := slices.Sorted(slices.Values(KeyVars)); !slices.Equal(got, envs) {
		t.Errorf("KeyVars = %v; want every provider's KeyEnv %v", got, envs)
	}
	if !slices.Equal(KeyExempt, []string{Broker, BrokerCommand}) {
		t.Errorf("KeyExempt = %v; want the Broker module and command only", KeyExempt)
	}
}

func TestAnalyzersAreFiveDistinctValidAnalyzers(t *testing.T) {
	as := Analyzers()
	if len(as) != 5 {
		t.Fatalf("Analyzers() returned %d analyzers, want 5", len(as))
	}
	seen := map[string]bool{}
	for _, a := range as {
		if seen[a.Name] {
			t.Errorf("duplicate analyzer name %q", a.Name)
		}
		seen[a.Name] = true
	}
	if err := analysis.Validate(as); err != nil {
		t.Errorf("analysis.Validate: %v", err)
	}
}
