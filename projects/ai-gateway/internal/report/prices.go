package report

import "strings"

// PricesSource and PricesRetrieved pin where the table below came from. The
// figures are Anthropic's published list prices in USD per million tokens
// (MTok), read from the "Model pricing" table on that page on that date.
// They are a sketch: batch, fast mode, data residency and negotiated prices
// are not modelled.
const (
	PricesSource    = "https://platform.claude.com/docs/en/about-claude/pricing"
	PricesRetrieved = "2026-11-22"
)

// Price is a list price in USD per MTok.
type Price struct {
	Input      float64
	CacheWrite float64 // the 5-minute cache write price; see Estimate
	CacheRead  float64
	Output     float64
}

// modelPrice is one row of the pricing table. Over100k, when not nil, is the
// price for a request whose prompt (input, cache write and cache read tokens
// together) is over 100,000 tokens; Claude Haiku 5.5 is priced that way.
type modelPrice struct {
	Price
	Over100k *Price
}

// prices is keyed by the model name on the pricing page, lower-cased, with
// spaces and dots turned into hyphens ("Claude Sonnet 4.5" is
// "claude-sonnet-4-5"). priceFor matches a Call record's model against it.
// Columns: input, 5m cache write, cache read, output.
var prices = map[string]modelPrice{
	"claude-fable-5-2":  {Price: Price{8, 10, 0.20, 40}},
	"claude-mythos-5-2": {Price: Price{8, 10, 0.20, 40}},
	"claude-fable-5-1":  {Price: Price{10, 12.5, 0.25, 50}},
	"claude-mythos-5-1": {Price: Price{10, 12.5, 0.25, 50}},
	"claude-fable-5":    {Price: Price{10, 12.5, 1, 50}},
	"claude-mythos-5":   {Price: Price{10, 12.5, 1, 50}},
	"claude-opus-5-5":   {Price: Price{4, 5, 0.20, 20}},
	"claude-opus-5":     {Price: Price{5, 6.25, 0.50, 25}},
	"claude-opus-4-8":   {Price: Price{5, 6.25, 0.50, 25}},
	"claude-opus-4-7":   {Price: Price{5, 6.25, 0.50, 25}},
	"claude-opus-4-6":   {Price: Price{5, 6.25, 0.50, 25}},
	"claude-opus-4-5":   {Price: Price{5, 6.25, 0.50, 25}},
	"claude-opus-4-1":   {Price: Price{15, 18.75, 1.50, 75}},
	"claude-opus-4":     {Price: Price{15, 18.75, 1.50, 75}},
	"claude-sonnet-5-5": {Price: Price{2, 2.5, 0.10, 10}},
	"claude-sonnet-5":   {Price: Price{2, 2.5, 0.20, 10}},
	"claude-sonnet-4-6": {Price: Price{3, 3.75, 0.30, 15}},
	"claude-sonnet-4-5": {Price: Price{3, 3.75, 0.30, 15}},
	"claude-sonnet-4":   {Price: Price{3, 3.75, 0.30, 15}},
	"claude-haiku-5-5": {
		Price:    Price{0.10, 0.125, 0.01, 0.50},
		Over100k: &Price{0.50, 0.625, 0.05, 2.50},
	},
	"claude-haiku-4-5": {Price: Price{1, 1.25, 0.10, 5}},
}

// priceFor returns the price row for a model id such as
// "claude-sonnet-4-5-20250929". The id must be a table key, optionally
// followed by "-latest" or an 8-digit date; any "[...]" suffix is ignored.
// The longest matching key wins, so "claude-opus-4-5-..." is not read as
// "claude-opus-4". Anything else has no list price and is not guessed.
func priceFor(model string) (modelPrice, bool) {
	id := strings.ToLower(model)
	if i := strings.IndexByte(id, '['); i >= 0 {
		id = id[:i]
	}
	best, found := "", false
	for key := range prices {
		if !strings.HasPrefix(id, key) || !validSuffix(id[len(key):]) {
			continue
		}
		if len(key) > len(best) {
			best, found = key, true
		}
	}
	return prices[best], found
}

// validSuffix accepts "", "-latest" and "-YYYYMMDD".
func validSuffix(s string) bool {
	if s == "" || s == "-latest" {
		return true
	}
	if len(s) != 9 || s[0] != '-' {
		return false
	}
	for _, c := range s[1:] {
		if c < '0' || c > '9' {
			return false
		}
	}
	return true
}
