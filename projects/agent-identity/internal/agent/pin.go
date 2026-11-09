package agent

import (
	"github.com/travism26/harness-lab/projects/agent-identity/internal/modelclient"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/pin"
)

// Pin is the Pin the Broker holds the permission-agent to: one model for each
// provider (today's defaults), the Model client's max_tokens as the ceiling,
// and the hash of the Model client's own request fields. It is computed from
// the Model client's request constants, so the Agent and its Pin cannot drift.
func Pin() pin.Pin { return modelclient.DefaultPin() }

// MessagesRequest is the Messages request body the Agent sends the Broker for a
// question, for a caller (such as the tour) that may not import the Model
// client.
func MessagesRequest(question string) ([]byte, error) { return modelclient.Request(question) }
