package pin

import (
	"encoding/json"
	"slices"

	"github.com/travism26/harness-lab/projects/agent-identity/internal/modelrequest"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/provider"
)

// Agent is the Pin the Broker holds the permission-agent to: each provider's
// default model, the Model client's max_tokens as the ceiling, and the
// request-shape hash of the Model client's own request fields. It is computed
// from the request constants in projects/agent-identity/internal/modelrequest, never written down, so
// the Agent and its Pin cannot drift; a test in the Model client package sends
// a real request and checks the hash against it.
func Agent() Pin {
	return build(func(p provider.Provider) []string { return []string{p.DefaultModel} })
}

// ModelEval is the Pin for the Eval's model-eval workload: every model in the
// Eval sweep for each provider, with the same ceiling and request shape as
// Agent.
func ModelEval() Pin {
	return build(func(p provider.Provider) []string { return slices.Clone(p.Sweep) })
}

func build(list func(provider.Provider) []string) Pin {
	raw, err := json.Marshal(modelrequest.Fields(nil))
	if err != nil {
		panic(err) // the constants always encode
	}
	shape, err := Shape(raw)
	if err != nil {
		panic(err)
	}
	models := map[string][]string{}
	for name, p := range provider.Providers {
		models[name] = list(p)
	}
	models[provider.StandIn.Name] = list(provider.StandIn)
	return Pin{Models: models, MaxTokens: modelrequest.MaxTokens, Shape: shape}
}
