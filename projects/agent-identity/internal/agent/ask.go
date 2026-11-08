package agent

import (
	"context"
	"crypto/rand"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"strings"
	"time"

	"github.com/travism26/harness-lab/projects/agent-identity/internal/modelclient"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/provider"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/wire"
)

// ModelConfig is the plain config the Agent builds its Model client from, so
// callers never import the model client.
type ModelConfig struct {
	// BaseURL is the Messages API root.
	BaseURL string
	APIKey  string
	// Model is the model id; empty means the provider's default.
	Model string
	// Provider is "anthropic", "openrouter" or "stand-in". It sets the auth
	// style and default model (projects/agent-identity/internal/provider). The Reply footer says
	// "stand-in" for the last and "live" for the others.
	Provider string
}

// DefaultModel is the model id the Model client uses for provider when none is
// given, so a command can print it without importing the Model client.
func DefaultModel(name string) string {
	p, _ := provider.Lookup(name)
	return p.DefaultModel
}

// DefaultWardenTimeout is the deadline on the Warden call when none is given.
const DefaultWardenTimeout = 5 * time.Second

// ReplyID is one of the eight Reply ids.
type ReplyID string

// Reply ids.
const (
	ReplyYes               ReplyID = "yes"
	ReplyNo                ReplyID = "no"
	ReplyDenial            ReplyID = "denial"
	ReplyUnknownPermission ReplyID = "unknown_permission"
	ReplyUnauthenticated   ReplyID = "unauthenticated"
	ReplyNoProposal        ReplyID = "no_proposal"
	ReplyModelUnreachable  ReplyID = "model_unreachable"
	ReplyWardenUnreachable ReplyID = "warden_unreachable"
)

const (
	noProposalText       = "I couldn't turn that into one permission lookup, so no lookup was made. Ask about one person and one permission."
	modelUnreachableText = "The Model couldn't be reached, so no lookup was made."
	denialText           = "I can't answer that: the Warden didn't allow this lookup."
	unauthenticatedText  = "The Warden didn't accept my identity or yours, so no lookup was made."
)

// Reply is the one fixed-template answer to a question, plus what happened on
// the way for the caller's trace.
type Reply struct {
	// ID is one of the eight Reply ids.
	ID ReplyID
	// Text is the printable Reply with its footer. The Model's text is never in it.
	Text string
	// CorrelationID is the run's Correlation ID, also in the footer.
	CorrelationID string
	// Proposal is what the Model proposed, if it proposed.
	Proposal *modelclient.Proposal
	// Status is the Warden's HTTP status, or 0 if no Warden response came back.
	Status int
	// ModelAttempts counts the Model calls made.
	ModelAttempts int
}

// Ask answers one question: the Model proposes, then (only if it did) the Agent
// fetches its JWT-SVID, makes one Lookup and returns a Reply. The error return
// is for a run that could not start: no Model configured, or the JWT-SVID could
// not be fetched.
func (a *Agent) Ask(ctx context.Context, assertion wire.CallerAssertion, question string) (Reply, error) {
	mc := a.cfg.Model
	if mc == nil {
		return Reply{}, errors.New("agent: no Model configured")
	}
	client, err := modelclient.New(modelclient.Config{
		BaseURL: mc.BaseURL, APIKey: mc.APIKey, Model: mc.Model, Provider: mc.Provider,
	})
	if err != nil {
		return Reply{}, fmt.Errorf("agent: %w", err)
	}
	corr := a.newCorrelationID()
	// The assertion's sub is read unverified, only to build the Target, the Reply
	// text and the Audit record; the Warden decides everything.
	tenant, sub := unverifiedSub(assertion)
	rec := AuditRecord{
		CorrelationID: corr, CallerUnverified: sub, Question: question,
		Backend: backendFor(mc.Provider), Model: client.Model(),
	}
	if rec.Backend == backendStandIn {
		// A stand-in run never shows a real model id.
		rec.Model = backendStandIn
	}
	finish := func(r Reply, id ReplyID, text string) (Reply, error) {
		r.ID = id
		r.CorrelationID = corr
		rec.Attempts, rec.WardenStatus, rec.Reply = r.ModelAttempts, r.Status, id
		a.writeAudit(rec)
		r.Text = fmt.Sprintf("%s\n[model: %s · id %s]", text, rec.Backend, corr)
		return r, nil
	}

	res, err := client.Propose(ctx, question)
	out := Reply{ModelAttempts: len(res.Attempts)}
	// Only the audit fields of each attempt are kept, never its Raw reply.
	rec.ModelCalls = modelCalls(res.Attempts)
	if err != nil {
		var f *modelclient.Failure
		if errors.As(err, &f) {
			rec.ModelFailure = &ModelFailure{Kind: string(f.Kind), Code: string(f.Code)}
			if f.Code == modelclient.CodeTextOnly {
				rec.ModelText = truncate(f.Text, maxModelText)
			}
		}
		if f != nil && f.Code == modelclient.CodeProviderError {
			return finish(out, ReplyModelUnreachable, modelUnreachableText)
		}
		return finish(out, ReplyNoProposal, noProposalText)
	}
	p := res.Proposal
	out.Proposal = &p
	rec.Proposal = &Proposal{Target: p.Target, Permission: p.Permission}

	target := p.Target
	if p.Target == "self" {
		target = sub
	} else if tenant != "" {
		target = tenant + "/" + p.Target
	}
	name, in := target, tenant
	if i := strings.IndexByte(target, '/'); i >= 0 {
		in, name = target[:i], target[i+1:]
	}

	timeout := a.cfg.WardenTimeout
	if timeout <= 0 {
		timeout = DefaultWardenTimeout
	}
	resp, err := a.lookup(ctx, assertion, wire.LookupRequest{Target: target, Permission: p.Permission}, corr, timeout)
	var fe fetchError
	if errors.As(err, &fe) {
		rec.Attempts = out.ModelAttempts
		a.writeAudit(rec)
		return Reply{}, err
	}
	out.Status = resp.Status
	unreachable := fmt.Sprintf("The Warden couldn't be reached, so I can't say whether %s holds `%s`.", name, p.Permission)
	// No response, a 5xx, or an unreadable 200 all mean the Warden gave no answer.
	if resp.Status == 0 || resp.Status >= 500 || (err != nil && resp.Status == http.StatusOK) {
		return finish(out, ReplyWardenUnreachable, unreachable)
	}
	switch resp.Status {
	case http.StatusOK:
		if resp.Holds {
			return finish(out, ReplyYes, fmt.Sprintf("Yes. %s holds `%s` in %s through the %s role.", name, p.Permission, in, resp.Role))
		}
		return finish(out, ReplyNo, fmt.Sprintf("No. %s does not hold `%s` in %s.", name, p.Permission, in))
	case http.StatusForbidden:
		return finish(out, ReplyDenial, denialText)
	case http.StatusUnprocessableEntity:
		return finish(out, ReplyUnknownPermission, fmt.Sprintf("The Warden doesn't know the permission `%s`, so no lookup was made.", p.Permission))
	case http.StatusUnauthorized:
		return finish(out, ReplyUnauthenticated, unauthenticatedText)
	}
	return finish(out, ReplyWardenUnreachable, unreachable)
}

func randomID() string {
	b := make([]byte, 16)
	if _, err := rand.Read(b); err != nil {
		panic(err) // crypto/rand does not fail on supported platforms
	}
	return hex.EncodeToString(b)
}

// unverifiedSub returns the Tenant and the whole sub of an assertion, read
// without checking its signature. Both are "" if the sub cannot be read.
func unverifiedSub(a wire.CallerAssertion) (tenant, sub string) {
	parts := strings.Split(string(a), ".")
	if len(parts) != 3 {
		return "", ""
	}
	raw, err := base64.RawURLEncoding.DecodeString(parts[1])
	if err != nil {
		return "", ""
	}
	var claims struct {
		Sub string `json:"sub"`
	}
	if json.Unmarshal(raw, &claims) != nil {
		return "", ""
	}
	i := strings.IndexByte(claims.Sub, '/')
	if i < 0 {
		return "", claims.Sub
	}
	return claims.Sub[:i], claims.Sub
}
