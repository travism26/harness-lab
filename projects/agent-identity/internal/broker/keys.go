package broker

import (
	"fmt"
	"net/http"

	"github.com/travism26/harness-lab/projects/agent-identity/internal/provider"
)

// keyEnv names the variable that holds each provider's key. Nothing outside
// the Broker may know these names (trustlint R5); a test pins trustlint.KeyVars
// to this table.
var keyEnv = map[string]string{"anthropic": "ANTHROPIC_API_KEY", "openrouter": "OPENROUTER_API_KEY"}

// Choice is the provider a run uses, with its key. It lives here, with the
// .env loader and the auth headers, because the Broker is the only place a
// provider key may be (trustlint R5).
type Choice struct {
	provider.Provider
	Key string
}

// Choose names the provider by the ADR 0003 rule: the named one, else Anthropic
// if its key is present, else OpenRouter. It does not check that the chosen
// provider's key is present; Select does.
func Choose(name string, getenv func(string) string) string {
	if name != "" {
		return name
	}
	if getenv(keyEnv["anthropic"]) != "" {
		return "anthropic"
	}
	return "openrouter"
}

// Select makes the choice once, before any request: the named provider, else
// Anthropic if its key is present, else OpenRouter. getenv reads the key; the
// caller decides where keys come from. A missing key is an error that names
// the variable, never the key.
func Select(name string, getenv func(string) string) (Choice, error) {
	if name == "" &&
		getenv(keyEnv["anthropic"]) == "" && getenv(keyEnv["openrouter"]) == "" {
		return Choice{}, fmt.Errorf("no provider key: set %s or %s", keyEnv["anthropic"], keyEnv["openrouter"])
	}
	name = Choose(name, getenv)
	p, ok := provider.Providers[name]
	if !ok {
		return Choice{}, fmt.Errorf("unknown provider %q (anthropic or openrouter)", name)
	}
	key := getenv(keyEnv[name])
	if key == "" {
		return Choice{}, fmt.Errorf("provider %s needs %s", name, keyEnv[name])
	}
	return Choice{Provider: p, Key: key}, nil
}

// AnthropicVersion is the anthropic-version header value sent with x-api-key.
const AnthropicVersion = "2026-10-21"

// setAuth sets the provider's authentication headers on h: a bearer token for
// OpenRouter, x-api-key plus anthropic-version otherwise. Only the Broker
// sends a provider key.
func setAuth(p provider.Provider, h http.Header, key string) {
	if p.BearerAuth {
		h.Set("Authorization", "Bearer "+key)
		return
	}
	h.Set("x-api-key", key)
	h.Set("anthropic-version", AnthropicVersion)
}
