package bad

import (
	"os"

	"example.com/m/broker"
)

const keyName = "ANTHROPIC_API_KEY"

func readsTheChosenKey(c broker.Choice) string {
	_ = broker.Choice{Name: "x", Key: "k"} // want `R5: .*references the chosen provider key example.com/m/broker.Choice.Key`
	return c.Key                           // want `R5: .*references the chosen provider key example.com/m/broker.Choice.Key`
}

func choosesAKey() {
	_, _ = broker.Select("anthropic") // want `R5: .*references the chosen provider key example.com/m/broker.Select`
}

func callsTheLoader() {
	_ = broker.WithDotEnv("x") // want `R5: .*uses the .env loader example.com/m/broker.WithDotEnv`
	_ = broker.DotEnvPath      // want `R5: .*uses the .env loader example.com/m/broker.DotEnvPath`
}

func readsAKeyVariable() {
	_ = os.Getenv("ANTHROPIC_API_KEY")        // want `R5: .*passes the provider key variable ANTHROPIC_API_KEY to os.Getenv`
	_, _ = os.LookupEnv("OPENROUTER_API_KEY") // want `R5: .*passes the provider key variable OPENROUTER_API_KEY to os.LookupEnv`
	_ = os.Getenv(keyName)                    // want `R5: .*passes the provider key variable ANTHROPIC_API_KEY to os.Getenv`
	_ = os.Getenv("OPENROUTER_" + "API_KEY")  // want `R5: .*passes the provider key variable OPENROUTER_API_KEY to os.Getenv`
}
