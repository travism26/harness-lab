package gateway_test

import (
	"bufio"
	"bytes"
	"encoding/json"
	"io"
	"log"
	"net"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/travism26/harness-lab/projects/ai-gateway/internal/gateway"
)

type seen struct {
	method, uri, host string
	header            http.Header
	body              []byte
	te                []string
}

type rig struct {
	gw    *httptest.Server
	audit string
	errs  *bytes.Buffer
	stand string // the Stand-in service's host:port
	mu    sync.Mutex
	got   []seen
}

func newRig(t *testing.T, upstream http.HandlerFunc) *rig {
	t.Helper()
	r := &rig{audit: filepath.Join(t.TempDir(), "a.jsonl")}
	stand := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, q *http.Request) {
		b, _ := io.ReadAll(q.Body)
		r.mu.Lock()
		r.got = append(r.got, seen{q.Method, q.RequestURI, q.Host, q.Header.Clone(), b, q.TransferEncoding})
		r.mu.Unlock()
		upstream(w, q)
	}))
	t.Cleanup(stand.Close)
	r.stand = strings.TrimPrefix(stand.URL, "http://")
	r.start(t, stand.URL+"/v1/messages")
	return r
}

func (r *rig) start(t *testing.T, upstream string) {
	f, err := os.OpenFile(r.audit, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o600)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { f.Close() })
	u, _ := url.Parse(upstream)
	r.errs = &bytes.Buffer{}
	r.gw = httptest.NewServer(gateway.New(u, f, log.New(r.errs, "", 0)))
	t.Cleanup(r.gw.Close)
}

// records returns the audit lines. The handler appends after the client has
// the whole reply, so it waits briefly for a first line unless none is due.
func (r *rig) records(t *testing.T) []map[string]any {
	t.Helper()
	var b []byte
	for range 200 {
		b, _ = os.ReadFile(r.audit)
		if len(b) > 0 {
			break
		}
		time.Sleep(10 * time.Millisecond)
	}
	var out []map[string]any
	sc := bufio.NewScanner(bytes.NewReader(b))
	sc.Buffer(nil, 1<<24)
	for sc.Scan() {
		var m map[string]any
		if err := json.Unmarshal(sc.Bytes(), &m); err != nil {
			t.Fatal(err)
		}
		out = append(out, m)
	}
	return out
}

func okJSON(w http.ResponseWriter, _ *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Anthropic-Ratelimit-Unified-Status", "allowed")
	w.Write([]byte(`{"id":"m","usage":{"input_tokens":3,"output_tokens":4,"cache_creation_input_tokens":5,"cache_read_input_tokens":6}}`))
}

func post(t *testing.T, url, body string, hdr map[string]string) *http.Response {
	t.Helper()
	req, _ := http.NewRequest("POST", url, strings.NewReader(body))
	if _, ok := hdr["User-Agent"]; !ok {
		req.Header["User-Agent"] = nil // the test client adds none either
	}
	for k, v := range hdr {
		req.Header[k] = []string{v} // keep exact case and absence rules
	}
	resp, err := (&http.Client{Transport: &http.Transport{Proxy: nil, DisableCompression: true}, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}).Do(req)
	if err != nil {
		t.Fatal(err)
	}
	return resp
}

const (
	sentAuth   = "Bearer SENTINEL-AUTH-1"
	sentKey    = "SENTINEL-KEY-2"
	sentCookie = "SENTINEL-COOKIE-3"
)

func TestForwardsAndRecords(t *testing.T) {
	t.Setenv("HTTP_PROXY", "http://127.0.0.1:1")
	r := newRig(t, okJSON)
	body := "{\"model\":\"claude-x\",  \"messages\":[]}\n"
	resp := post(t, r.gw.URL+"/v1/messages?beta=true", body, map[string]string{
		"Authorization":                 sentAuth,
		"X-Api-Key":                     sentKey,
		"Cookie":                        sentCookie,
		"Anthropic-Version":             "2023-06-01",
		"Anthropic-Beta":                "a,b",
		"X-Request-Id":                  "rid",
		"X-Claude-Code-Mystery":         "m",
		"Connection":                    "close, X-Drop",
		"X-Drop":                        "d",
		"X-Claude-Code-Session-Id":      "s1",
		"X-Claude-Code-Request-Class":   "subagent",
		"X-Claude-Code-Parent-Agent-Id": "p1",
		"Content-Type":                  "application/json",
		"User-Agent":                    "claude-cli/1",
	})
	rb, _ := io.ReadAll(resp.Body)
	resp.Body.Close()
	if resp.StatusCode != 200 || resp.Header.Get("Anthropic-Ratelimit-Unified-Status") != "allowed" || resp.Header.Get("Content-Type") != "application/json" {
		t.Fatalf("reply %d %v", resp.StatusCode, resp.Header)
	}
	if len(r.got) != 1 {
		t.Fatalf("upstream saw %d requests", len(r.got))
	}
	g := r.got[0]
	if g.method != "POST" || g.uri != "/v1/messages?beta=true" {
		t.Fatalf("upstream got %s %s", g.method, g.uri)
	}
	if g.host != r.stand || g.host == strings.TrimPrefix(r.gw.URL, "http://") {
		t.Fatalf("host %q", g.host)
	}
	if string(g.body) != body {
		t.Fatalf("body %q", g.body)
	}
	for k, v := range map[string]string{"Authorization": sentAuth, "X-Api-Key": sentKey, "Cookie": sentCookie, "Anthropic-Version": "2023-06-01", "Anthropic-Beta": "a,b", "X-Request-Id": "rid", "X-Claude-Code-Mystery": "m"} {
		if g.header.Get(k) != v {
			t.Errorf("%s = %q", k, g.header.Get(k))
		}
	}
	if g.header.Get("Connection") != "" || g.header.Get("X-Drop") != "" {
		t.Errorf("hop-by-hop forwarded: %v", g.header)
	}
	if g.header.Get("User-Agent") != "claude-cli/1" {
		t.Errorf("User-Agent = %v", g.header["User-Agent"])
	}
	if _, ok := g.header["Accept-Encoding"]; ok {
		t.Errorf("Accept-Encoding added")
	}
	if len(g.te) != 0 {
		t.Errorf("Transfer-Encoding %v", g.te)
	}

	recs := r.records(t)
	if len(recs) != 1 {
		t.Fatalf("%d records", len(recs))
	}
	m := recs[0]
	want := map[string]any{
		"x-claude-code-session-id": "s1", "x-claude-code-agent-id": "", "x-claude-code-parent-agent-id": "p1",
		"model": "claude-x", "request_body": body, "response_body": string(rb), "status": float64(200), "failure": false,
		"x-claude-code-request-class": "subagent",
	}
	for k, v := range want {
		if m[k] != v {
			t.Errorf("%s = %v, want %v", k, m[k], v)
		}
	}
	for _, k := range []string{"x-claude-code-agent-type", "x-claude-code-compaction", "x-claude-code-context-compacted", "x-claude-code-prev-tool-durations", "x-claude-code-prompt-id", "x-claude-code-mystery"} {
		if _, ok := m[k]; ok {
			t.Errorf("key %s present", k)
		}
	}
	if len(m) != 12 {
		t.Errorf("keys: %v", m)
	}
	u := m["usage"].(map[string]any)
	if len(u) != 4 || u["input_tokens"] != 3.0 || u["output_tokens"] != 4.0 || u["cache_creation_input_tokens"] != 5.0 || u["cache_read_input_tokens"] != 6.0 {
		t.Errorf("usage %v", u)
	}
	if _, ok := m["latency_ms"].(float64); !ok {
		t.Errorf("latency")
	}
	raw, _ := os.ReadFile(r.audit)
	for _, s := range []string{sentAuth, sentKey, sentCookie} {
		if bytes.Contains(raw, []byte(s)) {
			t.Errorf("audit file holds %s", s)
		}
		if strings.Contains(r.errs.String(), s) {
			t.Errorf("errlog holds %s", s)
		}
	}
}

func TestMinimalHeadersAndNoModel(t *testing.T) {
	r := newRig(t, okJSON)
	resp := post(t, r.gw.URL+"/v1/messages", "not json", nil)
	resp.Body.Close()
	g := r.got[0]
	if g.uri != "/v1/messages" {
		t.Errorf("uri %q", g.uri)
	}
	if _, ok := g.header["User-Agent"]; ok {
		t.Error("User-Agent added")
	}
	m := r.records(t)[0]
	if m["model"] != "" {
		t.Errorf("model %v", m["model"])
	}
}

func TestOtherRoutesAre404(t *testing.T) {
	r := newRig(t, okJSON)
	for _, c := range [][2]string{{"POST", "/v1/messages/count_tokens"}, {"HEAD", "/api/hello"}, {"GET", "/v1/messages"}, {"POST", "/"}} {
		req, _ := http.NewRequest(c[0], r.gw.URL+c[1], nil)
		resp, err := http.DefaultClient.Do(req)
		if err != nil {
			t.Fatal(err)
		}
		resp.Body.Close()
		if resp.StatusCode != 404 {
			t.Errorf("%v: %d", c, resp.StatusCode)
		}
	}
	if b, _ := os.ReadFile(r.audit); len(r.got) != 0 || len(b) != 0 {
		t.Fatal("upstream request or record for a 404")
	}
}

func TestUpstreamStatusesPassThrough(t *testing.T) {
	for _, code := range []int{401, 429, 302, 500} {
		r := newRig(t, func(w http.ResponseWriter, _ *http.Request) {
			w.Header().Set("Retry-After", "7")
			w.Header().Set("X-Should-Retry", "true")
			w.Header().Set("Location", "/elsewhere")
			w.WriteHeader(code)
			w.Write([]byte("body-" + http.StatusText(code)))
		})
		resp := post(t, r.gw.URL+"/v1/messages", "{}", nil)
		b, _ := io.ReadAll(resp.Body)
		resp.Body.Close()
		if resp.StatusCode != code || string(b) != "body-"+http.StatusText(code) || resp.Header.Get("Retry-After") != "7" || resp.Header.Get("X-Should-Retry") != "true" {
			t.Errorf("%d: got %d %q %v", code, resp.StatusCode, b, resp.Header)
		}
		if code == 302 && resp.Header.Get("Location") != "/elsewhere" {
			t.Errorf("Location lost")
		}
		if len(r.got) != 1 {
			t.Errorf("%d: upstream saw %d requests", code, len(r.got))
		}
		m := r.records(t)[0]
		if m["status"] != float64(code) || m["failure"] != (code >= 300) || m["response_body"] != string(b) {
			t.Errorf("%d: record %v", code, m)
		}
	}
}

func TestUnreachableUpstream(t *testing.T) {
	ln, _ := net.Listen("tcp", "127.0.0.1:0")
	addr := ln.Addr().String()
	ln.Close()
	r := &rig{audit: filepath.Join(t.TempDir(), "a.jsonl")}
	r.start(t, "http://"+addr+"/v1/messages")
	resp := post(t, r.gw.URL+"/v1/messages", `{"model":"REQSECRET"}`, map[string]string{"Authorization": sentAuth})
	b, _ := io.ReadAll(resp.Body)
	resp.Body.Close()
	if resp.StatusCode != 502 || string(b) != "gateway: upstream unreachable\n" {
		t.Fatalf("%d %q", resp.StatusCode, b)
	}
	if bytes.Contains(b, []byte("REQSECRET")) || bytes.Contains(b, []byte("SENTINEL")) {
		t.Fatal("502 body leaks request")
	}
	m := r.records(t)[0]
	raw, _ := os.ReadFile(r.audit)
	for _, s := range []string{sentAuth, "SENTINEL"} {
		if bytes.Contains(raw, []byte(s)) || strings.Contains(r.errs.String(), s) {
			t.Errorf("sentinel %s leaked", s)
		}
	}
	if m["status"] != 502.0 || m["failure"] != true || m["response_body"] != string(b) {
		t.Fatalf("record %v", m)
	}
}

func TestEventStreamCopiedToCompletion(t *testing.T) {
	r := newRig(t, func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		w.Write([]byte("event: x\ndata: {\"usage\":{\"input_tokens\":9}}\n\n"))
	})
	resp := post(t, r.gw.URL+"/v1/messages", "{}", nil)
	b, _ := io.ReadAll(resp.Body)
	resp.Body.Close()
	m := r.records(t)[0]
	if m["response_body"] != string(b) || m["usage"].(map[string]any)["input_tokens"] != 0.0 {
		t.Fatalf("record %v", m)
	}
}

func TestOverlappingCallsMakeTwoLines(t *testing.T) {
	r := newRig(t, okJSON)
	var wg sync.WaitGroup
	for range 20 {
		wg.Go(func() { post(t, r.gw.URL+"/v1/messages", "{}", nil).Body.Close() })
	}
	wg.Wait()
	for range 200 {
		if b, _ := os.ReadFile(r.audit); bytes.Count(b, []byte("\n")) == 20 {
			break
		}
		time.Sleep(10 * time.Millisecond)
	}
	if n := len(r.records(t)); n != 20 {
		t.Fatalf("%d records", n)
	}
}
