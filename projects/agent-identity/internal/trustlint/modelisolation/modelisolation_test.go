package modelisolation

import (
	"testing"

	"golang.org/x/tools/go/analysis/analysistest"
)

func TestModelIsolation(t *testing.T) {
	cfg := Config{
		ModelClient: "example.com/m/internal/modelclient",
		Allowed:     []string{"example.com/m/internal/agent"},
	}
	analysistest.Run(t, analysistest.TestData(), New(cfg),
		"example.com/m/internal/agent",
		"example.com/m/internal/demo",
		"example.com/m/internal/modelclient/...",
	)
}
