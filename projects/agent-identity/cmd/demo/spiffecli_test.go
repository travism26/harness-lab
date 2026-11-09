package main

import (
	"os"
	"regexp"
	"strings"
	"testing"
)

// The shipped spiffecli config is what the owner starts by hand for
// --spiffe-socket; this keeps it matching what the demo expects.
func TestSpiffecliConfig(t *testing.T) {
	raw, err := os.ReadFile("../../spiffecli/workloads.toml")
	if err != nil {
		t.Fatal(err)
	}
	cfg := string(raw)

	tables := regexp.MustCompile(`(?m)^\[([^\]]+)\]`).FindAllStringSubmatch(cfg, -1)
	var got []string
	for _, m := range tables {
		got = append(got, m[1])
	}
	want := []string{
		`td."example.com".workload.permission-agent`,
		`td."example.com".workload.warden`,
		`td."example.com".workload.model-broker`,
		`td."example.com".workload.model-eval`,
		`td."example.com".workload.unlisted-agent`,
	}
	if strings.Join(got, "\n") != strings.Join(want, "\n") {
		t.Errorf("tables %q; want %q (and no [federation])", got, want)
	}
	for _, name := range []string{"permission-agent", "warden", "model-broker", "model-eval", "unlisted-agent"} {
		sock := regexp.MustCompile(`(?m)^socket_path\s*=\s*"(/tmp/agent-identity/` + name + `\.sock)"`).FindStringSubmatch(cfg)
		if sock == nil {
			t.Errorf("no socket under /tmp/agent-identity/ for %s", name)
		} else if len(sock[1]) > 100 {
			t.Errorf("socket path %q is too long for macOS", sock[1])
		}
	}
	if n := len(regexp.MustCompile(`(?m)^jwt_svid_ttl\s*=\s*"5m"`).FindAllString(cfg, -1)); n != 5 {
		t.Errorf("%d workloads set jwt_svid_ttl = \"5m\"; want 5", n)
	}
	if strings.Contains(cfg, "federation") && !regexp.MustCompile(`(?m)^#.*federation`).MatchString(cfg) {
		t.Error("the config must have no [federation] table")
	}
}

// The default Warden socket sits beside the Agent's, as the config lays them out.
func TestDefaultWardenSocketMatchesTheConfig(t *testing.T) {
	f := newFakeSockets(t)
	_, errOut, code := runDeps(deps{openJWT: f.open}, "tokens", "--spiffe-socket", "/tmp/agent-identity/permission-agent.sock")
	if code != 0 || f.opened[1] != "/tmp/agent-identity/warden.sock" {
		t.Errorf("exit %d, opened %v: %s", code, f.opened, errOut)
	}
}
