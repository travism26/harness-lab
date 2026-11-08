package provider

import (
	"errors"
	"fmt"
	"io/fs"
	"os"
	"strings"
)

// DotEnvPath is where the commands look for keys, relative to the project
// directory they run from. The root .gitignore ignores it.
const DotEnvPath = ".env"

// WithDotEnv returns a getenv that reads KEY=VALUE lines from the file at path
// and lets getenv (the process environment) override them. A missing file is
// not an error. The only file ever read is path: no shell startup file. An
// error never carries a value from the file.
func WithDotEnv(path string, getenv func(string) string) (func(string) string, error) {
	raw, err := os.ReadFile(path)
	if err != nil && !errors.Is(err, fs.ErrNotExist) {
		return getenv, fmt.Errorf("cannot read %s", path)
	}
	vals := map[string]string{}
	for _, line := range strings.Split(string(raw), "\n") {
		line = strings.TrimSpace(line)
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		line = strings.TrimSpace(strings.TrimPrefix(line, "export "))
		k, v, ok := strings.Cut(line, "=")
		if !ok {
			continue
		}
		v = strings.TrimSpace(v)
		if len(v) >= 2 && (v[0] == '"' || v[0] == '\'') && v[len(v)-1] == v[0] {
			v = v[1 : len(v)-1]
		}
		vals[strings.TrimSpace(k)] = v
	}
	return func(k string) string {
		if v := getenv(k); v != "" {
			return v
		}
		return vals[k]
	}, nil
}
