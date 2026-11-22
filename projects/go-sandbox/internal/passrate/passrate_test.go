package passrate

import (
	"math"
	"testing"
)

func TestNewAndPercent(t *testing.T) {
	tests := []struct {
		name          string
		passed, total int
		percent       int
	}{
		{"none passed", 0, 1, 0},
		{"all passed", 1, 1, 100},
		{"three of four", 3, 4, 75},
		{"one of three rounds down", 1, 3, 33},
		{"two of three rounds up", 2, 3, 67},
		{"half rounds up", 1, 8, 13},
		{"largest total, all passed", math.MaxInt, math.MaxInt, 100},
		{"largest total, one short", math.MaxInt - 1, math.MaxInt, 100},
		{"largest total, half", math.MaxInt / 2, math.MaxInt, 50},
		{"largest total, one passed", 1, math.MaxInt, 0},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			r, err := New(tt.passed, tt.total)
			if err != nil {
				t.Fatalf("New(%d, %d) returned error: %v", tt.passed, tt.total, err)
			}
			if r.Passed() != tt.passed || r.Total() != tt.total {
				t.Errorf("got %d of %d, want %d of %d", r.Passed(), r.Total(), tt.passed, tt.total)
			}
			if got := r.Percent(); got != tt.percent {
				t.Errorf("Percent() = %d, want %d", got, tt.percent)
			}
		})
	}
}

func TestNewRejects(t *testing.T) {
	tests := []struct {
		name          string
		passed, total int
		want          string
	}{
		{"zero total", 0, 0, "total must be at least 1: 0"},
		{"negative total", 1, -1, "total must be at least 1: -1"},
		{"negative passed", -1, 4, "passed must be between 0 and total: -1 of 4"},
		{"passed above total", 5, 4, "passed must be between 0 and total: 5 of 4"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			_, err := New(tt.passed, tt.total)
			if err == nil {
				t.Fatalf("New(%d, %d) returned no error", tt.passed, tt.total)
			}
			if err.Error() != tt.want {
				t.Errorf("error = %q, want %q", err.Error(), tt.want)
			}
		})
	}
}
