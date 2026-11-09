// Package workloadsrc opens go-spiffe's JWT source on a spiffecli Workload API
// socket. The demo, the Broker and the Eval share it: each takes JWT-SVIDs or
// the trust bundle, or both, from a socket the owner started.
package workloadsrc

import (
	"context"
	"time"

	"github.com/spiffe/go-spiffe/v2/workloadapi"
)

// Timeout is how long opening a socket may wait for its first update.
const Timeout = 10 * time.Second

// StartHint tells the owner how to start the sockets, for a command that could
// not reach one.
const StartHint = "start spiffecli with `spiffecli run --config spiffecli/workloads.toml` from projects/agent-identity"

// OpenAs is Open for a command that holds the source behind its own small
// interface T, which Source must satisfy. It exists so a nil error never wraps a
// nil Source in a non-nil interface; a command checks its T with a
// compile-time assertion such as `var _ T = workloadsrc.Source{}`.
func OpenAs[T any](ctx context.Context, socket string) (T, error) {
	var none T
	src, err := Open(ctx, socket)
	if err != nil {
		return none, err
	}
	return any(src).(T), nil
}

// Source is a go-spiffe JWTSource and the context that keeps its watcher
// running. It fetches JWT-SVIDs and serves the trust bundles.
type Source struct {
	*workloadapi.JWTSource
	cancel context.CancelFunc
}

// Close stops the watcher and releases the connection.
func (s Source) Close() error {
	err := s.JWTSource.Close()
	s.cancel()
	return err
}

// Open connects to the Workload API socket at the given path. An unreachable
// socket is an error after Timeout.
func Open(ctx context.Context, socket string) (Source, error) {
	ctx, cancel := context.WithCancel(ctx)
	timer := time.AfterFunc(Timeout, cancel)
	defer timer.Stop()
	src, err := workloadapi.NewJWTSource(ctx, workloadapi.WithClientOptions(workloadapi.WithAddr("unix://"+socket)))
	if err != nil {
		cancel()
		return Source{}, err
	}
	return Source{JWTSource: src, cancel: cancel}, nil
}
