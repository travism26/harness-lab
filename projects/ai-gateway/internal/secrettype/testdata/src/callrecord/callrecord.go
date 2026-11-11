package callrecord

import "credential"

type Record struct { // want `Call record type Record contains credential type credential.Credential`
	Model string
	Auth  credential.Credential
}

type Clean struct {
	Model string
}
