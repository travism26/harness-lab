package noinsecureparse

import (
	"testing"

	"golang.org/x/tools/go/analysis/analysistest"
)

func TestNoInsecureParse(t *testing.T) {
	cfg := Config{Funcs: []string{
		"github.com/spiffe/go-spiffe/v2/svid/jwtsvid.ParseInsecure",
		"github.com/spiffe/go-spiffe/v2/exp/svid/witsvid.ParseInsecure",
		"(*github.com/go-jose/go-jose/v4/jwt.JSONWebToken).UnsafeClaimsWithoutVerification",
		"(github.com/go-jose/go-jose/v4.JSONWebSignature).UnsafePayloadWithoutVerification",
	}}
	analysistest.Run(t, analysistest.TestData(), New(cfg),
		"example.com/m/bad",
		"example.com/m/good",
		"example.com/m/testonly",
	)
}
