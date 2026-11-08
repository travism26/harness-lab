package model_test

import (
	"net/http"
	"strings"
	"testing"

	"github.com/travism26/harness-lab/projects/agent-identity/internal/standin/model"
)

func post(t *testing.T, url string, header map[string]string) int {
	t.Helper()
	req, _ := http.NewRequest(http.MethodPost, url+"/v1/messages", strings.NewReader(`{}`))
	for k, v := range header {
		req.Header.Set(k, v)
	}
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	resp.Body.Close()
	return resp.StatusCode
}

func TestServesBothAuthStylesAndRecordsWhichOne(t *testing.T) {
	s := model.New(model.Text("a"), model.Text("b"), model.Text("c"))
	defer s.Close()
	for _, h := range []map[string]string{
		{"x-api-key": "k", "anthropic-version": "2026-10-21"},
		{"Authorization": "Bearer k"},
		{},
	} {
		if code := post(t, s.URL, h); code != http.StatusOK {
			t.Fatalf("%v: status %d", h, code)
		}
	}
	reqs := s.Requests()
	want := []string{model.AuthAnthropic, model.AuthBearer, model.AuthNone}
	for i, w := range want {
		if reqs[i].Auth != w {
			t.Errorf("request %d: Auth = %q, want %q", i, reqs[i].Auth, w)
		}
	}
}

func TestAnthropicAuthNeedsTheVersionHeader(t *testing.T) {
	s := model.New(model.Text("a"))
	defer s.Close()
	post(t, s.URL, map[string]string{"x-api-key": "k"})
	if got := s.Requests()[0].Auth; got != model.AuthNone {
		t.Errorf("Auth = %q, want none without anthropic-version", got)
	}
}
