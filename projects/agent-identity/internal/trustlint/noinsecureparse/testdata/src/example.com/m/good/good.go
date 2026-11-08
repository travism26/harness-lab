package good

import (
	"github.com/go-jose/go-jose/v4"
	"github.com/spiffe/go-spiffe/v2/svid/jwtsvid"
)

func parse(s jose.JSONWebSignature) {
	jwtsvid.ParseAndValidate("x", nil)
	s.Verify(nil)
}
