package main

import (
	"bytes"
	"slices"
	"strings"
	"testing"
)

var tokenLines = []string{
	"POST /lookup  agent=spiffe://example.com/permission-agent  aud=spiffe://example.com/warden  -> 200  outcome=answer_yes",
	"POST /lookup  agent=spiffe://example.com/permission-agent  aud=spiffe://example.com/not-the-warden  -> 401  outcome=unauthenticated  reason=jwt_svid_audience",
	"POST /lookup  agent=spiffe://example.com/unlisted-agent  aud=spiffe://example.com/warden  -> 403  outcome=agent_not_allowed",
}

var scriptedLines = []string{
	"POST /lookup  caller=acme/alice  target=acme/tom  permission=invoice:approve  -> 200  outcome=answer_yes  holds=true  role=Finance Approver",
	"POST /lookup  caller=acme/bob  target=acme/tom  permission=invoice:approve  -> 403  outcome=denial  failed_check=lookup_check",
	"POST /lookup  caller=acme/alice  target=globex/sam  permission=permission:read  -> 403  outcome=denial  failed_check=lookup_check",
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

func runLines(t *testing.T, args ...string) []string {
	t.Helper()
	var out, errOut bytes.Buffer
	if code := run(args, &out, &errOut); code != 0 {
		t.Fatalf("run(%v) exit %d, stderr: %s", args, code, errOut.String())
	}
	return lookupLines(out.String())
}

func checkLines(t *testing.T, got, want []string) {
	t.Helper()
	if len(got) != len(want) {
		t.Fatalf("got %d lookup lines, want %d:\n%s", len(got), len(want), strings.Join(got, "\n"))
	}
	for i := range want {
		if got[i] != want[i] {
			t.Errorf("line %d:\n got %q\nwant %q", i, got[i], want[i])
		}
	}
}

func TestRunTokens(t *testing.T) {
	checkLines(t, runLines(t, "tokens"), tokenLines)
}

func TestRunScripted(t *testing.T) {
	checkLines(t, runLines(t, "scripted"), scriptedLines)
}

func TestRunTour(t *testing.T) {
	checkLines(t, runLines(t, "tour"), slices.Concat(tokenLines, scriptedLines))
}

func TestScriptedAsUnknownUser(t *testing.T) {
	unauth := "-> 401  outcome=unauthenticated  failed_check=caller_assertion  reason=assertion_unknown_caller"
	want := []string{
		"POST /lookup  caller=acme/nobody  target=acme/tom  permission=invoice:approve  " + unauth,
		scriptedLines[1],
		"POST /lookup  caller=acme/nobody  target=globex/sam  permission=permission:read  " + unauth,
	}
	checkLines(t, runLines(t, "scripted", "--as", "acme/nobody"), want)
}

func TestScriptedAsGlobexUserTargetsAcme(t *testing.T) {
	got := runLines(t, "scripted", "--as", "globex/sam")
	if len(got) != 3 {
		t.Fatalf("got %d lines, want 3: %v", len(got), got)
	}
	want := "POST /lookup  caller=globex/sam  target=acme/alice  permission=permission:read  -> 403  outcome=denial  failed_check=lookup_check"
	if got[2] != want {
		t.Errorf("line 3:\n got %q\nwant %q", got[2], want)
	}
}

func TestRunUsage(t *testing.T) {
	for _, args := range [][]string{nil, {"bogus"}, {"scripted", "--nope"}, {"scripted", "extra"}} {
		var out, errOut bytes.Buffer
		if code := run(args, &out, &errOut); code != 2 {
			t.Errorf("run(%v) = %d, want 2", args, code)
		}
		if !strings.Contains(errOut.String(), "usage: demo") {
			t.Errorf("run(%v) printed no usage: %q", args, errOut.String())
		}
	}
}
