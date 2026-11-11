// Command gateway starts the Gateway: a loopback process that forwards a
// Call to the Upstream and appends a Call record. It reads no environment
// variable and holds no credential; see
// projects/ai-gateway/docs/adr/0001-forward-only-on-loopback.md.
package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"net/url"
	"os"
	"os/signal"
	"strconv"
	"sync"
	"syscall"
	"time"

	"github.com/travism26/harness-lab/projects/ai-gateway/internal/gateway"
)

const (
	defaultListen = "127.0.0.1:8791"
	defaultAudit  = "audit.jsonl"
)

func main() {
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	os.Exit(run(ctx, os.Args[1:], os.Stderr, net.Listen, nil))
}

type listenFunc func(network, address string) (net.Listener, error)

// run starts the Gateway and returns the process exit code once ctx is done.
// ready, if not nil, is called with the bound address once the Gateway listens.
func run(ctx context.Context, args []string, stderr io.Writer, listen listenFunc, ready func(net.Addr)) int {
	fs := flag.NewFlagSet("gateway", flag.ContinueOnError)
	fs.SetOutput(stderr)
	listenAddr := fs.String("listen", defaultListen, "loopback address to listen on (127.0.0.1 or ::1)")
	upstream := fs.String("upstream", "", "Upstream Anthropic Messages endpoint URL (required)")
	audit := fs.String("audit", defaultAudit, "audit file to append Call records to")
	if err := fs.Parse(args); err != nil {
		return 2
	}
	if fs.NArg() > 0 {
		fmt.Fprintf(stderr, "gateway: unexpected argument %q\n", fs.Arg(0))
		return 2
	}
	if err := checkListen(*listenAddr); err != nil {
		fmt.Fprintf(stderr, "gateway: %v\n", err)
		return 2
	}
	if err := checkUpstream(*upstream); err != nil {
		fmt.Fprintf(stderr, "gateway: %v\n", err)
		return 2
	}

	auditFile, err := os.OpenFile(*audit, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o600)
	if err != nil {
		fmt.Fprintf(stderr, "gateway: audit file: %v\n", err)
		return 1
	}
	defer auditFile.Close()
	if err := auditFile.Chmod(0o600); err != nil {
		fmt.Fprintf(stderr, "gateway: audit file: %v\n", err)
		return 1
	}

	ln, err := listen("tcp", *listenAddr)
	if err != nil {
		fmt.Fprintf(stderr, "gateway: listen: %v\n", err)
		return 1
	}
	upstreamURL, err := url.Parse(*upstream)
	if err != nil {
		fmt.Fprintln(stderr, "gateway: --upstream is not a valid URL")
		return 1
	}
	pending := &newConns{}
	srv := &http.Server{
		Handler:           gateway.New(upstreamURL, auditFile, log.New(stderr, "", log.LstdFlags)),
		ReadHeaderTimeout: 10 * time.Second,
		ConnState:         pending.note,
	}
	// A client can dial and never write a request (net/http's Transport does
	// this when a spare dial loses the race to an idle connection). Shutdown
	// leaves that StateNew connection alone for five seconds, which is also
	// this deadline, so Shutdown would return context.DeadlineExceeded.
	srv.RegisterOnShutdown(pending.close)
	served := make(chan error, 1)
	go func() { served <- srv.Serve(ln) }()
	if ready != nil {
		ready(ln.Addr())
	}

	select {
	case err := <-served:
		fmt.Fprintf(stderr, "gateway: serve: %v\n", err)
		return 1
	case <-ctx.Done():
	}
	shutdown, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := srv.Shutdown(shutdown); err != nil && !errors.Is(err, http.ErrServerClosed) {
		fmt.Fprintf(stderr, "gateway: shutdown: %v\n", err)
		return 1
	}
	return 0
}

// checkListen accepts only 127.0.0.1 or ::1 with a numeric port.
func checkListen(addr string) error {
	host, port, err := net.SplitHostPort(addr)
	if err != nil {
		return fmt.Errorf("--listen %q: %w", addr, err)
	}
	if host != "127.0.0.1" && host != "::1" {
		return fmt.Errorf("--listen %q: only 127.0.0.1 and ::1 may bind", addr)
	}
	// A port is an unsigned decimal in 0..65535. A leading sign is not a port.
	if _, err := strconv.ParseUint(port, 10, 16); err != nil {
		return fmt.Errorf("--listen %q: bad port", addr)
	}
	return nil
}

// checkUpstream requires an absolute http or https URL. It does not dial.
func checkUpstream(raw string) error {
	if raw == "" {
		return errors.New("--upstream is required")
	}
	u, err := url.Parse(raw)
	if err != nil || (u.Scheme != "http" && u.Scheme != "https") || u.Host == "" {
		return errors.New("--upstream must be an http or https URL with a host")
	}
	return nil
}

// newConns is the set of accepted connections that have not sent a request.
type newConns struct {
	mu      sync.Mutex
	closing bool
	conns   map[net.Conn]struct{}
}

func (n *newConns) note(c net.Conn, st http.ConnState) {
	n.mu.Lock()
	if n.conns == nil {
		n.conns = make(map[net.Conn]struct{})
	}
	closeNow := false
	if st == http.StateNew {
		n.conns[c] = struct{}{}
		closeNow = n.closing
	} else {
		delete(n.conns, c)
	}
	n.mu.Unlock()
	if closeNow {
		c.Close()
	}
}

// close closes every connection that has not sent a request. A connection
// accepted after close has started is closed from note.
func (n *newConns) close() {
	n.mu.Lock()
	n.closing = true
	conns := n.conns
	n.conns = nil
	n.mu.Unlock()
	for c := range conns {
		c.Close()
	}
}
