// Package modelrequest holds the Messages request the Model client sends: its
// system prompt, its lookup_permission tool, tool_choice, output_config and
// max_tokens. They are a leaf shared by the Model client, which sends them, and
// by the Pin the Broker holds a workload to, which hashes them, so the Broker
// process can know what a request must look like without linking the Model
// client, the Agent or the Eval (trustlint R1 and R2;
// projects/agent-identity/docs/adr/0004-the-provider-key-lives-only-in-the-broker.md).
package modelrequest

import "encoding/json"

const (
	// ToolName is the one tool the Model may call.
	ToolName = "lookup_permission"
	// MaxTokens is the Client's max_tokens, and the ceiling the Pin sets.
	MaxTokens = 1024
)

const system = "You turn one question about who holds a permission into one call of the " +
	"lookup_permission tool. target is the name of the person or agent from the question, or " +
	"\"self\" when the question is about the asker. permission is resource:action in lowercase " +
	"letters, such as invoice:approve. The resource is singular: invoices becomes invoice, " +
	"permissions becomes permission. Two actions are known: read, which also covers view, see " +
	"and look up, and approve, which also covers sign off. Write any other permission as asked, " +
	"without mapping it onto these. Call the tool exactly once. If the question cannot be " +
	"turned into one lookup, do not call it."

var toolDef = map[string]any{
	"name":        ToolName,
	"description": "Look up whether one target holds one permission.",
	"strict":      true,
	"input_schema": map[string]any{
		"type": "object",
		"properties": map[string]any{
			"target":     map[string]any{"type": "string", "description": "a name from the question in lowercase (Tom becomes tom), or self"},
			"permission": map[string]any{"type": "string", "description": "resource:action, lowercase"},
		},
		"required":             []string{"target", "permission"},
		"additionalProperties": false,
	},
}

// Fields is every field of the Messages request but the model, which the Client
// or the Broker adds. The Pin's request-shape hash is computed from these same
// constants, so a change here moves the hash with it.
func Fields(messages []any) map[string]any {
	return map[string]any{
		"max_tokens":    MaxTokens,
		"system":        system,
		"messages":      messages,
		"tools":         []any{toolDef},
		"tool_choice":   map[string]any{"type": "auto", "disable_parallel_tool_use": true},
		"output_config": map[string]any{"effort": "low"},
	}
}

// Body is the Messages request body the Client sends the Broker for a
// question's first call: no model, no key.
func Body(question string) ([]byte, error) {
	return json.Marshal(Fields([]any{map[string]any{"role": "user", "content": question}}))
}
