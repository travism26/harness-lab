package jwtsvid

type SVID struct{}

func ParseInsecure(token string, audience []string) (*SVID, error) { return nil, nil }

func ParseAndValidate(token string, audience []string) (*SVID, error) { return nil, nil }
