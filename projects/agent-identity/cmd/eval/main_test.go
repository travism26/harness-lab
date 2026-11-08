package main

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/travism26/harness-lab/projects/agent-identity/internal/eval"
	"github.com/travism26/harness-lab/projects/agent-identity/internal/standin/model"
)

var committedCases string

// TestMain moves into an empty directory, so the default .env path never
// finds a real one.
func TestMain(m *testing.M) {
	var err error
	if committedCases, err = filepath.Abs("../../evals/cases.jsonl"); err != nil {
		panic(err)
	}
	dir, err := os.MkdirTemp("", "eval-cwd")
	if err != nil {
		panic(err)
	}
	if err := os.Chdir(dir); err != nil {
		panic(err)
	}
	code := m.Run()
	os.RemoveAll(dir)
	os.Exit(code)
}

func env(kv map[string]string) func(string) string {
	return func(k string) string { return kv[k] }
}

func casesFile(t *testing.T, body string) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "cases.jsonl")
	if err := os.WriteFile(path, []byte(body), 0o600); err != nil {
		t.Fatal(err)
	}
	return path
}

const twoCases = `{"id":"a","category":"named","question":"Can Tom approve invoices?","accept":[{"target":"tom","permission":"invoice:approve"}]}
{"id":"b","category":"no-proposal","question":"Weather?","no_proposal":true}
`

func TestCommittedCasesCoverTheFourCategories(t *testing.T) {
	f, err := os.Open(committedCases)
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	cases, err := eval.LoadCases(f)
	if err != nil {
		t.Fatal(err)
	}
	counts := map[string]int{}
	reportOnly, outOfCatalog := 0, 0
	for _, c := range cases {
		counts[c.Category]++
		if c.ReportOnly {
			reportOnly++
		}
		if strings.HasPrefix(c.ID, "named-ooc-") {
			outOfCatalog++
		}
	}
	if len(cases) < 20 || len(cases) > 28 {
		t.Errorf("%d cases, want about 24", len(cases))
	}
	for _, k := range eval.Categories {
		if counts[k] < 5 {
			t.Errorf("category %s has %d cases", k, counts[k])
		}
	}
	if reportOnly != 2 || outOfCatalog < 2 || outOfCatalog > 3 {
		t.Errorf("report-only = %d, out-of-catalog = %d", reportOnly, outOfCatalog)
	}
}

func TestMissingKeyExitsBeforeAnyRequest(t *testing.T) {
	s := model.New(model.ToolUse("tom", "invoice:approve"))
	defer s.Close()
	for _, args := range [][]string{
		{"--cases", casesFile(t, twoCases)},
		{"--cases", casesFile(t, twoCases), "--provider", "anthropic"},
		{"--cases", casesFile(t, twoCases), "--provider", "openrouter"},
	} {
		var out, errb bytes.Buffer
		if code := runWith(args, &out, &errb, env(nil), s.URL); code == 0 {
			t.Errorf("%v: exit 0 without a key", args)
		}
		if !strings.Contains(errb.String(), "API_KEY") {
			t.Errorf("stderr = %q", errb.String())
		}
	}
	if n := len(s.Requests()); n != 0 {
		t.Fatalf("%d requests were sent", n)
	}
}

func TestProviderChoiceFollowsKeys(t *testing.T) {
	s := model.New(model.ToolUse("tom", "invoice:approve"), model.Text("x"),
		model.ToolUse("tom", "invoice:approve"), model.Text("x"))
	defer s.Close()
	cases := casesFile(t, twoCases)
	var out, errb bytes.Buffer
	code := runWith([]string{"--cases", cases, "--runs", "1"}, &out, &errb,
		env(map[string]string{"OPENROUTER_API_KEY": "or"}), s.URL)
	if code != 0 || !strings.Contains(out.String(), "provider: openrouter") {
		t.Fatalf("code=%d out=%s err=%s", code, out.String(), errb.String())
	}
	if got := s.Requests()[0].Header.Get("Authorization"); got != "Bearer or" {
		t.Errorf("Authorization = %q", got)
	}
	out.Reset()
	code = runWith([]string{"--cases", cases, "--runs", "1"}, &out, &errb,
		env(map[string]string{"OPENROUTER_API_KEY": "or", "ANTHROPIC_API_KEY": "an"}), s.URL)
	if code != 0 || !strings.Contains(out.String(), "provider: anthropic") {
		t.Fatalf("code=%d out=%s", code, out.String())
	}
	if got := s.Requests()[2].Header.Get("X-Api-Key"); got != "an" {
		t.Errorf("x-api-key = %q", got)
	}
}

func TestKeysComeFromTheEnvFileAndTheProcessOverridesIt(t *testing.T) {
	envFile := filepath.Join(t.TempDir(), ".env")
	if err := os.WriteFile(envFile, []byte("ANTHROPIC_API_KEY=file-a\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	s := model.New(model.ToolUse("tom", "invoice:approve"), model.Text("x"),
		model.ToolUse("tom", "invoice:approve"), model.Text("x"))
	defer s.Close()
	args := []string{"--cases", casesFile(t, twoCases), "--runs", "1", "--env-file", envFile}
	var out, errb bytes.Buffer
	if code := runWith(args, &out, &errb, env(nil), s.URL); code != 0 || !strings.Contains(out.String(), "provider: anthropic") {
		t.Fatalf("code=%d out=%s err=%s", code, out.String(), errb.String())
	}
	if got := s.Requests()[0].Header.Get("X-Api-Key"); got != "file-a" {
		t.Errorf("x-api-key = %q, want the file's key", got)
	}
	if code := runWith(args, &out, &errb, env(map[string]string{"ANTHROPIC_API_KEY": "proc-a"}), s.URL); code != 0 {
		t.Fatalf("code=%d err=%s", code, errb.String())
	}
	if got := s.Requests()[2].Header.Get("X-Api-Key"); got != "proc-a" {
		t.Errorf("x-api-key = %q, want the process key", got)
	}
}

func TestMissingEnvFileIsNotAnError(t *testing.T) {
	var out, errb bytes.Buffer
	args := []string{"--cases", casesFile(t, twoCases), "--env-file", filepath.Join(t.TempDir(), "absent")}
	code := runWith(args, &out, &errb, env(nil), "")
	if code != 2 || !strings.Contains(errb.String(), "API_KEY") {
		t.Fatalf("code=%d err=%s", code, errb.String())
	}
}

func TestExitCodeFollowsMinAccuracy(t *testing.T) {
	keys := env(map[string]string{"ANTHROPIC_API_KEY": "an"})
	wrong := func() *model.Server {
		return model.New(model.ToolUse("tom", "invoice:read"), model.Text("x"))
	}
	for _, tc := range []struct {
		args []string
		want int
	}{
		{nil, 1},
		{[]string{"--min-accuracy", "0"}, 0},
	} {
		s := wrong()
		args := append([]string{"--cases", casesFile(t, twoCases), "--runs", "1"}, tc.args...)
		var out, errb bytes.Buffer
		if code := runWith(args, &out, &errb, keys, s.URL); code != tc.want {
			t.Errorf("%v: code %d, want %d\n%s", tc.args, code, tc.want, out.String())
		}
		s.Close()
	}
}

func TestBadUsage(t *testing.T) {
	keys := env(map[string]string{"ANTHROPIC_API_KEY": "an"})
	for _, args := range [][]string{
		{"--runs", "0"},
		{"--provider", "nope"},
		{"--cases", "/no/such/file"},
		{"--min-accuracy", "2"},
		{"extra"},
	} {
		var out, errb bytes.Buffer
		if code := runWith(args, &out, &errb, keys, ""); code != 2 {
			t.Errorf("%v: code %d, want 2", args, code)
		}
	}
}
