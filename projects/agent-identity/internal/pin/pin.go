// Package pin holds the Pin: what the Broker lets one workload send. It is
// shared by the Broker, which enforces it, and by the code that builds it from
// the Model client's own request, so neither imports the other
// (projects/agent-identity/docs/adr/0004-the-provider-key-lives-only-in-the-broker.md).
package pin

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"sort"
)

// Pin is what the Broker lets one workload send. It has no provider of its own:
// the Broker uses the entry for the provider it chose at startup.
type Pin struct {
	// Models is, for each provider name, the model ids the workload may use.
	Models map[string][]string
	// MaxTokens is the ceiling on max_tokens.
	MaxTokens int
	// Shape is the request-shape hash (see Shape) every request must match.
	Shape string
}

// unpinned lists the request fields that Shape leaves out: messages is the
// question text, which a workload may change; model and max_tokens are checked
// against Models and MaxTokens instead.
var unpinned = map[string]bool{"messages": true, "model": true, "max_tokens": true}

// Shape is the request-shape hash of a Messages request body: a SHA-256 over
// every top-level field except messages, model and max_tokens, in a canonical
// form (sorted keys, no insignificant spacing), so a changed system, tools,
// tool_choice, output_config or any other field changes it.
func Shape(body []byte) (string, error) {
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(body, &fields); err != nil || fields == nil {
		return "", errors.New("pin: not a JSON object")
	}
	return ShapeOf(fields)
}

// ShapeOf is Shape for a body already split into its top-level fields.
func ShapeOf(fields map[string]json.RawMessage) (string, error) {
	keys := make([]string, 0, len(fields))
	for k := range fields {
		if !unpinned[k] {
			keys = append(keys, k)
		}
	}
	sort.Strings(keys)
	h := sha256.New()
	for _, k := range keys {
		// Decode and re-encode, so key order inside a field does not matter
		// either. UseNumber keeps numbers exact.
		dec := json.NewDecoder(bytes.NewReader(fields[k]))
		dec.UseNumber()
		var v any
		if err := dec.Decode(&v); err != nil {
			return "", err
		}
		canon, err := json.Marshal(v)
		if err != nil {
			return "", err
		}
		name, _ := json.Marshal(k)
		h.Write(name)
		h.Write([]byte{':'})
		h.Write(canon)
		h.Write([]byte{'\n'})
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}
