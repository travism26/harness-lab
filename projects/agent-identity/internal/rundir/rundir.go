// Package rundir makes a run directory for Audit logs. The demo and the Broker
// command share it so that "--out" means the same thing to both.
package rundir

import (
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"time"
)

// Make creates out if given, or else a new UTC-timestamped directory under
// base, and returns its path. A timestamp already taken gets a -2, -3 ... suffix.
func Make(out, base string) (string, error) {
	if out != "" {
		return out, os.MkdirAll(out, 0o755)
	}
	stamp := time.Now().UTC().Format("20060102T150405Z")
	dir := filepath.Join(base, stamp)
	for n := 2; ; n++ {
		err := os.MkdirAll(base, 0o755)
		if err == nil {
			err = os.Mkdir(dir, 0o755)
		}
		if err == nil {
			return dir, nil
		}
		if !errors.Is(err, fs.ErrExist) {
			return "", err
		}
		dir = filepath.Join(base, fmt.Sprintf("%s-%d", stamp, n))
	}
}
