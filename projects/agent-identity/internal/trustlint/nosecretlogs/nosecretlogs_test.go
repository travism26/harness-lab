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

// An Audit record type that can hold a token is reported where it is declared,
// so the Audit writer, which only encodes the record, can never write one.
func TestAuditRecordsHoldNoTokens(t *testing.T) {
	cfg := Config{
		TokenTypes: []string{"example.com/m/wire.JWTSVID", "example.com/m/wire.Bearer"},
		AuditRecords: []string{
			"example.com/m/badaudit.AuditRecord",
			"example.com/m/goodaudit.AuditRecord",
		},
	}
	analysistest.Run(t, analysistest.TestData(), New(cfg),
		"example.com/m/badaudit",
		"example.com/m/goodaudit",
	)
}
