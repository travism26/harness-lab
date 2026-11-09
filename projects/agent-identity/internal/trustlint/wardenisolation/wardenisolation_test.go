package wardenisolation

import (
	"testing"

	"golang.org/x/tools/go/analysis/analysistest"
)

func TestWorkloadIsolation(t *testing.T) {
	cfg := Config{Rules: []Rule{
		{
			Name:     "the Warden",
			Isolated: []string{"example.com/m/internal/warden"},
			Forbidden: []string{
				"example.com/m/internal/agent", "example.com/m/internal/modelclient", "example.com/m/internal/broker",
			},
		},
		{
			Name:      "the Broker",
			Isolated:  []string{"example.com/m/internal/broker"},
			Forbidden: []string{"example.com/m/internal/agent", "example.com/m/internal/warden"},
		},
	}}
	analysistest.Run(t, analysistest.TestData(), New(cfg),
		"example.com/m/internal/warden",
		"example.com/m/internal/warden/sub",
		"example.com/m/internal/warden/indirect",
		// The Warden importing the Broker, directly and through a helper.
		"example.com/m/internal/warden/viabroker",
		"example.com/m/internal/warden/viabrokerhelper",
		"example.com/m/internal/nonwarden",
		"example.com/m/internal/other",
		// The Broker importing the Agent and the Warden, directly, through a
		// helper and from an external test package; and a Broker that imports
		// only what it may.
		"example.com/m/internal/broker",
		"example.com/m/internal/broker/indirect",
		"example.com/m/internal/broker/sub",
		// Packages outside both workloads may import any of them.
		"example.com/m/internal/usesbroker",
		"example.com/m/internal/useswarden",
	)
}
