// Package provider holds the one rule that picks the live Model provider
// (ADR 0003), shared by cmd/demo and cmd/eval. It does not import the Model
// client, so any command may use it.
package provider

import "fmt"

// Provider describes one live provider: its API root and the environment
// variable that holds its key.
type Provider struct {
	Name, BaseURL, KeyEnv string
}

// Providers are the two live providers.
var Providers = map[string]Provider{
	"anthropic":  {"anthropic", "https://api.anthropic.com", "ANTHROPIC_API_KEY"},
	"openrouter": {"openrouter", "https://openrouter.ai/api", "OPENROUTER_API_KEY"},
}

// Choice is the provider a run uses, with its key.
type Choice struct {
	Provider
	Key string
}

// Select makes the choice once, before any request: the named provider, else
// Anthropic if its key is present, else OpenRouter. getenv reads the key; the
// caller decides where keys come from. A missing key is an error that names
// the variable, never the key.
func Select(name string, getenv func(string) string) (Choice, error) {
	if name == "" {
		anthropic, openrouter := Providers["anthropic"], Providers["openrouter"]
		switch {
		case getenv(anthropic.KeyEnv) != "":
			name = anthropic.Name
		case getenv(openrouter.KeyEnv) != "":
			name = openrouter.Name
		default:
			return Choice{}, fmt.Errorf("no provider key: set %s or %s", anthropic.KeyEnv, openrouter.KeyEnv)
		}
	}
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
