package provider

import (
	"os"
	"path/filepath"
	"testing"
)

func writeEnv(t *testing.T, content string) string {
	t.Helper()
	p := filepath.Join(t.TempDir(), ".env")
	if err := os.WriteFile(p, []byte(content), 0o600); err != nil {
		t.Fatal(err)
	}
	return p
}

func TestDotEnvSuppliesKeysTheProcessLacks(t *testing.T) {
	p := writeEnv(t, "# keys\nANTHROPIC_API_KEY=file-a\nexport OPENROUTER_API_KEY=\"file-o\"\n\nJUNK\n")
	get, err := WithDotEnv(p, env(nil))
	if err != nil {
		t.Fatal(err)
	}
	if got := get("ANTHROPIC_API_KEY"); got != "file-a" {
		t.Errorf("anthropic = %q", got)
	}
	if got := get("OPENROUTER_API_KEY"); got != "file-o" {
		t.Errorf("openrouter = %q", got)
	}
	if got := get("OTHER"); got != "" {
		t.Errorf("other = %q", got)
	}
}

func TestProcessEnvironmentOverridesDotEnv(t *testing.T) {
	p := writeEnv(t, "ANTHROPIC_API_KEY=file-a\nOPENROUTER_API_KEY=file-o\n")
	get, err := WithDotEnv(p, env(map[string]string{"ANTHROPIC_API_KEY": "proc-a"}))
	if err != nil {
		t.Fatal(err)
	}
	if got := get("ANTHROPIC_API_KEY"); got != "proc-a" {
		t.Errorf("anthropic = %q, want the process value", got)
	}
	if got := get("OPENROUTER_API_KEY"); got != "file-o" {
		t.Errorf("openrouter = %q", got)
	}
}

func TestMissingDotEnvIsNotAnError(t *testing.T) {
	get, err := WithDotEnv(filepath.Join(t.TempDir(), "absent.env"), env(map[string]string{"ANTHROPIC_API_KEY": "p"}))
	if err != nil {
		t.Fatal(err)
	}
	if got := get("ANTHROPIC_API_KEY"); got != "p" {
		t.Errorf("anthropic = %q", got)
	}
}

func TestUnreadableDotEnvIsAnErrorThatHoldsNoValue(t *testing.T) {
	// A directory where the file should be: present but not readable as a file.
	if _, err := WithDotEnv(t.TempDir(), env(nil)); err == nil {
		t.Fatal("want an error")
	}
}

func TestSelectUsesDotEnvKeys(t *testing.T) {
	p := writeEnv(t, "OPENROUTER_API_KEY=file-o\n")
	get, _ := WithDotEnv(p, env(nil))
	got, err := Select("", get)
	if err != nil || got.Name != "openrouter" || got.Key != "file-o" {
		t.Fatalf("got %+v, %v", got, err)
	}
}
