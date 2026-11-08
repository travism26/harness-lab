package jwt

type JSONWebToken struct{}

func (t *JSONWebToken) UnsafeClaimsWithoutVerification(dest ...interface{}) error { return nil }
