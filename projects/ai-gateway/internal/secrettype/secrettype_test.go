package secrettype

import (
	"testing"

	"golang.org/x/tools/go/analysis"
	"golang.org/x/tools/go/analysis/analysistest"
	"golang.org/x/tools/go/analysis/checker"
	"golang.org/x/tools/go/packages"
)

func TestAnalyzerIsValid(t *testing.T) {
	if err := analysis.Validate([]*analysis.Analyzer{Analyzer}); err != nil {
		t.Fatal(err)
	}
}

func TestReportsTestdata(t *testing.T) {
	f := Analyzer.Flags.Lookup("credential")
	old := f.Value.String()
	if err := Analyzer.Flags.Set("credential", "credential.Credential"); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = Analyzer.Flags.Set("credential", old) })
	analysistest.Run(t, analysistest.TestData(), Analyzer, "callrecord", "leaky")
}

// TestRealPackagesAreClean runs the analyzer with the default credential flag
// over the real Call record and Gateway packages.
func TestRealPackagesAreClean(t *testing.T) {
	const mod = "github.com/travism26/harness-lab/projects/ai-gateway/internal/"
	cfg := &packages.Config{Mode: packages.LoadAllSyntax}
	pkgs, err := packages.Load(cfg, mod+"callrecord", mod+"gateway")
	if err != nil || len(pkgs) != 2 {
		t.Fatalf("load: %v, %d packages", err, len(pkgs))
	}
	if got := Analyzer.Flags.Lookup("credential").Value.String(); got != defaultCredential {
		t.Fatalf("credential flag is %q, not the default", got)
	}
	graph, err := checker.Analyze([]*analysis.Analyzer{Analyzer}, pkgs, nil)
	if err != nil {
		t.Fatal(err)
	}
	for _, act := range graph.Roots {
		if act.Err != nil {
			t.Fatal(act.Err)
		}
		for _, d := range act.Diagnostics {
			t.Errorf("%s: %s", act.Package.Fset.Position(d.Pos), d.Message)
		}
	}
}
