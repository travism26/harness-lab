package secrettype

import (
	"testing"

	"golang.org/x/tools/go/analysis"
)

func TestAnalyzerIsValid(t *testing.T) {
	if err := analysis.Validate([]*analysis.Analyzer{Analyzer}); err != nil {
		t.Fatal(err)
	}
}
