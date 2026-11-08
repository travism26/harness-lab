package good

import "github.com/spiffe/go-spiffe/v2/svid/jwtsvid"

func parse() { jwtsvid.ParseAndValidate("x", nil) }
