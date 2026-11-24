package main

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

const fixture = "../../internal/redact/testdata/with-secrets.jsonl"

func TestRedactsFixtureAndReportsCounts(t *testing.T) {
	out := filepath.Join(t.TempDir(), "redacted.jsonl")
	var stderr bytes.Buffer
	if code := run([]string{fixture, out}, &stderr); code != 0 {
		t.Fatalf("exit code %d", code)
	}
	b, err := os.ReadFile(out)
	if err != nil {
		t.Fatal(err)
	}
	if bytes.Contains(b, []byte("FIXTUREONLY")) {
		t.Error("output still contains a fake secret")
	}
	if bytes.Contains(stderr.Bytes(), []byte("FIXTUREONLY")) {
		t.Error("stderr contains a fake secret")
	}
	for _, line := range []string{
		"redacted anthropic-key: 1\n", "redacted bearer: 2\n", "redacted header: 1\n",
		"redacted oauth: 2\n", "redacted pem: 1\n", "redacted total: 7\n",
	} {
		if !strings.Contains(stderr.String(), line) {
			t.Errorf("stderr lacks the line %q", line)
		}
	}
}

func TestRefusesToWriteOverInput(t *testing.T) {
	dir := t.TempDir()
	in := filepath.Join(dir, "in.jsonl")
	original := []byte(`{"request_body":"Bearer FIXTUREONLYtoken0000"}` + "\n")
	if err := os.WriteFile(in, original, 0o600); err != nil {
		t.Fatal(err)
	}
	link := filepath.Join(dir, "link.jsonl")
	if err := os.Symlink(in, link); err != nil {
		t.Skip("no symlinks here")
	}
	for _, out := range []string{in, filepath.Join(dir, ".", "in.jsonl"), link} {
		var stderr bytes.Buffer
		if code := run([]string{in, out}, &stderr); code == 0 {
			t.Errorf("exit code 0 for output %q", filepath.Base(out))
		}
		got, _ := os.ReadFile(in)
		if !bytes.Equal(got, original) {
			t.Fatal("the input file was changed")
		}
	}
}

func TestUsageAndMissingInput(t *testing.T) {
	var stderr bytes.Buffer
	if code := run(nil, &stderr); code != 2 {
		t.Errorf("no args: code %d, want 2", code)
	}
	out := filepath.Join(t.TempDir(), "o.jsonl")
	if code := run([]string{filepath.Join(t.TempDir(), "missing.jsonl"), out}, &stderr); code != 1 {
		t.Errorf("missing input: code %d, want 1", code)
	}
	if _, err := os.Stat(out); err == nil {
		t.Error("an output file was created for a missing input")
	}
}
