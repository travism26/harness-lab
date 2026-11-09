package rundir

import (
	"path/filepath"
	"regexp"
	"testing"
)

func TestMakeUsesOutWhenGiven(t *testing.T) {
	out := filepath.Join(t.TempDir(), "a", "b")
	dir, err := Make(out, t.TempDir())
	if err != nil || dir != out {
		t.Fatalf("got %q, %v", dir, err)
	}
}

func TestMakeDefaultsToATimestampUnderBaseAndNeverReusesOne(t *testing.T) {
	base := filepath.Join(t.TempDir(), "runs")
	seen := map[string]bool{}
	for range 3 {
		dir, err := Make("", base)
		if err != nil {
			t.Fatal(err)
		}
		if seen[dir] || filepath.Dir(dir) != base || !regexp.MustCompile(`^\d{8}T\d{6}Z(-\d+)?$`).MatchString(filepath.Base(dir)) {
			t.Fatalf("bad or repeated run directory %q", dir)
		}
		seen[dir] = true
	}
}
