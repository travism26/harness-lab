// Package trustlint wires the trust-boundary analyzers R1–R4 to this module's
// real package paths. The configuration is Go literals, not a runtime file.
package trustlint

import (
	"golang.org/x/tools/go/analysis"

	"github.com/travism26/harness-lab/projects/agent-identity/internal/trustlint/modelisolation"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/trustlint/noinsecureparse"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/trustlint/nosecretlogs"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/trustlint/wardenisolation"
)

const prefix = "github.com/travism26/harness-lab/projects/agent-identity"

// The module's trust-boundary packages.
const (
	ModelClient = prefix + "/internal/modelclient"
	Agent       = prefix + "/internal/agent"
	Warden      = prefix + "/internal/warden"
	Broker      = prefix + "/internal/broker"
)

// ModelClientImporters may import ModelClient (R1).
var ModelClientImporters = []string{Agent, prefix + "/internal/eval"}

// WorkloadRules are R2's isolation rules: the Warden imports none of the Agent,
// the Model client and the Broker, and the Broker imports neither the Agent nor
// the Warden.
var WorkloadRules = []wardenisolation.Rule{
	{Name: "the Warden", Isolated: []string{Warden}, Forbidden: []string{Agent, ModelClient, Broker}},
	{Name: "the Broker", Isolated: []string{Broker}, Forbidden: []string{Agent, Warden}},
}

// TokenTypes must never reach a logging or printing sink (R3).
var TokenTypes = []string{
	prefix + "/internal/wire.JWTSVID",
	prefix + "/internal/wire.CallerAssertion",
	prefix + "/internal/wire.Bearer",
}

// InsecureFuncs skip token signature verification and are test-only (R4).
var InsecureFuncs = []string{
	"github.com/spiffe/go-spiffe/v2/svid/jwtsvid.ParseInsecure",
	"github.com/spiffe/go-spiffe/v2/exp/svid/witsvid.ParseInsecure",
	"(*github.com/go-jose/go-jose/v4/jwt.JSONWebToken).UnsafeClaimsWithoutVerification",
	"(github.com/go-jose/go-jose/v4.JSONWebSignature).UnsafePayloadWithoutVerification",
}

// Analyzers returns R1–R4 configured for this module.
func Analyzers() []*analysis.Analyzer {
	return []*analysis.Analyzer{
		modelisolation.New(modelisolation.Config{ModelClient: ModelClient, Allowed: ModelClientImporters}),
		wardenisolation.New(wardenisolation.Config{Rules: WorkloadRules}),
		nosecretlogs.New(nosecretlogs.Config{TokenTypes: TokenTypes}),
		noinsecureparse.New(noinsecureparse.Config{Funcs: InsecureFuncs}),
	}
}
