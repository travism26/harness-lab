package good

import (
	"os"

	"example.com/m/broker"
)

// A local type with a Key field is not the Broker's.
type local struct{ Key string }

func fine(c broker.Choice, l local, name string) string {
	_ = os.Getenv("HOME")
	_, _ = os.LookupEnv("PATH")
	_ = os.Getenv(name) // not a constant: not R5's to judge
	_ = os.Setenv("ANTHROPIC_API_KEY", "canary")
	_ = os.Getenv("ANTHROPIC_API_KEY_FILE_UNRELATED")
	return c.Name + l.Key
}
