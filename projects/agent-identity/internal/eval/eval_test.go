package eval_test

import (
	"context"
	"strings"
	"testing"

	"github.com/travism26/harness-lab/projects/agent-identity/internal/eval"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/modelclient"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/standin/model"
)

func client(t *testing.T, s *model.Server) *modelclient.Client {
	t.Helper()
	c, err := modelclient.New(modelclient.Config{BaseURL: s.URL, APIKey: "k", Provider: "stand-in"})
	if err != nil {
		t.Fatal(err)
	}
	return c
}

func run(t *testing.T, cases []eval.Case, runs int, replies ...model.Reply) eval.Report {
	t.Helper()
	s := model.New(replies...)
	defer s.Close()
	return eval.Run(context.Background(), client(t, s), "stand-in", cases, runs)
}

func p(target, perm string) modelclient.Proposal {
	return modelclient.Proposal{Target: target, Permission: perm}
}

var named = eval.Case{ID: "n1", Category: "named", Question: "Can Tom approve invoices?",
	Accept: []modelclient.Proposal{p("tom", "invoice:approve")}}
var none = eval.Case{ID: "x1", Category: "no-proposal", Question: "Weather?", NoProposal: true}

func TestNoProposalPassesOnlyOnRefusalOrTextOnly(t *testing.T) {
	for name, tc := range map[string]struct {
		reply model.Reply
		want  bool
	}{
		"refusal":        {model.Refusal(), true},
		"text only":      {model.Text("no"), true},
		"provider error": {model.Error(500), false},
		"max tokens":     {model.MaxTokens(), false},
	} {
		r := run(t, []eval.Case{none}, 1, tc.reply)
		if got := r.Cases[0].Runs[0].Pass; got != tc.want {
			t.Errorf("%s: pass = %v (%s), want %v", name, got, r.Cases[0].Runs[0].Outcome, tc.want)
		}
	}
}

func TestLoadCases(t *testing.T) {
	good := `{"id":"a","category":"named","question":"q","accept":[{"target":"tom","permission":"invoice:approve"}]}
{"id":"b","category":"no-proposal","question":"q","no_proposal":true}
`
	cs, err := eval.LoadCases(strings.NewReader(good))
	if err != nil || len(cs) != 2 || cs[0].Accept[0] != p("tom", "invoice:approve") || !cs[1].NoProposal {
		t.Fatalf("cs=%+v err=%v", cs, err)
	}
	for name, bad := range map[string]string{
		"unknown field":    `{"id":"a","category":"named","question":"q","accept":[{"target":"t","permission":"a:b"}],"x":1}`,
		"unknown category": `{"id":"a","category":"zzz","question":"q","no_proposal":true}`,
		"no outcome":       `{"id":"a","category":"named","question":"q"}`,
		"empty question":   `{"id":"a","category":"named","question":"","no_proposal":true}`,
		"duplicate id":     `{"id":"a","category":"named","question":"q","no_proposal":true}` + "\n" + `{"id":"a","category":"named","question":"q","no_proposal":true}`,
		"not json":         `nope`,
	} {
		if _, err := eval.LoadCases(strings.NewReader(bad)); err == nil {
			t.Errorf("%s: want error", name)
		}
	}
}

func TestExactMatchPassesAndOtherProposalFails(t *testing.T) {
	r := run(t, []eval.Case{named}, 2, model.ToolUse("tom", "invoice:approve"), model.ToolUse("tom", "invoice:read"))
	c := r.Cases[0]
	if !c.Runs[0].Pass || c.Runs[1].Pass {
		t.Fatalf("runs = %+v", c.Runs)
	}
	if !c.Unstable {
		t.Error("runs disagree, want unstable")
	}
	if r.Categories["named"].Passed != 1 || r.Categories["named"].Total != 2 {
		t.Errorf("category = %+v", r.Categories["named"])
	}
}

func TestRetryThatFixesPassesAndIsCounted(t *testing.T) {
	bad := map[string]any{"target": "Tom!", "permission": "invoice:approve"}
	r := run(t, []eval.Case{named}, 1, model.ToolUses(bad), model.ToolUse("tom", "invoice:approve"))
	run0 := r.Cases[0].Runs[0]
	if !run0.Pass || run0.Retries != 1 || r.Categories["named"].Retries != 1 {
		t.Fatalf("run = %+v cat = %+v", run0, r.Categories["named"])
	}
}

func TestNoProposalPassesOnlyOnFatalFailure(t *testing.T) {
	r := run(t, []eval.Case{none}, 3,
		model.Text("It is sunny"),
		model.ToolUse("tom", "invoice:read"),
		model.Refusal())
	got := []bool{r.Cases[0].Runs[0].Pass, r.Cases[0].Runs[1].Pass, r.Cases[0].Runs[2].Pass}
	if !got[0] || got[1] || !got[2] {
		t.Fatalf("pass = %v", got)
	}
}

func TestNoProposalFailsWhenRetryableFailureExhausted(t *testing.T) {
	bad := map[string]any{"target": "Tom!", "permission": "x"}
	r := run(t, []eval.Case{none}, 1, model.ToolUses(bad), model.ToolUses(bad))
	if r.Cases[0].Runs[0].Pass {
		t.Fatal("a retryable failure is not a fatal no-proposal")
	}
}

func TestMultiPartIsReportOnly(t *testing.T) {
	multi := eval.Case{ID: "m1", Category: "no-proposal", Question: "q", NoProposal: true, ReportOnly: true,
		Accept: []modelclient.Proposal{p("tom", "invoice:approve"), p("bob", "invoice:read")}}
	r := run(t, []eval.Case{multi, none}, 1,
		model.ToolUse("bob", "invoice:read"), model.Text("hm"))
	if !r.Cases[0].Runs[0].Pass {
		t.Error("either half's Proposal passes")
	}
	cat := r.Categories["no-proposal"]
	if cat.Total != 1 || cat.Passed != 1 {
		t.Errorf("counted = %+v", cat)
	}
	if r.ReportOnly.Total != 1 || r.ReportOnly.Passed != 1 {
		t.Errorf("report-only = %+v", r.ReportOnly)
	}
}

func TestStableCaseNotUnstableAndRawKept(t *testing.T) {
	r := run(t, []eval.Case{named}, 2, model.ToolUse("tom", "invoice:approve"), model.ToolUse("tom", "invoice:approve"))
	if r.Cases[0].Unstable {
		t.Error("identical outcomes are stable")
	}
	if r.Provider != "stand-in" || len(r.Cases[0].Runs[0].Raw) != 1 || !strings.Contains(r.Cases[0].Runs[0].Raw[0], "invoice:approve") {
		t.Errorf("report = %+v", r)
	}
}

func TestExitCode(t *testing.T) {
	cases := []eval.Case{named, none}
	good := run(t, cases, 1, model.ToolUse("tom", "invoice:approve"), model.Text("x"))
	if !good.Passed(0.9) || good.ExitCode(0.9) != 0 {
		t.Error("all correct should pass")
	}
	bad := run(t, cases, 1, model.ToolUse("tom", "invoice:approve"), model.ToolUse("tom", "invoice:read"))
	if bad.Passed(0.9) || bad.ExitCode(0.9) != 1 {
		t.Error("a category under threshold should fail")
	}
	if bad.ExitCode(0) != 0 {
		t.Error("min-accuracy 0 is report-only")
	}
}

func TestWriteShowsTheReport(t *testing.T) {
	r := run(t, []eval.Case{named, none}, 2,
		model.ToolUse("tom", "invoice:approve"), model.ToolUse("tom", "invoice:read"),
		model.Text("sunny"), model.Text("sunny"))
	var b strings.Builder
	r.Write(&b, "claude-haiku-5-5", 0.9)
	out := b.String()
	for _, want := range []string{"provider: stand-in", "model: claude-haiku-5-5", "named", "no-proposal", "unstable", "n1", "retries", "cost", "invoice:read", "sunny"} {
		if !strings.Contains(out, want) {
			t.Errorf("report lacks %q:\n%s", want, out)
		}
	}
}
