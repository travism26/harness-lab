package broker_test

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/spiffe/go-spiffe/v2/spiffeid"
	"github.com/spiffe/go-spiffe/v2/svid/jwtsvid"

	"github.com/travism26/harness-lab/projects/agent-identity/internal/broker"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/pin"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/provider"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/standin/workload"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/wire"
)

const (
	brokerAudience = "spiffe://example.com/model-broker"
	wardenAudience = "spiffe://example.com/warden"
	keyCanary      = "sk-CANARY-provider-key-4f2a"
)

var (
	trustDomain = spiffeid.RequireTrustDomainFromString("example.com")
	agentID     = spiffeid.RequireFromString("spiffe://example.com/permission-agent")
	unlistedID  = spiffeid.RequireFromString("spiffe://example.com/unlisted-agent")
)

// upstreamBody is the provider reply the happy path must return byte for byte,
// odd spacing included.
const upstreamBody = `{"id":"msg_1",  "type":"message","stop_reason":"tool_use","content":[],"usage":{"input_tokens":1000,"output_tokens":200}}`

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

// upstream is a counting fake provider.
type upstream struct {
	srv    *httptest.Server
	mu     sync.Mutex
	hits   []*http.Request
	bodies []string
	status int
	body   string
}

func (u *upstream) count() int {
	u.mu.Lock()
	defer u.mu.Unlock()
	return len(u.hits)
}

type fixture struct {
	source *workload.Source
	up     *upstream
	url    string
	audit  syncBuffer
}

type option func(*broker.Config)

func newFixture(t *testing.T, opts ...option) *fixture {
	t.Helper()
	source, err := workload.New(trustDomain)
	if err != nil {
		t.Fatal(err)
	}
	f := &fixture{source: source, up: &upstream{status: 200, body: upstreamBody}}
	f.up.srv = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		raw, _ := io.ReadAll(r.Body)
		f.up.mu.Lock()
		f.up.hits = append(f.up.hits, r)
		f.up.bodies = append(f.up.bodies, string(raw))
		status, body := f.up.status, f.up.body
		f.up.mu.Unlock()
		w.Header().Set("Content-Type", "application/json")
		w.Header().Set("Request-Id", "req_upstream_1")
		w.WriteHeader(status)
		io.WriteString(w, body)
	}))
	t.Cleanup(f.up.srv.Close)
	cfg := broker.Config{
		Audience:    brokerAudience,
		Bundles:     source,
		Allowlist:   []spiffeid.ID{agentID},
		Pins:        map[spiffeid.ID]pin.Pin{agentID: testPin(t)},
		Provider:    provider.Providers["anthropic"],
		Key:         keyCanary,
		UpstreamURL: f.up.srv.URL,
		Audit:       &f.audit,
	}
	for _, o := range opts {
		o(&cfg)
	}
	b, err := broker.New(cfg)
	if err != nil {
		t.Fatal(err)
	}
	srv, err := b.ListenLoopback()
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { srv.Close() })
	f.url = srv.URL
	return f
}

func (f *fixture) fetch(t *testing.T, id spiffeid.ID, audience string) wire.JWTSVID {
	t.Helper()
	wl, err := f.source.Workload(id)
	if err != nil {
		t.Fatal(err)
	}
	svid, err := wl.FetchJWTSVID(context.Background(), jwtsvid.Params{Audience: audience})
	if err != nil {
		t.Fatal(err)
	}
	return wire.JWTSVID(svid.Marshal())
}

func (f *fixture) sign(t *testing.T, id spiffeid.ID, audience []string, iat, exp time.Time) wire.JWTSVID {
	t.Helper()
	token, err := f.source.Sign(workload.Claims{Subject: id, Audience: audience, IssuedAt: iat, Expiry: exp})
	if err != nil {
		t.Fatal(err)
	}
	return token
}

type response struct {
	status int
	body   string
	header http.Header
}

// shapeFields stand in for the Model client's fixed request fields; the Pin the
// fixture gives the permission-agent is the hash of them.
const shapeFields = `"system":"be brief","tools":[{"name":"lookup"}],"tool_choice":{"type":"auto"},"output_config":{"effort":"low"}`

const questionBody = `{"max_tokens":1024,"messages":[{"role":"user","content":"Can Tom approve invoices?"},` + `{"role":"assistant","content":"x"}],` + shapeFields + `}`

// testPin lists each provider's default model, a 1024 ceiling and the shape of
// shapeFields.
func testPin(t *testing.T) pin.Pin {
	t.Helper()
	shape, err := pin.Shape([]byte(`{` + shapeFields + `}`))
	if err != nil {
		t.Fatal(err)
	}
	models := map[string][]string{}
	for name, p := range provider.Providers {
		models[name] = []string{p.DefaultModel}
	}
	models[provider.StandIn.Name] = []string{provider.StandIn.DefaultModel}
	return pin.Pin{Models: models, MaxTokens: 1024, Shape: shape}
}

// post sends a Messages request with the given Authorization ("" sends none).
func (f *fixture) post(t *testing.T, authorization wire.Bearer, corr string) response {
	t.Helper()
	return f.postBody(t, authorization, corr, questionBody)
}

func (f *fixture) postBody(t *testing.T, authorization wire.Bearer, corr, body string) response {
	t.Helper()
	req, err := http.NewRequest(http.MethodPost, f.url+wire.PathMessages, strings.NewReader(body))
	if err != nil {
		t.Fatal(err)
	}
	if authorization != "" {
		req.Header.Set(wire.HeaderAuthorization, string(authorization))
	}
	if corr != "" {
		req.Header.Set(wire.HeaderCorrelationID, corr)
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	raw, err := io.ReadAll(resp.Body)
	if err != nil {
		t.Fatal(err)
	}
	return response{status: resp.StatusCode, body: string(raw), header: resp.Header}
}

func (f *fixture) records(t *testing.T) []broker.AuditRecord {
	t.Helper()
	var out []broker.AuditRecord
	for _, line := range strings.Split(strings.TrimSpace(f.audit.String()), "\n") {
		if line == "" {
			continue
		}
		var r broker.AuditRecord
		dec := json.NewDecoder(strings.NewReader(line))
		dec.DisallowUnknownFields()
		if err := dec.Decode(&r); err != nil {
			t.Fatalf("audit line %q: %v", line, err)
		}
		out = append(out, r)
	}
	return out
}

// noSecrets fails if the response or the Audit log holds the provider key or
// the token that was sent.
func (f *fixture) noSecrets(t *testing.T, r response, token wire.Bearer) {
	t.Helper()
	canaries := []string{keyCanary}
	if tok := strings.TrimPrefix(string(token), wire.BearerPrefix); tok != "" {
		canaries = append(canaries, tok)
		if parts := strings.Split(tok, "."); len(parts) == 3 {
			canaries = append(canaries, parts[2])
		}
	}
	for what, text := range map[string]string{"response body": r.body, "response headers": headerText(r.header), "Audit log": f.audit.String()} {
		for _, c := range canaries {
			if strings.Contains(text, c) {
				t.Errorf("%s contains a secret: %.12s…", what, c)
			}
		}
	}
}

func headerText(h http.Header) string {
	var b strings.Builder
	for k, v := range h {
		b.WriteString(k + ": " + strings.Join(v, ",") + "\n")
	}
	return b.String()
}

func forge(t *testing.T, token wire.JWTSVID, sub string) wire.JWTSVID {
	t.Helper()
	parts := strings.Split(string(token), ".")
	raw, err := base64.RawURLEncoding.DecodeString(parts[1])
	if err != nil {
		t.Fatal(err)
	}
	var claims map[string]any
	if err := json.Unmarshal(raw, &claims); err != nil {
		t.Fatal(err)
	}
	claims["sub"] = sub
	payload, _ := json.Marshal(claims)
	parts[1] = base64.RawURLEncoding.EncodeToString(payload)
	return wire.JWTSVID(strings.Join(parts, "."))
}

func TestHappyPathReturnsTheUpstreamBytesAndTheFourHeaders(t *testing.T) {
	f := newFixture(t)
	const corr = "0123456789abcdef0123456789abcdef"
	token := wire.BearerFor(f.fetch(t, agentID, brokerAudience))

	got := f.post(t, token, corr)

	if got.status != 200 || got.body != upstreamBody {
		t.Fatalf("response = %d %q; want 200 and the upstream's bytes", got.status, got.body)
	}
	for h, want := range map[string]string{
		wire.HeaderBrokerProvider:  "anthropic",
		wire.HeaderBrokerModel:     "claude-haiku-5-5",
		wire.HeaderBrokerCost:      "0.0002",
		wire.HeaderBrokerRequestID: "req_upstream_1",
		wire.HeaderCorrelationID:   corr,
	} {
		if g := got.header.Get(h); g != want {
			t.Errorf("header %s = %q; want %q", h, g, want)
		}
	}
	if f.up.count() != 1 {
		t.Fatalf("upstream saw %d requests; want 1", f.up.count())
	}
	req := f.up.hits[0]
	if req.URL.Path != wire.PathMessages || req.Header.Get("x-api-key") != keyCanary || req.Header.Get("anthropic-version") != broker.AnthropicVersion {
		t.Errorf("upstream request %s with headers %v; want the provider's auth", req.URL.Path, req.Header)
	}
	if req.Header.Get(wire.HeaderAuthorization) != "" || req.Header.Get(wire.HeaderCorrelationID) != "" {
		t.Errorf("the caller's Authorization or Correlation-Id reached the provider: %v", req.Header)
	}
	var sent map[string]any
	if err := json.Unmarshal([]byte(f.up.bodies[0]), &sent); err != nil {
		t.Fatal(err)
	}
	if sent["model"] != "claude-haiku-5-5" {
		t.Errorf("upstream model = %v; the Broker should fill in the provider's default", sent["model"])
	}
	recs := f.records(t)
	if len(recs) != 1 {
		t.Fatalf("%d Audit records; want 1", len(recs))
	}
	r := recs[0]
	if r.CorrelationID != corr || r.SPIFFEID != agentID.String() || r.Provider != "anthropic" || r.Model != "claude-haiku-5-5" ||
		r.Outcome != broker.OutcomeAllowed || r.Status != 200 || r.RequestID != "req_upstream_1" ||
		r.InputTokens != 1000 || r.OutputTokens != 200 || r.Cost != 0.0002 || r.Reason != "" {
		t.Errorf("Audit record = %+v", r)
	}
	f.noSecrets(t, got, token)
}

func TestUnauthenticatedCasesGet401WithTheWardensReasonAndNoUpstreamRequest(t *testing.T) {
	f := newFixture(t)
	now := time.Now().Truncate(time.Second)
	cases := []struct {
		name          string
		authorization wire.Bearer
		want          string
	}{
		{"no header", "", "jwt_svid_missing"},
		{"not a jwt", "Bearer not-a-jwt", "jwt_svid_malformed"},
		{"Basic scheme", "Basic abc", "jwt_svid_malformed"},
		{"forged payload", wire.BearerFor(forge(t, f.fetch(t, agentID, brokerAudience), "spiffe://example.com/someone-else")), "jwt_svid_signature"},
		{"wrong audience", wire.BearerFor(f.fetch(t, agentID, "spiffe://example.com/not-the-broker")), "jwt_svid_audience"},
		{"Bearer with no token", "Bearer ", "jwt_svid_missing"},
		{"both audiences", wire.BearerFor(f.sign(t, agentID, []string{brokerAudience, wardenAudience}, now, now.Add(time.Minute))), "jwt_svid_audience"},
		{"the Warden's audience", wire.BearerFor(f.fetch(t, agentID, wardenAudience)), "jwt_svid_audience"},
		{"expired", wire.BearerFor(f.sign(t, agentID, []string{brokerAudience}, now.Add(-10*time.Minute), now.Add(-5*time.Minute))), "jwt_svid_expired"},
		{"exp 90s ago", wire.BearerFor(f.sign(t, agentID, []string{brokerAudience}, now.Add(-90*time.Second-5*time.Minute), now.Add(-90*time.Second))), "jwt_svid_expired"},
		{"issued 90s in the future", wire.BearerFor(f.sign(t, agentID, []string{brokerAudience}, now.Add(90*time.Second), now.Add(90*time.Second+4*time.Minute))), "jwt_svid_other"},
		{"lifetime too long", wire.BearerFor(f.sign(t, agentID, []string{brokerAudience}, now, now.Add(time.Hour))), "jwt_svid_lifetime"},
		{"no iat", wire.BearerFor(f.sign(t, agentID, []string{brokerAudience}, time.Time{}, now.Add(time.Minute))), "jwt_svid_lifetime"},
	}
	for i, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got := f.post(t, tc.authorization, "")

			if got.status != http.StatusUnauthorized || got.body != `{"reason":"`+tc.want+`"}`+"\n" {
				t.Errorf("response = %d %s; want 401 %s", got.status, got.body, tc.want)
			}
			if n := f.up.count(); n != 0 {
				t.Errorf("%d upstream requests; want 0", n)
			}
			recs := f.records(t)
			if len(recs) != i+1 {
				t.Fatalf("%d Audit records; want %d", len(recs), i+1)
			}
			r := recs[i]
			if r.Outcome != broker.OutcomeRefused || r.Status != 401 || string(r.Reason) != tc.want || r.SPIFFEID != "" {
				t.Errorf("Audit record = %+v; want refused/401/%s/no SPIFFE ID", r, tc.want)
			}
			f.noSecrets(t, got, tc.authorization)
		})
	}
}

func TestJWTSVIDExpiryLeewayBoundaries(t *testing.T) {
	f := newFixture(t)
	now := time.Now().Truncate(time.Second)
	cases := []struct {
		name     string
		iat, exp time.Time
		want     int
	}{
		{"exp 30s ago", now.Add(-30*time.Second - 5*time.Minute), now.Add(-30 * time.Second), 200},
		{"issued 30s in the future", now.Add(30 * time.Second), now.Add(30*time.Second + 4*time.Minute), 200},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got := f.post(t, wire.BearerFor(f.sign(t, agentID, []string{brokerAudience}, tc.iat, tc.exp)), "")
			if got.status != tc.want {
				t.Errorf("status = %d, body %s; want %d", got.status, got.body, tc.want)
			}
		})
	}
}

func TestExactlyMaxLifetimeTokenIsAccepted(t *testing.T) {
	f := newFixture(t)
	now := time.Now().Truncate(time.Second)

	got := f.post(t, wire.BearerFor(f.sign(t, agentID, []string{brokerAudience}, now, now.Add(5*time.Minute))), "")

	if got.status != 200 {
		t.Errorf("status = %d, body %s; want 200", got.status, got.body)
	}
}

func TestVerifiedWorkloadOffTheAllowlistGets403(t *testing.T) {
	f := newFixture(t)
	token := wire.BearerFor(f.fetch(t, unlistedID, brokerAudience))

	got := f.post(t, token, "")

	if got.status != http.StatusForbidden || got.body != `{"reason":"not_allowlisted"}`+"\n" {
		t.Errorf("response = %d %s; want 403 not_allowlisted", got.status, got.body)
	}
	if n := f.up.count(); n != 0 {
		t.Errorf("%d upstream requests; want 0", n)
	}
	recs := f.records(t)
	if len(recs) != 1 || recs[0].Outcome != broker.OutcomeRefused || recs[0].Status != 403 ||
		recs[0].Reason != wire.ReasonNotAllowlisted || recs[0].SPIFFEID != unlistedID.String() {
		t.Errorf("Audit records = %+v", recs)
	}
	f.noSecrets(t, got, token)
}

func TestUpstreamFailureIsA502WithoutTheUpstreamBody(t *testing.T) {
	cases := []struct {
		name       string
		status     int
		wantStatus int
		down       bool
	}{
		{"upstream 401", 401, 401, false},
		{"upstream 429", 429, 429, false},
		{"upstream 500", 500, 500, false},
		{"upstream 302", 302, 302, false},
		{"unreachable", 0, 0, true},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			f := newFixture(t)
			f.up.status, f.up.body = tc.status, `{"error":"`+keyCanary+` is invalid, secret upstream detail"}`
			if tc.down {
				f.up.srv.Close()
			}
			token := wire.BearerFor(f.fetch(t, agentID, brokerAudience))

			got := f.post(t, token, "")

			want := `{"reason":"upstream_error"`
			if tc.wantStatus != 0 {
				want += `,"upstream_status":` + itoa(tc.wantStatus)
			}
			want += "}\n"
			if got.status != http.StatusBadGateway || got.body != want {
				t.Errorf("response = %d %s; want 502 %s", got.status, got.body, want)
			}
			recs := f.records(t)
			if len(recs) != 1 || recs[0].Outcome != broker.OutcomeUpstreamError || recs[0].Status != 502 ||
				recs[0].Reason != wire.ReasonUpstreamError || recs[0].UpstreamStatus != tc.wantStatus || recs[0].SPIFFEID != agentID.String() {
				t.Errorf("Audit records = %+v", recs)
			}
			f.noSecrets(t, got, token)
		})
	}
}

// A reply over the 1 MiB cap is an upstream error with no body passed on, not
// a truncated 200; one exactly at the cap is passed whole.
func TestAnOversizedReplyIsAnUpstreamErrorAndOneAtTheCapIsPassedWhole(t *testing.T) {
	const cap = 1 << 20
	t.Run("one byte over", func(t *testing.T) {
		f := newFixture(t)
		f.up.body = strings.Repeat("a", cap+1)
		token := wire.BearerFor(f.fetch(t, agentID, brokerAudience))

		got := f.post(t, token, "")

		if want := `{"reason":"upstream_error","upstream_status":200}` + "\n"; got.status != http.StatusBadGateway || got.body != want {
			t.Errorf("response = %d (%d bytes) %.80s; want 502 %s", got.status, len(got.body), got.body, want)
		}
		recs := f.records(t)
		if len(recs) != 1 || recs[0].Outcome != broker.OutcomeUpstreamError || recs[0].Status != 502 || recs[0].Reason != wire.ReasonUpstreamError {
			t.Errorf("Audit records = %+v; want one upstream_error record", recs)
		}
		if got.header.Get(wire.HeaderBrokerModel) != "" {
			t.Errorf("a refused reply carries the Broker headers: %v", got.header)
		}
	})
	t.Run("exactly at the cap", func(t *testing.T) {
		f := newFixture(t)
		f.up.body = strings.Repeat("a", cap)
		got := f.post(t, wire.BearerFor(f.fetch(t, agentID, brokerAudience)), "")
		if got.status != 200 || len(got.body) != cap {
			t.Errorf("response = %d (%d bytes); want 200 with %d bytes", got.status, len(got.body), cap)
		}
	})
}

func itoa(n int) string {
	b, _ := json.Marshal(n)
	return string(b)
}

func TestARequestBodyThatIsNotAJSONObjectIsRefusedBeforeTheUpstream(t *testing.T) {
	f := newFixture(t)
	token := wire.BearerFor(f.fetch(t, agentID, brokerAudience))

	got := f.postBody(t, token, "", "not json")

	if got.status != http.StatusBadRequest || got.body != `{"reason":"bad_request"}`+"\n" {
		t.Errorf("response = %d %s; want 400 bad_request", got.status, got.body)
	}
	if n := f.up.count(); n != 0 {
		t.Errorf("%d upstream requests; want 0", n)
	}
	if recs := f.records(t); len(recs) != 1 || recs[0].Outcome != broker.OutcomeRefused || recs[0].Status != 400 {
		t.Errorf("Audit records = %+v", recs)
	}
}

func TestAnInvalidCorrelationIDGetsAFreshOneEchoedAndAudited(t *testing.T) {
	f := newFixture(t)

	got := f.post(t, "", "not-a-correlation-id")

	id := got.header.Get(wire.HeaderCorrelationID)
	if len(id) != 32 || id == "not-a-correlation-id" {
		t.Errorf("echoed Correlation-Id %q; want a fresh 32-hex one", id)
	}
	if recs := f.records(t); len(recs) != 1 || recs[0].CorrelationID != id {
		t.Errorf("Audit records = %+v; want correlation_id %s", recs, id)
	}
}

func TestOpenRouterIsCalledWithBearerAuthAndItsReportedCost(t *testing.T) {
	f := newFixture(t, func(c *broker.Config) { c.Provider = provider.Providers["openrouter"] })
	f.up.body = `{"id":"gen-1","usage":{"input_tokens":10,"output_tokens":5,"cost":0.0123}}`

	got := f.post(t, wire.BearerFor(f.fetch(t, agentID, brokerAudience)), "")

	if got.status != 200 || got.header.Get(wire.HeaderBrokerCost) != "0.0123" || got.header.Get(wire.HeaderBrokerProvider) != "openrouter" {
		t.Errorf("response = %d, cost %q, provider %q", got.status, got.header.Get(wire.HeaderBrokerCost), got.header.Get(wire.HeaderBrokerProvider))
	}
	if h := f.up.hits[0].Header; h.Get("Authorization") != "Bearer "+keyCanary || h.Get("x-api-key") != "" {
		t.Errorf("upstream auth headers = %v; want Bearer", h)
	}
}

func TestNewRefusesAnEmptyAudienceAndMissingPieces(t *testing.T) {
	source, err := workload.New(trustDomain)
	if err != nil {
		t.Fatal(err)
	}
	good := broker.Config{
		Audience: brokerAudience, Bundles: source, Allowlist: []spiffeid.ID{agentID},
		Pins:     map[spiffeid.ID]pin.Pin{agentID: testPin(t)},
		Provider: provider.Providers["anthropic"], Key: keyCanary, UpstreamURL: "http://127.0.0.1:1",
	}
	for name, mut := range map[string]func(*broker.Config){
		"empty audience": func(c *broker.Config) { c.Audience = "" },
		"no bundles":     func(c *broker.Config) { c.Bundles = nil },
		"no key":         func(c *broker.Config) { c.Key = "" },
	} {
		t.Run(name, func(t *testing.T) {
			cfg := good
			mut(&cfg)
			if b, err := broker.New(cfg); err == nil || b != nil {
				t.Errorf("New = %v, %v; want nil Broker and an error", b, err)
			}
		})
	}
	if _, err := broker.New(good); err != nil {
		t.Errorf("New(good) = %v", err)
	}
}

func TestTheStandInProviderNeedsNoKey(t *testing.T) {
	f := newFixture(t, func(c *broker.Config) { c.Provider = provider.StandIn; c.Key = "" })

	got := f.post(t, wire.BearerFor(f.fetch(t, agentID, brokerAudience)), "")

	if got.status != 200 || got.header.Get(wire.HeaderBrokerProvider) != "stand-in" {
		t.Errorf("response = %d, provider %q", got.status, got.header.Get(wire.HeaderBrokerProvider))
	}
	if h := f.up.hits[0].Header; h.Get("x-api-key") != "" || h.Get("Authorization") != "" {
		t.Errorf("the stand-in was sent auth headers: %v", h)
	}
}

func TestDefaultAllowlistNamesThePermissionAgentAndModelEval(t *testing.T) {
	got := map[string]bool{}
	for _, id := range broker.DefaultAllowlist {
		got[id.String()] = true
	}
	if !got["spiffe://example.com/permission-agent"] || !got["spiffe://example.com/model-eval"] || len(got) != 2 {
		t.Errorf("DefaultAllowlist = %v", broker.DefaultAllowlist)
	}
	if broker.ID.String() != brokerAudience {
		t.Errorf("broker.ID = %s", broker.ID)
	}
}

// withBody returns questionBody with the top-level field name set to raw (a
// JSON value), or removed when raw is empty.
func withBody(t *testing.T, name, raw string) string {
	t.Helper()
	var fields map[string]json.RawMessage
	if err := json.Unmarshal([]byte(questionBody), &fields); err != nil {
		t.Fatal(err)
	}
	if raw == "" {
		delete(fields, name)
	} else {
		fields[name] = json.RawMessage(raw)
	}
	out, err := json.Marshal(fields)
	if err != nil {
		t.Fatal(err)
	}
	return string(out)
}

// sentUpstream is the one request body the provider received.
func (f *fixture) sentUpstream(t *testing.T) map[string]any {
	t.Helper()
	if f.up.count() != 1 {
		t.Fatalf("upstream saw %d requests; want 1", f.up.count())
	}
	var sent map[string]any
	if err := json.Unmarshal([]byte(f.up.bodies[0]), &sent); err != nil {
		t.Fatal(err)
	}
	return sent
}

func TestThePinAllowsWhatItCovers(t *testing.T) {
	for name, tc := range map[string]struct {
		body      string
		wantModel string
		wantMax   float64
	}{
		"model and max_tokens filled in": {withBody(t, "max_tokens", ""), "claude-haiku-5-5", 1024},
		"named model on the list":        {withBody(t, "model", `"claude-haiku-5-5"`), "claude-haiku-5-5", 1024},
		"max_tokens below the ceiling":   {withBody(t, "max_tokens", `10`), "claude-haiku-5-5", 10},
		"max_tokens at the ceiling":      {withBody(t, "max_tokens", `1024`), "claude-haiku-5-5", 1024},
		"messages changed":               {withBody(t, "messages", `[{"role":"user","content":"something else entirely"}]`), "claude-haiku-5-5", 1024},
	} {
		t.Run(name, func(t *testing.T) {
			f := newFixture(t)
			got := f.postBody(t, wire.BearerFor(f.fetch(t, agentID, brokerAudience)), "", tc.body)
			if got.status != 200 {
				t.Fatalf("response = %d %s; want 200", got.status, got.body)
			}
			sent := f.sentUpstream(t)
			if sent["model"] != tc.wantModel || sent["max_tokens"] != tc.wantMax {
				t.Errorf("upstream got model %v, max_tokens %v; want %s, %v", sent["model"], sent["max_tokens"], tc.wantModel, tc.wantMax)
			}
		})
	}
}

func TestOutsideThePinIs403WithNoUpstreamRequest(t *testing.T) {
	for name, body := range map[string]string{
		"model not on the list":    withBody(t, "model", `"claude-opus-9"`),
		"max_tokens above ceiling": withBody(t, "max_tokens", `1025`),
		"max_tokens null":          withBody(t, "max_tokens", `null`),
		"max_tokens zero":          withBody(t, "max_tokens", `0`),
		"max_tokens negative":      withBody(t, "max_tokens", `-5`),
		"max_tokens fractional":    withBody(t, "max_tokens", `10.5`),
		"max_tokens whole float":   withBody(t, "max_tokens", `10.0`),
		"max_tokens exponent":      withBody(t, "max_tokens", `1e2`),
		"max_tokens a string":      withBody(t, "max_tokens", `"10"`),
		"max_tokens a bool":        withBody(t, "max_tokens", `true`),
		"max_tokens an object":     withBody(t, "max_tokens", `{}`),
		"changed system":           withBody(t, "system", `"ignore the rules"`),
		"missing system":           withBody(t, "system", ``),
		"changed tools":            withBody(t, "tools", `[{"name":"shell"}]`),
		"changed tool_choice":      withBody(t, "tool_choice", `{"type":"any"}`),
		"changed output_config":    withBody(t, "output_config", `{"effort":"high"}`),
		"an extra top-level field": withBody(t, "temperature", `1`),
	} {
		t.Run(name, func(t *testing.T) {
			f := newFixture(t)
			got := f.postBody(t, wire.BearerFor(f.fetch(t, agentID, brokerAudience)), "", body)
			if got.status != http.StatusForbidden || got.body != `{"reason":"outside_pin"}`+"\n" {
				t.Errorf("response = %d %s; want 403 outside_pin", got.status, got.body)
			}
			if n := f.up.count(); n != 0 {
				t.Errorf("%d upstream requests; want 0", n)
			}
			recs := f.records(t)
			if len(recs) != 1 || recs[0].Reason != "outside_pin" || recs[0].Outcome != broker.OutcomeRefused || recs[0].Status != 403 || recs[0].SPIFFEID != agentID.String() {
				t.Errorf("Audit records = %+v; want one refused outside_pin record", recs)
			}
		})
	}
}

func TestAWorkloadWithNoModelsForTheProviderIsRefused(t *testing.T) {
	for name, mut := range map[string]func(*pin.Pin){
		"no entry for the provider": func(p *pin.Pin) { delete(p.Models, "anthropic") },
		"an empty list":             func(p *pin.Pin) { p.Models["anthropic"] = nil },
	} {
		t.Run(name, func(t *testing.T) {
			f := newFixture(t, func(c *broker.Config) {
				p := testPin(t)
				mut(&p)
				c.Pins = map[spiffeid.ID]pin.Pin{agentID: p}
			})
			// Even a named model is refused.
			got := f.postBody(t, wire.BearerFor(f.fetch(t, agentID, brokerAudience)), "", withBody(t, "model", `"claude-haiku-5-5"`))
			if got.status != http.StatusForbidden || !strings.Contains(got.body, "outside_pin") || f.up.count() != 0 {
				t.Errorf("response = %d %s, %d upstream requests; want 403 outside_pin and none", got.status, got.body, f.up.count())
			}
		})
	}
}

func TestAListedWorkloadWithNoPinIsRefused(t *testing.T) {
	f := newFixture(t, func(c *broker.Config) { c.Pins = nil })
	got := f.post(t, wire.BearerFor(f.fetch(t, agentID, brokerAudience)), "")
	if got.status != http.StatusForbidden || !strings.Contains(got.body, "outside_pin") || f.up.count() != 0 {
		t.Errorf("response = %d %s, %d upstream requests; want 403 outside_pin and none", got.status, got.body, f.up.count())
	}
}

func TestAModelIsNotFilledInWhenThePinListsSeveral(t *testing.T) {
	f := newFixture(t, func(c *broker.Config) {
		p := testPin(t)
		p.Models["anthropic"] = []string{"claude-haiku-5-5", "claude-sonnet-5-5"}
		c.Pins = map[spiffeid.ID]pin.Pin{agentID: p}
	})
	token := wire.BearerFor(f.fetch(t, agentID, brokerAudience))
	if got := f.post(t, token, ""); got.status != http.StatusForbidden {
		t.Errorf("model left out with two listed: %d; want 403", got.status)
	}
	if got := f.postBody(t, token, "", withBody(t, "model", `"claude-sonnet-5-5"`)); got.status != 200 {
		t.Errorf("a listed model: %d; want 200", got.status)
	}
}

// sweepPin is model-eval's Pin: every model in the Eval sweep for each provider.
func sweepPin(t *testing.T) pin.Pin {
	t.Helper()
	p := testPin(t)
	for name, prov := range provider.Providers {
		p.Models[name] = prov.Sweep
	}
	p.Models[provider.StandIn.Name] = provider.StandIn.Sweep
	return p
}

func TestModelEvalIsHeldToItsSweepPin(t *testing.T) {
	evalID := spiffeid.RequireFromString("spiffe://example.com/model-eval")
	for name, tc := range map[string]struct {
		body       string
		wantStatus int
		wantReason string
		wantModel  string
	}{
		"Haiku":                  {withBody(t, "model", `"claude-haiku-5-5"`), 200, "", "claude-haiku-5-5"},
		"Sonnet":                 {withBody(t, "model", `"claude-sonnet-5-5"`), 200, "", "claude-sonnet-5-5"},
		"Opus":                   {withBody(t, "model", `"claude-opus-5-5"`), 200, "", "claude-opus-5-5"},
		"a model off its list":   {withBody(t, "model", `"claude-opus-9"`), 403, "outside_pin", ""},
		"no model: several Pins": {questionBody, 403, "outside_pin", ""},
	} {
		t.Run(name, func(t *testing.T) {
			f := newFixture(t, func(c *broker.Config) {
				c.Allowlist = []spiffeid.ID{agentID, evalID}
				c.Pins = map[spiffeid.ID]pin.Pin{agentID: testPin(t), evalID: sweepPin(t)}
			})
			got := f.postBody(t, wire.BearerFor(f.fetch(t, evalID, brokerAudience)), "", tc.body)
			if got.status != tc.wantStatus {
				t.Fatalf("response = %d %s; want %d", got.status, got.body, tc.wantStatus)
			}
			if tc.wantReason != "" {
				if got.body != `{"reason":"`+tc.wantReason+`"}`+"\n" || f.up.count() != 0 {
					t.Errorf("body %q, %d upstream requests; want %s and none", got.body, f.up.count(), tc.wantReason)
				}
				return
			}
			if sent := f.sentUpstream(t); sent["model"] != tc.wantModel {
				t.Errorf("upstream model = %v; want %s", sent["model"], tc.wantModel)
			}
		})
	}
}

func TestThePinIsHeldPerWorkload(t *testing.T) {
	other := spiffeid.RequireFromString("spiffe://example.com/model-eval")
	f := newFixture(t, func(c *broker.Config) {
		c.Allowlist = []spiffeid.ID{agentID, other}
		strict := testPin(t)
		strict.MaxTokens = 10
		c.Pins = map[spiffeid.ID]pin.Pin{agentID: testPin(t), other: strict}
	})
	if got := f.post(t, wire.BearerFor(f.fetch(t, agentID, brokerAudience)), ""); got.status != 200 {
		t.Errorf("permission-agent: %d; want 200", got.status)
	}
	if got := f.post(t, wire.BearerFor(f.fetch(t, other, brokerAudience)), ""); got.status != http.StatusForbidden {
		t.Errorf("model-eval with a lower ceiling: %d; want 403", got.status)
	}
}

func TestTwoAuthorizationHeadersAreRefusedWithNoUpstreamRequest(t *testing.T) {
	f := newFixture(t)
	good := string(wire.BearerFor(f.fetch(t, agentID, brokerAudience)))
	req, err := http.NewRequest(http.MethodPost, f.url+wire.PathMessages, strings.NewReader(questionBody))
	if err != nil {
		t.Fatal(err)
	}
	req.Header.Add(wire.HeaderAuthorization, good)
	req.Header.Add(wire.HeaderAuthorization, good)

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	raw, _ := io.ReadAll(resp.Body)
	resp.Body.Close()

	if resp.StatusCode != http.StatusUnauthorized || string(raw) != `{"reason":"jwt_svid_malformed"}`+"\n" {
		t.Errorf("response = %d %s; want 401 jwt_svid_malformed", resp.StatusCode, raw)
	}
	if n := f.up.count(); n != 0 {
		t.Errorf("%d upstream requests; want 0", n)
	}
}
