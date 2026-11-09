// Package provider holds the one table of Model providers and the rule that
// picks the live one (projects/agent-identity/docs/adr/0003-anthropic-api-as-a-second-model-provider.md),
// shared by projects/agent-identity/cmd/demo, projects/agent-identity/cmd/eval, projects/agent-identity/internal/agent, projects/agent-identity/internal/eval and
// projects/agent-identity/internal/modelclient. It does not import the Model client, so any package may
// use it.
package provider

import "fmt"

// Provider describes one Model provider: its API root, the environment variable
// that holds its key, the model id used when none is given, and how it takes
// the key.
type Provider struct {
	Name, BaseURL, KeyEnv string
	// DefaultModel is the model id used when none is given.
	DefaultModel string
	// Sweep is every model the Eval sweep runs on this provider (Haiku, Sonnet
	// and Opus), the default first. The Broker's model-eval Pin lists them.
	Sweep []string
	// BearerAuth sends Authorization: Bearer (OpenRouter) instead of x-api-key
	// plus anthropic-version.
	BearerAuth bool
	// PricedByTable means the provider reports no cost, so the Model client
	// computes it from the price table in this package.
	PricedByTable bool
}

// Providers are the two live providers.
var Providers = map[string]Provider{
	"anthropic": {
		Name: "anthropic", BaseURL: "https://api.anthropic.com", KeyEnv: "ANTHROPIC_API_KEY",
		DefaultModel: "claude-haiku-5-5", PricedByTable: true,
		Sweep: []string{"claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"},
	},
	"openrouter": {
		Name: "openrouter", BaseURL: "https://openrouter.ai/api", KeyEnv: "OPENROUTER_API_KEY",
		DefaultModel: "anthropic/claude-haiku-5.5", BearerAuth: true,
		Sweep: []string{"anthropic/claude-haiku-5.5", "anthropic/claude-sonnet-5.5", "anthropic/claude-opus-5.5"},
	},
}

// StandIn is the stand-in Model, which needs no key. It is sent Anthropic's
// default model id, though no real model answers.
var StandIn = Provider{Name: "stand-in", DefaultModel: Providers["anthropic"].DefaultModel, Sweep: Providers["anthropic"].Sweep}

// Lookup finds a provider by name, the stand-in included. An unknown name
// returns the Anthropic provider's settings with ok false.
func Lookup(name string) (p Provider, ok bool) {
	if name == StandIn.Name {
		return StandIn, true
	}
	if p, ok = Providers[name]; ok {
		return p, true
	}
	return Providers["anthropic"], false
}

// Choice is the provider a run uses, with its key.
type Choice struct {
	Provider
	Key string
}

// Choose names the provider by the ADR 0003 rule: the named one, else Anthropic
// if its key is present, else OpenRouter. It does not check that the chosen
// provider's key is present; Select does.
func Choose(name string, getenv func(string) string) string {
	if name != "" {
		return name
	}
	if getenv(Providers["anthropic"].KeyEnv) != "" {
		return "anthropic"
	}
	return "openrouter"
}

// Select makes the choice once, before any request: the named provider, else
// Anthropic if its key is present, else OpenRouter. getenv reads the key; the
// caller decides where keys come from. A missing key is an error that names
// the variable, never the key.
func Select(name string, getenv func(string) string) (Choice, error) {
	if anthropic, openrouter := Providers["anthropic"], Providers["openrouter"]; name == "" &&
		getenv(anthropic.KeyEnv) == "" && getenv(openrouter.KeyEnv) == "" {
		return Choice{}, fmt.Errorf("no provider key: set %s or %s", anthropic.KeyEnv, openrouter.KeyEnv)
	}
	name = Choose(name, getenv)
	p, ok := Providers[name]
	if !ok {
		return Choice{}, fmt.Errorf("unknown provider %q (anthropic or openrouter)", name)
	}
	key := getenv(p.KeyEnv)
	if key == "" {
		return Choice{}, fmt.Errorf("provider %s needs %s", name, p.KeyEnv)
	}
	return Choice{Provider: p, Key: key}, nil
}
