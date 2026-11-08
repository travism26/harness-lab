package nosecretlogs

import (
	"testing"

	"golang.org/x/tools/go/analysis/analysistest"
)

func TestNoSecretLogs(t *testing.T) {
	cfg := Config{TokenTypes: []string{"example.com/m/wire.JWTSVID", "example.com/m/wire.Bearer"}}
	analysistest.Run(t, analysistest.TestData(), New(cfg),
		"example.com/m/bad",
		"example.com/m/good",
	)
}
