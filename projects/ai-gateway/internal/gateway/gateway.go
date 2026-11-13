// Package gateway is the Gateway's handler and relay: it forwards one
// POST /v1/messages Call to the Upstream and appends a Call record.
package gateway

import (
	"bytes"
	"encoding/json"
	"io"
	"log"
	"mime"
	"net/http"
	"net/url"
	"strings"
	"time"

	"github.com/travism26/harness-lab/projects/ai-gateway/internal/callrecord"
	"github.com/travism26/harness-lab/projects/ai-gateway/internal/credential"
)

// BadGatewayBody is the body of the 502 the Gateway returns when the Upstream
// cannot be reached. It holds no request byte.
// BadRequestBody is the body of the 400 the Gateway returns when the client
// request body cannot be read.
const BadRequestBody = "gateway: cannot read request body\n"

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
	reqBody, readErr := io.ReadAll(r.Body)

	var status int
	var respBody []byte
	var latency time.Duration
	var usage callrecord.Usage
	var resp *http.Response
	var err error
	if readErr == nil {
		var out *http.Request
		if out, err = h.upstreamRequest(r, reqBody); err == nil {
			resp, err = h.client.Do(out)
		}
	}
	if readErr != nil {
		// A body that cannot be read is still a Call: recorded as a 400, no Upstream request.
		status = http.StatusBadRequest
		respBody = []byte(BadRequestBody)
		w.Header().Set("Content-Type", "text/plain; charset=utf-8")
		w.WriteHeader(status)
		_, _ = w.Write(respBody)
		latency = time.Since(start)
	} else if err != nil {
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
		if isEventStream(resp.Header) {
			var sc sseUsage
			relayStream(w, resp.Body, &buf, &sc)
			usage = sc.usage
		} else {
			_, _ = io.Copy(io.MultiWriter(w, &buf), resp.Body)
			if f, ok := w.(http.Flusher); ok {
				f.Flush()
			}
			usage = usageOf(buf.Bytes())
		}
		latency = time.Since(start)
		respBody = buf.Bytes()
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
		Usage:         usage,

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

func isEventStream(h http.Header) bool {
	mt, _, err := mime.ParseMediaType(h.Get("Content-Type"))
	return err == nil && mt == "text/event-stream"
}

// relayStream writes each read to w and flushes it, appends it to buf, and
// feeds it to sc. It returns when the Upstream ends or the client write fails.
func relayStream(w http.ResponseWriter, body io.Reader, buf *bytes.Buffer, sc *sseUsage) bool {
	f, _ := w.(http.Flusher)
	chunk := make([]byte, 32*1024)
	for {
		n, err := body.Read(chunk)
		if n > 0 {
			buf.Write(chunk[:n])
			sc.feed(chunk[:n])
			if _, werr := w.Write(chunk[:n]); werr != nil {
				return false
			}
			if f != nil {
				f.Flush()
			}
		}
		if err != nil {
			return err == io.EOF
		}
	}
}

// sseUsage tracks the latest value of each token counter in SSE payloads.
type sseUsage struct {
	usage   callrecord.Usage
	pending []byte // an incomplete trailing line
}

func (s *sseUsage) feed(p []byte) {
	s.pending = append(s.pending, p...)
	for {
		i := bytes.IndexByte(s.pending, '\n')
		if i < 0 {
			return
		}
		s.line(bytes.TrimSuffix(s.pending[:i], []byte("\r")))
		s.pending = s.pending[i+1:]
	}
}

func (s *sseUsage) line(l []byte) {
	rest, ok := bytes.CutPrefix(l, []byte("data:"))
	if !ok {
		return
	}
	var v struct {
		Usage   *usageObj `json:"usage"`
		Message *struct {
			Usage *usageObj `json:"usage"`
		} `json:"message"`
	}
	if json.Unmarshal(bytes.TrimSpace(rest), &v) != nil {
		return
	}
	if v.Message != nil {
		s.apply(v.Message.Usage)
	}
	s.apply(v.Usage)
}

type usageObj struct {
	In, Out, Create, Read *int64
}

func (u *usageObj) UnmarshalJSON(b []byte) error {
	var m struct {
		In     *int64 `json:"input_tokens"`
		Out    *int64 `json:"output_tokens"`
		Create *int64 `json:"cache_creation_input_tokens"`
		Read   *int64 `json:"cache_read_input_tokens"`
	}
	if err := json.Unmarshal(b, &m); err != nil {
		return nil // a malformed usage object is ignored
	}
	*u = usageObj{m.In, m.Out, m.Create, m.Read}
	return nil
}

func (s *sseUsage) apply(u *usageObj) {
	if u == nil {
		return
	}
	set := func(dst, src *int64) {
		if src != nil {
			*dst = *src
		}
	}
	set(&s.usage.InputTokens, u.In)
	set(&s.usage.OutputTokens, u.Out)
	set(&s.usage.CacheCreationInputTokens, u.Create)
	set(&s.usage.CacheReadInputTokens, u.Read)
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
