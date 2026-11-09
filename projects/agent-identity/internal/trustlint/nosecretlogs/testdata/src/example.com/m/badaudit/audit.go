package badaudit

import "example.com/m/wire"

// A record that can hold a token is a leak waiting for a writer.
type AuditRecord struct { // want `R3: audit record type example.com/m/badaudit.AuditRecord contains token type example.com/m/wire.JWTSVID`
	ID   string
	Auth detail
}

type detail struct{ Tok wire.JWTSVID }

// Not an audit record: not configured, so not checked.
type Other struct{ Tok wire.JWTSVID }
