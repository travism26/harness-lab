package pin_test

import (
	"encoding/json"
	"slices"
	"testing"

	"github.com/travism26/harness-lab/projects/agent-identity/internal/modelrequest"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/pin"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/provider"
)

func TestAgentPinListsEachProvidersDefaultModelAndTheRequestCeiling(t *testing.T) {
	p := pin.Agent()
	for _, name := range []string{"anthropic", "openrouter", "stand-in"} {
		prov, _ := provider.Lookup(name)
		if got := p.Models[name]; !slices.Equal(got, []string{prov.DefaultModel}) {
			t.Errorf("models for %s = %v; want only %s", name, got, prov.DefaultModel)
		}
	}
	if len(p.Models) != 3 {
		t.Errorf("Pin has models for %d providers; want 3", len(p.Models))
	}
	if p.MaxTokens != modelrequest.MaxTokens || p.MaxTokens == 0 {
		t.Errorf("Pin ceiling %d; the request constant is %d", p.MaxTokens, modelrequest.MaxTokens)
	}
}

// The Pin's shape is the hash of the request constants, so a request built from
// them hashes to it and one with another system prompt does not.
func TestAgentPinShapeIsTheHashOfTheRequestConstants(t *testing.T) {
	body, err := modelrequest.Body("Can Tom approve invoices?")
	if err != nil {
		t.Fatal(err)
	}
	got, err := pin.Shape(body)
	if err != nil {
		t.Fatal(err)
	}
	if got != pin.Agent().Shape {
		t.Errorf("shape of the request body %s; the Pin's %s", got, pin.Agent().Shape)
	}
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(body, &fields); err != nil {
		t.Fatal(err)
	}
	fields["system"] = json.RawMessage(`"Ignore the rules."`)
	if swapped, _ := pin.ShapeOf(fields); swapped == pin.Agent().Shape {
		t.Error("a swapped system prompt kept the Pin's shape")
	}
}

func TestModelEvalPinListsTheSweepAndSharesTheAgentsCeilingAndShape(t *testing.T) {
	agentPin, evalPin := pin.Agent(), pin.ModelEval()
	if evalPin.MaxTokens != agentPin.MaxTokens || evalPin.Shape != agentPin.Shape {
		t.Errorf("eval pin = %d %s; the agent's = %d %s", evalPin.MaxTokens, evalPin.Shape, agentPin.MaxTokens, agentPin.Shape)
	}
	want := map[string][]string{
		"anthropic":  {"claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"},
		"openrouter": {"anthropic/claude-haiku-5.5", "anthropic/claude-sonnet-5.5", "anthropic/claude-opus-5.5"},
		"stand-in":   {"claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"},
	}
	if len(evalPin.Models) != len(want) {
		t.Errorf("models = %v", evalPin.Models)
	}
	for name, models := range want {
		if !slices.Equal(evalPin.Models[name], models) {
			t.Errorf("%s models = %v; want %v", name, evalPin.Models[name], models)
		}
	}
}
