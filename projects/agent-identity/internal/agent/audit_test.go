package agent_test

import (
	"bytes"
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"math/big"
	"net"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/spiffe/go-spiffe/v2/spiffeid"
	"github.com/spiffe/go-spiffe/v2/svid/jwtsvid"

	"github.com/travism26/harness-lab/projects/agent-identity/internal/agent"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/login"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/standin/model"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/standin/workload"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/warden"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/wire"
)

type syncBuffer struct {
	mu  sync.Mutex
	buf bytes.Buffer
}

func (b *syncBuffer) Write(p []byte) (int, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.buf.Write(p)
}

func (b *syncBuffer) String() string {
	b.mu.Lock()
	defer b.mu.Unlock()
	return b.buf.String()
}

// capturing records every JWT-SVID the Agent fetched, so a test knows the bytes.
type capturing struct {
	inner agent.SVIDSource
	mu    sync.Mutex
	svids []string
}

func (c *capturing) FetchJWTSVID(ctx context.Context, p jwtsvid.Params) (*jwtsvid.SVID, error) {
	s, err := c.inner.FetchJWTSVID(ctx, p)
	if err == nil {
		c.mu.Lock()
		c.svids = append(c.svids, s.Marshal())
		c.mu.Unlock()
	}
	return s, err
}

// auditEnv is a real Warden with both Audit logs captured.
type auditEnv struct {
	source      *workload.Source
	login       *login.Login
	url         string
	agentLog    syncBuffer
	wardenLog   syncBuffer
	fetched     *capturing
	assertions  []wire.CallerAssertion
	modelAPIKey string
	// The test's own signing keys, for the canary.
	loginKey, sourceKey *ecdsa.PrivateKey
}

func newAuditEnv(t *testing.T) *auditEnv {
	t.Helper()
	sourceKey, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	loginKey, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	source, err := workload.NewWithKey(trustDomain, sourceKey)
	if err != nil {
		t.Fatal(err)
	}
	lg, err := login.NewWithKey(nil, loginKey)
	if err != nil {
		t.Fatal(err)
	}
	e := &auditEnv{source: source, login: lg, modelAPIKey: "CANARY-API-KEY-7c1e", loginKey: loginKey, sourceKey: sourceKey}
	w, err := warden.New(warden.Config{
		Audience: wardenAudience, Bundles: source,
		Allowlist: []spiffeid.ID{listedID}, LoginKey: lg.PublicKey(), Audit: &e.wardenLog,
	})
	if err != nil {
		t.Fatal(err)
	}
	srv, err := w.ListenLoopback()
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { srv.Close() })
	e.url = srv.URL
	return e
}

// agent builds an Agent for id against url, with the model stand-in m (or none).
// opts adjust the Config last, to swap the Model config or the JWT-SVID source.
func (e *auditEnv) agent(t *testing.T, id spiffeid.ID, url string, m *model.Server, timeout time.Duration, opts ...func(*agent.Config)) *agent.Agent {
	t.Helper()
	wl, err := e.source.Workload(id)
	if err != nil {
		t.Fatal(err)
	}
	e.fetched = &capturing{inner: wl}
	cfg := agent.Config{WardenURL: url, Audience: wardenAudience, Source: e.fetched, WardenTimeout: timeout, Audit: &e.agentLog}
	if m != nil {
		cfg.Model = &agent.ModelConfig{BaseURL: m.URL, APIKey: e.modelAPIKey, Provider: "stand-in", Model: "stand-in-model"}
	}
	for _, o := range opts {
		o(&cfg)
	}
	a, err := agent.New(cfg)
	if err != nil {
		t.Fatal(err)
	}
	return a
}

// tokenCanaries are every Caller assertion the test signed and every JWT-SVID
// the Agent fetched, whole and by signature.
func (e *auditEnv) tokenCanaries() []string {
	var canaries []string
	for _, as := range e.assertions {
		canaries = append(canaries, string(as), strings.Split(string(as), ".")[2])
	}
	e.fetched.mu.Lock()
	defer e.fetched.mu.Unlock()
	for _, s := range e.fetched.svids {
		canaries = append(canaries, s, strings.Split(s, ".")[2])
	}
	return canaries
}

// closedURL is a loopback URL nothing listens on; deadURL accepts connections
// and never answers.
func closedURL(t *testing.T) string {
	t.Helper()
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	u := "http://" + l.Addr().String()
	l.Close()
	return u
}

func deadURL(t *testing.T) string {
	t.Helper()
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { l.Close() })
	return "http://" + l.Addr().String()
}

func (e *auditEnv) assertion(t *testing.T, caller string, id spiffeid.ID) wire.CallerAssertion {
	t.Helper()
	as, err := e.login.Sign(caller, wardenAudience, id.String())
	if err != nil {
		t.Fatal(err)
	}
	e.assertions = append(e.assertions, as)
	return as
}

func decodeLines[T any](t *testing.T, log string) []T {
	t.Helper()
	var out []T
	for _, line := range strings.Split(strings.TrimSpace(log), "\n") {
		if line == "" {
			continue
		}
		dec := json.NewDecoder(strings.NewReader(line))
		dec.DisallowUnknownFields()
		var r T
		if err := dec.Decode(&r); err != nil {
			t.Fatalf("audit line %q: %v", line, err)
		}
		out = append(out, r)
	}
	return out
}

func (e *auditEnv) agentRecords(t *testing.T) []agent.AuditRecord {
	return decodeLines[agent.AuditRecord](t, e.agentLog.String())
}

func (e *auditEnv) wardenRecords(t *testing.T) []warden.AuditRecord {
	return decodeLines[warden.AuditRecord](t, e.wardenLog.String())
}

func TestAskWritesOneAgentRecordWithTheProposalAndTheWardensRecordShareItsID(t *testing.T) {
	e := newAuditEnv(t)
	m := model.New(model.ToolUse("tom", "invoice:approve"))
	defer m.Close()
	a := e.agent(t, listedID, e.url, m, 0)
	r, err := a.Ask(context.Background(), e.assertion(t, "acme/alice", listedID), "Can Tom approve invoices?")
	if err != nil {
		t.Fatal(err)
	}

	recs := e.agentRecords(t)
	if len(recs) != 1 {
		t.Fatalf("got %d Agent records; want 1", len(recs))
	}
	g := recs[0]
	if len(g.CorrelationID) != 32 || g.CorrelationID != r.CorrelationID || g.CallerUnverified != "acme/alice" ||
		g.Question != "Can Tom approve invoices?" || g.Backend != "stand-in" || g.Model != "stand-in" || g.Attempts != 1 ||
		g.Proposal == nil || g.Proposal.Target != "tom" || g.Proposal.Permission != "invoice:approve" || g.ModelFailure != nil ||
		g.ModelText != "" || g.WardenStatus != 200 || g.Reply != agent.ReplyYes || g.TS.IsZero() {
		t.Errorf("record = %+v", g)
	}
	if len(g.ModelCalls) != 1 || g.ModelCalls[0].Provider != "stand-in" || g.ModelCalls[0].Cost != 0 {
		t.Errorf("model calls = %+v", g.ModelCalls)
	}
	w := e.wardenRecords(t)
	if len(w) != 1 || w[0].CorrelationID != g.CorrelationID {
		t.Errorf("Warden records %+v; Agent ID %s", w, g.CorrelationID)
	}
}

func TestEveryOutcomeHasOneRecordPerServiceAndNoCanaryInEitherLog(t *testing.T) {
	e := newAuditEnv(t)
	unreachableURL := deadURL(t)

	long := strings.Repeat("a", 500) + "TAILBEYOND500" + strings.Repeat("z", 100)
	cases := []struct {
		name     string
		id       spiffeid.ID
		caller   string
		url      string
		timeout  time.Duration
		script   []model.Reply
		reply    agent.ReplyID
		wardened bool // the Warden answers, so it writes a record
	}{
		{"yes", listedID, "acme/alice", e.url, 0, []model.Reply{model.ToolUse("tom", "invoice:approve")}, agent.ReplyYes, true},
		{"no", listedID, "acme/alice", e.url, 0, []model.Reply{model.ToolUse("bob", "invoice:approve")}, agent.ReplyNo, true},
		{"denial", listedID, "acme/bob", e.url, 0, []model.Reply{model.ToolUse("tom", "invoice:approve")}, agent.ReplyDenial, true},
		{"unknown permission", listedID, "acme/alice", e.url, 0, []model.Reply{model.ToolUse("tom", "invoices:approve")}, agent.ReplyUnknownPermission, true},
		{"unauthenticated", listedID, "acme/nobody", e.url, 0, []model.Reply{model.ToolUse("tom", "invoice:approve")}, agent.ReplyUnauthenticated, true},
		{"agent not allowed", unlistedID, "acme/alice", e.url, 0, []model.Reply{model.ToolUse("tom", "invoice:approve")}, agent.ReplyDenial, true},
		{"no proposal text", listedID, "acme/alice", e.url, 0, []model.Reply{model.Text(long)}, agent.ReplyNoProposal, false},
		{"no proposal refusal", listedID, "acme/alice", e.url, 0, []model.Reply{model.Refusal()}, agent.ReplyNoProposal, false},
		{"retry then proposal", listedID, "acme/alice", e.url, 0, []model.Reply{model.ToolUse("Tom", "invoice:approve"), model.ToolUse("tom", "invoice:approve")}, agent.ReplyYes, true},
		{"model unreachable", listedID, "acme/alice", e.url, 0, []model.Reply{model.Error(500)}, agent.ReplyModelUnreachable, false},
		{"warden unreachable", listedID, "acme/alice", unreachableURL, 50 * time.Millisecond, []model.Reply{model.ToolUse("tom", "invoice:approve")}, agent.ReplyWardenUnreachable, false},
	}
	replies := map[string]agent.Reply{}
	for _, tc := range cases {
		m := model.New(tc.script...)
		a := e.agent(t, tc.id, tc.url, m, tc.timeout)
		r, err := a.Ask(context.Background(), e.assertion(t, tc.caller, tc.id), "question "+tc.name)
		m.Close()
		if err != nil {
			t.Fatalf("%s: %v", tc.name, err)
		}
		if r.ID != tc.reply {
			t.Errorf("%s: reply %s; want %s", tc.name, r.ID, tc.reply)
		}
		replies[tc.name] = r
	}

	agentRecs := map[string][]agent.AuditRecord{}
	for _, g := range e.agentRecords(t) {
		agentRecs[g.CorrelationID] = append(agentRecs[g.CorrelationID], g)
	}
	wardenRecs := map[string][]warden.AuditRecord{}
	for _, w := range e.wardenRecords(t) {
		wardenRecs[w.CorrelationID] = append(wardenRecs[w.CorrelationID], w)
	}
	for _, tc := range cases {
		id := replies[tc.name].CorrelationID
		if len(agentRecs[id]) != 1 {
			t.Errorf("%s: %d Agent records", tc.name, len(agentRecs[id]))
		}
		want := 0
		if tc.wardened {
			want = 1
		}
		if len(wardenRecs[id]) != want {
			t.Errorf("%s: %d Warden records; want %d", tc.name, len(wardenRecs[id]), want)
		}
	}

	// Details that differ by outcome.
	textOnly := agentRecs[replies["no proposal text"].CorrelationID][0]
	if textOnly.ModelFailure == nil || textOnly.ModelFailure.Kind != "fatal" || textOnly.ModelFailure.Code != "text_only" ||
		textOnly.Proposal != nil || textOnly.ModelText != strings.Repeat("a", 500) || textOnly.WardenStatus != 0 {
		t.Errorf("text-only record = %+v", textOnly)
	}
	if rf := agentRecs[replies["no proposal refusal"].CorrelationID][0]; rf.ModelText != "" || rf.ModelFailure == nil || rf.ModelFailure.Code != "refusal" {
		t.Errorf("refusal record = %+v", rf)
	}
	if retry := agentRecs[replies["retry then proposal"].CorrelationID][0]; retry.Attempts != 2 || len(retry.ModelCalls) != 2 || retry.Proposal == nil {
		t.Errorf("retry record = %+v", retry)
	}
	if un := agentRecs[replies["warden unreachable"].CorrelationID][0]; un.WardenStatus != 0 || un.Reply != agent.ReplyWardenUnreachable {
		t.Errorf("warden-unreachable record = %+v", un)
	}
	if w := wardenRecs[replies["agent not allowed"].CorrelationID][0]; w.Outcome != warden.OutcomeAgentNotAllowed || w.Caller != "" {
		t.Errorf("agent-not-allowed record = %+v", w)
	}
	if w := wardenRecs[replies["unauthenticated"].CorrelationID][0]; w.Reason != warden.ReasonAssertionUnknownCaller {
		t.Errorf("unauthenticated record = %+v", w)
	}

	// Canary: no token or key byte, and nothing of the raw Model reply, is in either log.
	canaries := []string{e.modelAPIKey, "TAILBEYOND500"}
	// The Login's and the Workload stand-in's signing keys, in the encodings a
	// log could carry: base64url (JWK), base64, hex and decimal.
	for _, k := range []*ecdsa.PrivateKey{e.loginKey, e.sourceKey} {
		d, err := k.Bytes()
		if err != nil {
			t.Fatal(err)
		}
		canaries = append(canaries,
			base64.RawURLEncoding.EncodeToString(d), base64.StdEncoding.EncodeToString(d),
			hex.EncodeToString(d), new(big.Int).SetBytes(d).String())
	}
	canaries = append(canaries, e.tokenCanaries()...)
	for name, log := range map[string]string{"agent": e.agentLog.String(), "warden": e.wardenLog.String()} {
		for _, c := range canaries {
			if strings.Contains(log, c) {
				t.Errorf("%s log contains %q", name, c)
			}
		}
		for _, raw := range []string{"stop_reason", `"content"`, "tool_use"} {
			if strings.Contains(log, raw) {
				t.Errorf("%s log contains raw Model reply text %q", name, raw)
			}
		}
	}
}

func TestCorrelationIDIsThirtyTwoLowercaseHexByDefault(t *testing.T) {
	e := newAuditEnv(t)
	m := model.New(model.ToolUse("tom", "invoice:approve"))
	defer m.Close()
	r, err := e.agent(t, listedID, e.url, m, 0).Ask(context.Background(), e.assertion(t, "acme/alice", listedID), "q")
	if err != nil {
		t.Fatal(err)
	}
	if len(r.CorrelationID) != 32 || strings.Trim(r.CorrelationID, "0123456789abcdef") != "" {
		t.Errorf("Correlation ID %q", r.CorrelationID)
	}
}

func TestScriptedLookupWritesAnAgentRecordToo(t *testing.T) {
	e := newAuditEnv(t)
	a := e.agent(t, listedID, e.url, nil, 0)
	_, err := a.Lookup(context.Background(), e.assertion(t, "acme/alice", listedID), wire.LookupRequest{Target: "acme/tom", Permission: "invoice:approve"})
	if err != nil {
		t.Fatal(err)
	}
	recs, w := e.agentRecords(t), e.wardenRecords(t)
	if len(recs) != 1 || len(w) != 1 || recs[0].CorrelationID != w[0].CorrelationID || recs[0].WardenStatus != 200 ||
		recs[0].CallerUnverified != "acme/alice" || recs[0].Reply != "" || recs[0].Proposal != nil {
		t.Errorf("agent %+v; warden %+v", recs, w)
	}
}

func TestUnknownPermissionReplyAgreesWithTheWardensAuditRecord(t *testing.T) {
	e := newAuditEnv(t)
	m := model.New(model.ToolUse("tom", "invoices:approve"))
	defer m.Close()
	r, err := e.agent(t, listedID, e.url, m, 0).Ask(context.Background(), e.assertion(t, "acme/alice", listedID), "Does Tom hold invoices:approve?")
	if err != nil {
		t.Fatal(err)
	}
	want := "The Warden doesn't know the permission `invoices:approve`, so it couldn't answer whether `tom` holds it in `acme`."
	if r.ID != agent.ReplyUnknownPermission || r.Status != 422 || body(r) != want {
		t.Errorf("got %s %d %q", r.ID, r.Status, r.Text)
	}
	g, w := e.agentRecords(t), e.wardenRecords(t)
	if len(g) != 1 || len(w) != 1 || g[0].CorrelationID != r.CorrelationID || w[0].CorrelationID != r.CorrelationID {
		t.Fatalf("agent %+v; warden %+v; Reply correlation ID %s", g, w, r.CorrelationID)
	}
	if g[0].WardenStatus != 422 || g[0].Reply != agent.ReplyUnknownPermission ||
		w[0].Status != 422 || w[0].Outcome != warden.OutcomeUnknownPermission || w[0].Target != "acme/tom" || w[0].Permission != "invoices:approve" {
		t.Errorf("agent %+v; warden %+v", g[0], w[0])
	}
}

// "No lookup was made" means no accepted Lookup: the no-Proposal and
// Model-unreachable paths send no request, and a 401 records warden_status 401.
// Replies are checked by exact string.
func TestNoLookupWasMadeRepliesMatchTheAgentAuditRecord(t *testing.T) {
	cases := []struct {
		name   string
		caller string
		script model.Reply
		reply  agent.ReplyID
		status int
		text   string
	}{
		{"no proposal", "acme/alice", model.Text("hi"), agent.ReplyNoProposal, 0,
			"I couldn't turn that into one permission lookup, so no lookup was made. Ask about one person and one permission."},
		{"model unreachable", "acme/alice", model.Error(500), agent.ReplyModelUnreachable, 0,
			"The Model couldn't be reached, so no lookup was made."},
		{"unauthenticated", "acme/nobody", model.ToolUse("tom", "invoice:approve"), agent.ReplyUnauthenticated, 401,
			"The Warden didn't accept my identity or yours, so no lookup was made."},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			e := newAuditEnv(t)
			m := model.New(tc.script)
			defer m.Close()
			r, err := e.agent(t, listedID, e.url, m, 0).Ask(context.Background(), e.assertion(t, tc.caller, listedID), "q")
			if err != nil {
				t.Fatal(err)
			}
			if body(r) != tc.text {
				t.Errorf("Reply %q; want %q", body(r), tc.text)
			}
			g := e.agentRecords(t)
			if len(g) != 1 || g[0].Reply != tc.reply || g[0].WardenStatus != tc.status {
				t.Errorf("agent record %+v; want %s status %d", g, tc.reply, tc.status)
			}
		})
	}
}
