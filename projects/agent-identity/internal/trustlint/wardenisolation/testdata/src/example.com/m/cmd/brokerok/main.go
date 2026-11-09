// This command is named like the Broker's but is not it, so it may import the
// Agent and the Eval.
package main

import (
	"example.com/m/internal/agent"
	"example.com/m/internal/eval"
)

func main() { agent.Run(); eval.Do() }
