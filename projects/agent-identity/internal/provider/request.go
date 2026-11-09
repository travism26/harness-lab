package provider

import "net/http"

// AnthropicVersion is the anthropic-version header value sent with x-api-key.
const AnthropicVersion = "2026-10-21"

// SetAuth sets the provider's authentication headers on h: a bearer token for
// OpenRouter, x-api-key plus anthropic-version otherwise.
func (p Provider) SetAuth(h http.Header, key string) {
	if p.BearerAuth {
		h.Set("Authorization", "Bearer "+key)
		return
	}
	h.Set("x-api-key", key)
	h.Set("anthropic-version", AnthropicVersion)
}

// price is USD per million input and output tokens.
type price struct{ input, output float64 }

// pricesPerMillion is the price per model id (projects/agent-identity/docs/adr/0003-anthropic-api-as-a-second-model-provider.md).
var pricesPerMillion = map[string]price{
	"claude-haiku-5-5":  {input: 0.10, output: 0.50},
	"claude-sonnet-5-5": {input: 2, output: 10},
	"claude-opus-5-5":   {input: 4, output: 20},
}

// Cost is what a response cost in USD: the cost the provider reported if any,
// else, for a provider priced by table, the usage times the model's price, else
// 0. A model missing from the table costs 0.
func (p Provider) Cost(model string, inputTokens, outputTokens float64, reported *float64) float64 {
	if reported != nil {
		return *reported
	}
	if !p.PricedByTable {
		return 0
	}
	pr := pricesPerMillion[model]
	return (inputTokens*pr.input + outputTokens*pr.output) / 1e6
}
