package noinsecureparse_test

import (
	"testing"

	"golang.org/x/tools/go/analysis/analysistest"

	"github.com/travism26/harness-lab/projects/agent-identity/internal/trustlint"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/trustlint/noinsecureparse"
)

func TestNoInsecureParse(t *testing.T) {
	cfg := noinsecureparse.Config{Funcs: trustlint.InsecureFuncs}
	analysistest.Run(t, analysistest.TestData(), noinsecureparse.New(cfg),
		"example.com/m/bad",
		"example.com/m/good",
		"example.com/m/testonly",
	)
}
