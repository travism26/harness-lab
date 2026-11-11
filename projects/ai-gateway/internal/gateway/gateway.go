// Package gateway is the Gateway's handler and relay: it forwards one
// POST /v1/messages Call to the Upstream and appends a Call record.
package gateway

import (
	"bytes"
	"encoding/json"
	"io"
	"log"
	"net/http"
	"net/url"
	"strings"
	"time"

	"github.com/travism26/harness-lab/projects/ai-gateway/internal/callrecord"
	"github.com/travism26/harness-lab/projects/ai-gateway/internal/credential"
)

// BadGatewayBody is the body of the 502 the Gateway returns when the Upstream
// cannot be reached. It holds no request byte.
const BadGatewayBody = "gateway: upstream unreachable\n"

var hopByHop = []string{
	"Connection", "Keep-Alive", "Proxy-Authenticate", "Proxy-Authorization",
	"Te", "Trailer", "Transfer-Encoding", "Upgrade",
}

// Handler serves the one Call.
type Handler struct {
	upstream *url.URL
	client   *http.Client
	records  *callrecord.Writer
	errlog   *log.Logger
}

// New returns a Handler that forwards to upstream (the full Messages URL) and
// appends Call records to audit. errlog, if not nil, gets fixed messages only.
func New(upstream *url.URL, audit io.Writer, errlog *log.Logger) *Handler {
	return &Handler{
		upstream: upstream,
		client: &http.Client{
			Transport: &http.Transport{Proxy: nil, DisableCompression: true},
			CheckRedirect: func(*http.Request, []*http.Request) error {
				return http.ErrUseLastResponse
			},
		},
		records: callrecord.NewWriter(audit),
		errlog:  errlog,
	}
}

func (h *Handler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost || r.URL.Path != "/v1/messages" {
		http.NotFound(w, r)
		return
	}
	start := time.Now()
	reqBody, err := io.ReadAll(r.Body)
	if err != nil {
		http.Error(w, "gateway: cannot read request body", http.StatusBadRequest)
		return
	}

	var status int
	var respBody []byte
	var latency time.Duration
	out, err := h.upstreamRequest(r, reqBody)
	var resp *http.Response
	if err == nil {
		resp, err = h.client.Do(out)
	}
	if err != nil {
		status = http.StatusBadGateway
		respBody = []byte(BadGatewayBody)
		w.Header().Set("Content-Type", "text/plain; charset=utf-8")
		w.WriteHeader(status)
		_, _ = w.Write(respBody)
		latency = time.Since(start)
	} else {
		defer resp.Body.Close()
		status = resp.StatusCode
		dropHopByHop(resp.Header)
		for k, vs := range resp.Header {
			w.Header()[k] = vs
		}
		w.WriteHeader(status)
		var buf bytes.Buffer
		// Copied to completion, stream or not; chunk-by-chunk flushing is a later ticket.
		_, _ = io.Copy(io.MultiWriter(w, &buf), resp.Body)
		latency = time.Since(start)
		respBody = buf.Bytes()
	}
	if f, ok := w.(http.Flusher); ok {
		f.Flush()
	}

	rec := callrecord.Record{
		Ts:            start.UTC().Format(time.RFC3339Nano),
		SessionID:     r.Header.Get("x-claude-code-session-id"),
		AgentID:       r.Header.Get("x-claude-code-agent-id"),
		ParentAgentID: r.Header.Get("x-claude-code-parent-agent-id"),
		Model:         modelOf(reqBody),
		RequestBody:   string(reqBody),
		ResponseBody:  string(respBody),
		Status:        status,
		Failure:       status < 200 || status > 299,
		LatencyMS:     latency.Milliseconds(),
		Usage:         usageOf(respBody),

		RequestClass:      hint(r, "x-claude-code-request-class"),
		AgentType:         hint(r, "x-claude-code-agent-type"),
		Compaction:        hint(r, "x-claude-code-compaction"),
		ContextCompacted:  hint(r, "x-claude-code-context-compacted"),
		PrevToolDurations: hint(r, "x-claude-code-prev-tool-durations"),
		PromptID:          hint(r, "x-claude-code-prompt-id"),
	}
	if err := h.records.Append(rec); err != nil && h.errlog != nil {
		h.errlog.Print("gateway: cannot append Call record")
	}
}

func (h *Handler) upstreamRequest(r *http.Request, body []byte) (*http.Request, error) {
	u := *h.upstream
	u.RawQuery = r.URL.RawQuery
	var rd io.Reader = http.NoBody
	if len(body) > 0 {
		rd = bytes.NewReader(body)
	}
	out, err := http.NewRequestWithContext(r.Context(), http.MethodPost, u.String(), rd)
	if err != nil {
		return nil, err
	}
	hdr := r.Header.Clone()
	dropHopByHop(hdr)
	hdr.Del("Content-Length")
	forwarded := credential.Take(hdr)
	forwarded.Apply(hdr)
	if _, ok := hdr["User-Agent"]; !ok {
		// A nil value stops the transport from adding its own User-Agent.
		hdr["User-Agent"] = nil
	}
	out.Header = hdr
	out.Host = u.Host
	return out, nil
}

// dropHopByHop removes the hop-by-hop headers and every name Connection lists.
func dropHopByHop(h http.Header) {
	for _, v := range h.Values("Connection") {
		for name := range strings.SplitSeq(v, ",") {
			if name = strings.TrimSpace(name); name != "" {
				h.Del(name)
			}
		}
	}
	for _, name := range hopByHop {
		h.Del(name)
	}
}

func hint(r *http.Request, name string) *string {
	vs, ok := r.Header[http.CanonicalHeaderKey(name)]
	if !ok || len(vs) == 0 {
		return nil
	}
	return &vs[0]
}

func modelOf(body []byte) string {
	var v struct {
		Model any `json:"model"`
	}
	if json.Unmarshal(body, &v) != nil {
		return ""
	}
	s, _ := v.Model.(string)
	return s
}

func usageOf(body []byte) callrecord.Usage {
	var v struct {
		Usage callrecord.Usage `json:"usage"`
	}
	if json.Unmarshal(body, &v) != nil {
		return callrecord.Usage{}
	}
	return v.Usage
}
