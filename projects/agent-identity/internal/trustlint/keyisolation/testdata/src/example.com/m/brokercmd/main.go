package brokercmd

import (
	"os"

	"example.com/m/broker"
)

// The Broker command may do all of it.
func Run() string {
	_ = broker.WithDotEnv(broker.DotEnvPath)
	c, _ := broker.Select(os.Getenv("ANTHROPIC_API_KEY"))
	v, _ := os.LookupEnv("OPENROUTER_API_KEY")
	return c.Key + v
}
