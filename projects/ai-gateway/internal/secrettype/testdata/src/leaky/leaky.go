package leaky

import (
	"fmt"
	"log"
	"log/slog"

	"credential"
)

type holder struct{ c credential.Credential }

func f(c credential.Credential, s string) {
	log.Println(c)           // want `passed to log.Println`
	slog.Info("x", "k", c)   // want `passed to log/slog.Info`
	_ = fmt.Sprintf("%s", c) // want `passed to fmt.Sprintf`
	fmt.Println(holder{c})   // want `passed to fmt.Println`
	fmt.Println(s)
	_ = string(c)
}
