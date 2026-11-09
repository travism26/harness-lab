package modelclient_test

import (
	"context"
	"encoding/json"
	"errors"
	"strings"
	"testing"

	"github.com/travism26/harness-lab/projects/agent-identity/internal/modelclient"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/standin/model"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/wire"
)

func testSVID(context.Context) (wire.JWTSVID, error) { return "svid", nil }

func newClient(t *testing.T, s *model.Server) *modelclient.Client {
	t.Helper()
	c, err := modelclient.New(modelclient.Config{BaseURL: s.URL, SVID: testSVID})
	if err != nil {
		t.Fatal(err)
	}
	return c
}

func propose(t *testing.T, c *modelclient.Client) (modelclient.Result, error) {
	t.Helper()
	return c.Propose(context.Background(), "Does tom hold invoice:approve?")
}

func TestProposalAndRequestShape(t *testing.T) {
	s := model.New(model.ToolUse("tom", "invoice:approve"))
	defer s.Close()
	res, err := propose(t, newClient(t, s))
	if err != nil {
		t.Fatal(err)
	}
	if res.Proposal != (modelclient.Proposal{Target: "tom", Permission: "invoice:approve"}) {
		t.Fatalf("proposal = %+v", res.Proposal)
	}
	if len(res.Attempts) != 1 || res.Attempts[0].Cost != 0 || res.Attempts[0].RequestID == "" {
		t.Fatalf("attempts = %+v", res.Attempts)
	}
	reqs := s.Requests()
	if len(reqs) != 1 {
		t.Fatalf("calls = %d", len(reqs))
	}
	b := reqs[0].Body
	if _, ok := b["model"]; ok || b["max_tokens"] != float64(1024) {
		t.Errorf("model/max_tokens = %v/%v; the request names no model", b["model"], b["max_tokens"])
	}
	if _, ok := b["temperature"]; ok {
		t.Error("temperature must not be sent")
	}
	if oc, _ := b["output_config"].(map[string]any); oc["effort"] != "low" {
		t.Errorf("output_config = %v", b["output_config"])
	}
	tc, _ := b["tool_choice"].(map[string]any)
	if tc["type"] != "auto" || tc["disable_parallel_tool_use"] != true {
		t.Errorf("tool_choice = %v", tc)
	}
	tools, _ := b["tools"].([]any)
	if len(tools) != 1 {
		t.Fatalf("tools = %v", b["tools"])
	}
	tool := tools[0].(map[string]any)
	schema := tool["input_schema"].(map[string]any)
	if tool["name"] != "lookup_permission" || tool["strict"] != true || schema["additionalProperties"] != false {
		t.Errorf("tool = %v", tool)
	}
	h := reqs[0].Header
	if h.Get("Authorization") != "Bearer svid" || h.Get("X-Api-Key") != "" || h.Get("Anthropic-Version") != "" {
		t.Errorf("headers = %v; want the JWT-SVID and no provider auth", h)
	}
}

func TestRepairRetryAfterToolUseStopWithNoBlocksIsWellFormed(t *testing.T) {
	s := model.New(model.ToolUseNone(), model.ToolUse("tom", "invoice:approve"))
	defer s.Close()
	res, err := propose(t, newClient(t, s))
	if err != nil || len(res.Attempts) != 2 {
		t.Fatalf("res=%+v err=%v", res, err)
	}
	msgs, _ := s.Requests()[1].Body["messages"].([]any)
	if len(msgs) != 3 {
		t.Fatalf("messages = %v", msgs)
	}
	for i, m := range msgs {
		mm := m.(map[string]any)
		if mm["content"] == nil {
			t.Errorf("message %d has null content: %v", i, mm)
		}
		if arr, ok := mm["content"].([]any); ok && len(arr) == 0 {
			t.Errorf("message %d has empty content: %v", i, mm)
		}
	}
	if last := msgs[2].(map[string]any); last["role"] != "user" {
		t.Errorf("last message = %v", last)
	}
}

func TestPromptHoldsOnlyTheQuestion(t *testing.T) {
	s := model.New(model.ToolUse("tom", "a:b"))
	defer s.Close()
	if _, err := propose(t, newClient(t, s)); err != nil {
		t.Fatal(err)
	}
	raw, _ := json.Marshal(s.Requests()[0].Body)
	if !strings.Contains(string(raw), "Does tom hold invoice:approve?") {
		t.Error("question missing from prompt")
	}
	if strings.Contains(strings.ToLower(string(raw)), "caller") {
		t.Error("prompt mentions the Caller")
	}
}

func TestGateRejections(t *testing.T) {
	good := map[string]any{"target": "a", "permission": "b:c"}
	cases := []struct {
		name  string
		reply model.Reply
		kind  modelclient.Kind
		code  modelclient.FailureCode
	}{
		{"stop reason", model.MaxTokens(), modelclient.Fatal, "stop_reason"},
		{"refusal", model.Refusal(), modelclient.Fatal, "refusal"},
		{"text only", model.Text("sure"), modelclient.Fatal, "text_only"},
		{"two tool uses", model.ToolUses(good, good), modelclient.Retryable, "tool_use_count"},
		{"wrong name", model.ToolUseNamed("other", good), modelclient.Retryable, "tool_name"},
		{"unknown field", model.ToolUseNamed("lookup_permission", map[string]any{"target": "a", "permission": "b:c", "x": 1}), modelclient.Retryable, "decode"},
		{"missing field", model.ToolUseNamed("lookup_permission", map[string]any{"target": "a"}), modelclient.Retryable, "decode"},
		{"empty field", model.ToolUseNamed("lookup_permission", map[string]any{"target": "", "permission": "b:c"}), modelclient.Retryable, "decode"},
		{"bad target", model.ToolUse("Tom!", "b:c"), modelclient.Retryable, "format"},
		{"bad permission", model.ToolUse("tom", "invoice-approve"), modelclient.Retryable, "format"},
		{"provider error", model.Error(529), modelclient.Fatal, "provider_error"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			// A retryable failure is followed by the same bad reply, so the
			// second call fails too.
			s := model.New(tc.reply, tc.reply)
			defer s.Close()
			res, err := propose(t, newClient(t, s))
			var f *modelclient.Failure
			if !errors.As(err, &f) {
				t.Fatalf("err = %v", err)
			}
			if f.Kind != tc.kind || f.Code != tc.code {
				t.Fatalf("failure = %v/%v, want %v/%v", f.Kind, f.Code, tc.kind, tc.code)
			}
			want := 1
			if tc.kind == modelclient.Retryable {
				want = 2
			}
			if n := len(s.Requests()); n != want || len(res.Attempts) != want {
				t.Fatalf("calls = %d, attempts = %d, want %d", n, len(res.Attempts), want)
			}
		})
	}
}

func TestTextOnlyKeepsText(t *testing.T) {
	s := model.New(model.Text("hello"))
	defer s.Close()
	_, err := propose(t, newClient(t, s))
	var f *modelclient.Failure
	if !errors.As(err, &f) || f.Text != "hello" {
		t.Fatalf("err = %v", err)
	}
}

func TestRepairRetryFeedsErrorBack(t *testing.T) {
	s := model.New(model.ToolUse("Tom!", "b:c"), model.ToolUse("tom", "invoice:approve"))
	defer s.Close()
	res, err := propose(t, newClient(t, s))
	if err != nil {
		t.Fatal(err)
	}
	if res.Proposal.Target != "tom" || len(res.Attempts) != 2 {
		t.Fatalf("res = %+v", res)
	}
	reqs := s.Requests()
	if len(reqs) != 2 {
		t.Fatalf("calls = %d", len(reqs))
	}
	raw, _ := json.Marshal(reqs[1].Body["messages"])
	if !strings.Contains(string(raw), "tool_result") || !strings.Contains(string(raw), `"is_error":true`) || !strings.Contains(string(raw), "target") {
		t.Errorf("repair messages = %s", raw)
	}
	if res.Attempts[0].RequestID == res.Attempts[1].RequestID {
		t.Error("attempts should carry distinct request ids")
	}
}

func TestScriptExhaustedIsProviderError(t *testing.T) {
	s := model.New()
	defer s.Close()
	_, err := propose(t, newClient(t, s))
	var f *modelclient.Failure
	if !errors.As(err, &f) || f.Kind != modelclient.Fatal || f.Code != "provider_error" {
		t.Fatalf("err = %v", err)
	}
}

func TestAttemptKeepsTheRawReply(t *testing.T) {
	s := model.New(model.Text("I cannot do that"))
	defer s.Close()
	res, _ := propose(t, newClient(t, s))
	if len(res.Attempts) != 1 || !strings.Contains(res.Attempts[0].Raw, "I cannot do that") {
		t.Fatalf("attempts = %+v", res.Attempts)
	}
}

func TestConfigRequiresBaseURLAndAnSVIDSource(t *testing.T) {
	if _, err := modelclient.New(modelclient.Config{SVID: testSVID}); err == nil {
		t.Error("want error for empty BaseURL")
	}
	if _, err := modelclient.New(modelclient.Config{BaseURL: "http://x"}); err == nil {
		t.Error("want error for no SVID source: the Broker is the only mode")
	}
}

// Live, a reply often starts with a thinking block. The repair retry echoes
// the Model's turn, and the API rejects a thinking block without its thinking
// and signature fields, so the echo must keep every block as sent.
func TestRepairRetryEchoesThinkingBlockUnchanged(t *testing.T) {
	s := model.New(model.WithThinking(model.ToolUse("Tom", "invoice:approve")), model.ToolUse("tom", "invoice:approve"))
	defer s.Close()
	res, err := propose(t, newClient(t, s))
	if err != nil || len(res.Attempts) != 2 {
		t.Fatalf("res=%+v err=%v", res, err)
	}
	msgs, _ := s.Requests()[1].Body["messages"].([]any)
	if len(msgs) != 3 {
		t.Fatalf("messages = %v", msgs)
	}
	echoed, _ := msgs[1].(map[string]any)["content"].([]any)
	if len(echoed) == 0 {
		t.Fatalf("assistant echo = %v", msgs[1])
	}
	th, _ := echoed[0].(map[string]any)
	if th["type"] != "thinking" || th["signature"] != "sig-standin" {
		t.Errorf("first echoed block = %v", th)
	}
	if v, ok := th["thinking"]; !ok || v != "" {
		t.Errorf("echoed thinking block lacks its thinking field: %v", th)
	}
}
