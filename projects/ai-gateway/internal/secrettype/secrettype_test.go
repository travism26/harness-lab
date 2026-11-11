package secrettype

import (
	"testing"

	"golang.org/x/tools/go/analysis"
	"golang.org/x/tools/go/analysis/analysistest"
)

func TestAnalyzerIsValid(t *testing.T) {
	if err := analysis.Validate([]*analysis.Analyzer{Analyzer}); err != nil {
		t.Fatal(err)
	}
}

func TestReportsTestdata(t *testing.T) {
	old := credentialFlag
	credentialFlag = "credential.Credential"
	t.Cleanup(func() { credentialFlag = old })
	analysistest.Run(t, analysistest.TestData(), Analyzer, "callrecord", "leaky")
}
