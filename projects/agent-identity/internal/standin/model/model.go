// Package model is the stand-in Model: a loopback httptest server that serves a
// queue of scripted Messages-API replies, records each request, and returns 500
// once the script runs out. It is the only Model backend in tests and in check.
package model

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strconv"
	"sync"
)

// Reply is one scripted response.
type Reply struct {
	status int
	body   map[string]any
}

func message(stop string, content ...map[string]any) Reply {
	return Reply{status: http.StatusOK, body: map[string]any{
		"id": "msg_standin", "type": "message", "role": "assistant",
		"stop_reason": stop, "content": content,
		"usage": map[string]any{"input_tokens": 10, "output_tokens": 5},
	}}
}

func toolUse(name string, input any) map[string]any {
	return map[string]any{"type": "tool_use", "id": "toolu_1", "name": name, "input": input}
}

// ToolUse is a well-formed lookup_permission call.
func ToolUse(target, permission string) Reply {
	return ToolUseNamed("lookup_permission", map[string]any{"target": target, "permission": permission})
}

// ToolUseNamed is a tool_use stop with one block of the given name and input.
func ToolUseNamed(name string, input any) Reply {
	return message("tool_use", toolUse(name, input))
}

// ToolUses is a tool_use stop with one lookup_permission block per input.
func ToolUses(inputs ...any) Reply {
	var blocks []map[string]any
	for _, in := range inputs {
		blocks = append(blocks, toolUse("lookup_permission", in))
	}
	return message("tool_use", blocks...)
}

// Text is a text-only reply that ends the turn.
func Text(s string) Reply {
	return message("end_turn", map[string]any{"type": "text", "text": s})
}

// Refusal is a reply the Model refused to give.
func Refusal() Reply { return message("refusal") }

// MaxTokens is a reply cut off by max_tokens.
func MaxTokens() Reply {
	return message("max_tokens", map[string]any{"type": "text", "text": "..."})
}

// Error is a provider error with the given HTTP status.
func Error(status int) Reply {
	return Reply{status: status, body: map[string]any{
		"type": "error", "error": map[string]any{"type": "api_error", "message": "scripted"},
	}}
}

// Server is a running stand-in Model.
type Server struct {
	// URL is the base URL; the client posts to URL + "/v1/messages".
	URL string

	srv      *httptest.Server
	mu       sync.Mutex
	script   []Reply
	requests []Request
}

// Request is one recorded call.
type Request struct {
	Header http.Header
	Body   map[string]any
}

// New starts a stand-in serving the replies in order. Call Close when done.
func New(replies ...Reply) *Server {
	s := &Server{script: replies}
	s.srv = httptest.NewServer(http.HandlerFunc(s.handle))
	s.URL = s.srv.URL
	return s
}

// Close shuts the server down.
func (s *Server) Close() { s.srv.Close() }

// Requests returns the recorded requests in order.
func (s *Server) Requests() []Request {
	s.mu.Lock()
	defer s.mu.Unlock()
	return append([]Request(nil), s.requests...)
}

func (s *Server) handle(w http.ResponseWriter, r *http.Request) {
	raw, _ := io.ReadAll(r.Body)
	var body map[string]any
	_ = json.Unmarshal(raw, &body)
	s.mu.Lock()
	s.requests = append(s.requests, Request{Header: r.Header.Clone(), Body: body})
	if len(s.script) == 0 {
		s.mu.Unlock()
		http.Error(w, "stand-in script exhausted", http.StatusInternalServerError)
		return
	}
	rep := s.script[0]
	s.script = s.script[1:]
	n := len(s.requests)
	s.mu.Unlock()
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Request-Id", "req_standin_"+strconv.Itoa(n))
	w.WriteHeader(rep.status)
	_ = json.NewEncoder(w).Encode(rep.body)
}
