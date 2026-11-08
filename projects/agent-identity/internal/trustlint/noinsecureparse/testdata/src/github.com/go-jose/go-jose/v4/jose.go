package jose

type JSONWebSignature struct{}

func (obj JSONWebSignature) UnsafePayloadWithoutVerification() []byte { return nil }

func (obj JSONWebSignature) Verify(verificationKey interface{}) ([]byte, error) { return nil, nil }
