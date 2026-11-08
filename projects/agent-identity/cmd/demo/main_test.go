package main

import (
	"bytes"
	"strings"
	"testing"
)

var wantLines = []string{
	"POST /lookup  agent=spiffe://example.com/permission-agent  aud=spiffe://example.com/warden  -> 200  outcome=allowed",
	"POST /lookup  agent=spiffe://example.com/permission-agent  aud=spiffe://example.com/not-the-warden  -> 401  outcome=unauthenticated  reason=jwt_svid_audience",
	"POST /lookup  agent=spiffe://example.com/unlisted-agent  aud=spiffe://example.com/warden  -> 403  outcome=agent_not_allowed",
}

func lookupLines(out string) []string {
	var lines []string
	for _, l := range strings.Split(out, "\n") {
		if strings.HasPrefix(l, "POST /lookup") {
			lines = append(lines, l)
		}
	}
	return lines
}

func TestRunScenarios(t *testing.T) {
	for _, sub := range []string{"tokens", "tour"} {
		t.Run(sub, func(t *testing.T) {
			var out, errOut bytes.Buffer
			if code := run([]string{sub}, &out, &errOut); code != 0 {
				t.Fatalf("exit %d, stderr: %s", code, errOut.String())
			}
			got := lookupLines(out.String())
			if len(got) != len(wantLines) {
				t.Fatalf("got %d lookup lines, want %d:\n%s", len(got), len(wantLines), out.String())
			}
			for i := range wantLines {
				if got[i] != wantLines[i] {
					t.Errorf("line %d:\n got %q\nwant %q", i, got[i], wantLines[i])
				}
			}
		})
	}
}

func TestRunUsage(t *testing.T) {
	for _, args := range [][]string{nil, {"bogus"}} {
		var out, errOut bytes.Buffer
		if code := run(args, &out, &errOut); code != 2 {
			t.Errorf("run(%v) = %d, want 2", args, code)
		}
		if errOut.Len() == 0 {
			t.Errorf("run(%v) printed no usage", args)
		}
	}
}
