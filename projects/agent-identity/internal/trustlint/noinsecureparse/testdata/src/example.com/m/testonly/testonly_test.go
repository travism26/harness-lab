package testonly

import (
	"testing"

	"github.com/spiffe/go-spiffe/v2/svid/jwtsvid"
)

func TestParse(t *testing.T) { jwtsvid.ParseInsecure("x", nil) }
