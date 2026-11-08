package main

import (
	"bytes"
	"strings"
	"testing"
)

func replyOut(args ...string) (stdout, stderr string, code int) {
	var out, errOut bytes.Buffer
	code = run(args, &out, &errOut)
	return out.String(), errOut.String(), code
}

func firstLine(s string) string { return strings.SplitN(s, "\n", 2)[0] }

func TestAskYes(t *testing.T) {
	out, errOut, code := replyOut("ask", "Can Tom approve invoices?")
	if code != 0 {
		t.Fatalf("exit %d: %s", code, errOut)
	}
	want := "Yes. tom holds `invoice:approve` in acme through the Finance Approver role."
	if firstLine(out) != want {
		t.Errorf("stdout first line %q; want %q", firstLine(out), want)
	}
	if !strings.Contains(out, "\n[model: stand-in · id ") || strings.Count(out, "\n") != 2 {
		t.Errorf("stdout should be the Reply and its footer only: %q", out)
	}
	if !strings.Contains(errOut, "proposal") {
		t.Errorf("stderr has no trace: %q", errOut)
	}
}

func TestAskFlagAfterQuestion(t *testing.T) {
	out, _, code := replyOut("ask", "Can Tom approve invoices?", "--as", "acme/nobody")
	want := "The Warden didn't accept my identity or yours, so no lookup was made."
	if code != 0 || firstLine(out) != want {
		t.Errorf("exit %d, got %q", code, firstLine(out))
	}
}

func TestAskFlagBeforeQuestionAndOtherReplies(t *testing.T) {
	out, _, code := replyOut("ask", "--as", "acme/bob", "Can Tom approve invoices?")
	if code != 0 || firstLine(out) != "I can't answer that: the Warden didn't allow this lookup." {
		t.Errorf("exit %d, got %q", code, firstLine(out))
	}
	out, _, code = replyOut("ask", "What is the weather?")
	if code != 0 || !strings.HasPrefix(firstLine(out), "I couldn't turn that into one permission lookup") {
		t.Errorf("exit %d, got %q", code, firstLine(out))
	}
}

func TestAskNeedsAQuestion(t *testing.T) {
	if _, _, code := replyOut("ask"); code != 2 {
		t.Errorf("exit %d; want 2", code)
	}
}

func TestTourIncludesAsk(t *testing.T) {
	out, _, code := replyOut("tour")
	if code != 0 || !strings.Contains(out, "== ask\nYes. tom holds `invoice:approve` in acme through the Finance Approver role.") {
		t.Errorf("exit %d, tour output lacks the ask Reply:\n%s", code, out)
	}
}
