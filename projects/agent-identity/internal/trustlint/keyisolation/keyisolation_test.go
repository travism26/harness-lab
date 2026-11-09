package keyisolation

import (
	"testing"

	"golang.org/x/tools/go/analysis/analysistest"
)

func TestKeyIsolation(t *testing.T) {
	cfg := Config{
		Exempt:  []string{"example.com/m/broker", "example.com/m/brokercmd"},
		KeyRefs: []string{"example.com/m/broker.Choice.Key", "example.com/m/broker.Select"},
		Loaders: []string{"example.com/m/broker.WithDotEnv", "example.com/m/broker.DotEnvPath"},
		KeyVars: []string{"ANTHROPIC_API_KEY", "OPENROUTER_API_KEY"},
	}
	analysistest.Run(t, analysistest.TestData(), New(cfg),
		"example.com/m/broker/...",
		"example.com/m/brokercmd",
		"example.com/m/bad",
		"example.com/m/good",
	)
}
