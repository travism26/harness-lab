// Package provider stands in for a provider table that names its key variable
// in a field. It is not analyzed itself; the bad package reads the field.
package provider

// Provider has a field that names the variable holding its key.
type Provider struct {
	Name, BaseURL, KeyEnv string
}

// Providers is the table.
var Providers = map[string]Provider{
	"anthropic": {Name: "anthropic", BaseURL: "https://a.example", KeyEnv: "ANTHROPIC_API_KEY"},
}
