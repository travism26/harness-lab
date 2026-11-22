package httpapi

import (
	"net/http"
	"net/http/httptest"
	"testing"
)

func do(method, target string) *httptest.ResponseRecorder {
	rec := httptest.NewRecorder()
	Handler().ServeHTTP(rec, httptest.NewRequest(method, target, nil))
	return rec
}

func TestPassRate(t *testing.T) {
	rec := do(http.MethodGet, "/pass-rate?passed=3&total=4")
	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rec.Code)
	}
	if got := rec.Header().Get("Content-Type"); got != "application/json" {
		t.Errorf("Content-Type = %q, want application/json", got)
	}
	want := "{\"passed\":3,\"total\":4,\"percent\":75}\n"
	if got := rec.Body.String(); got != want {
		t.Errorf("body = %q, want %q", got, want)
	}
}

func TestPassRateBadRequest(t *testing.T) {
	tests := []struct {
		name, target string
	}{
		{"passed above total", "/pass-rate?passed=5&total=4"},
		{"zero total", "/pass-rate?passed=0&total=0"},
		{"missing total", "/pass-rate?passed=3"},
		{"missing passed", "/pass-rate?total=4"},
		{"non-integer passed", "/pass-rate?passed=abc&total=4"},
		{"non-integer total", "/pass-rate?passed=3&total=x"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			rec := do(http.MethodGet, tt.target)
			if rec.Code != http.StatusBadRequest {
				t.Errorf("status = %d, want 400", rec.Code)
			}
		})
	}
}

func TestMethodNotAllowed(t *testing.T) {
	if rec := do(http.MethodPost, "/pass-rate?passed=3&total=4"); rec.Code != http.StatusMethodNotAllowed {
		t.Errorf("status = %d, want 405", rec.Code)
	}
}

func TestNotFound(t *testing.T) {
	if rec := do(http.MethodGet, "/nope"); rec.Code != http.StatusNotFound {
		t.Errorf("status = %d, want 404", rec.Code)
	}
}
