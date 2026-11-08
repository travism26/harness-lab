package wardenisolation

import (
	"testing"

	"golang.org/x/tools/go/analysis/analysistest"
)

func TestWardenIsolation(t *testing.T) {
	cfg := Config{
		Warden:    []string{"example.com/m/internal/warden"},
		Forbidden: []string{"example.com/m/internal/agent", "example.com/m/internal/modelclient"},
	}
	analysistest.Run(t, analysistest.TestData(), New(cfg),
		"example.com/m/internal/warden",
		"example.com/m/internal/warden/sub",
		"example.com/m/internal/warden/indirect",
		"example.com/m/internal/nonwarden",
		"example.com/m/internal/other",
	)
}
