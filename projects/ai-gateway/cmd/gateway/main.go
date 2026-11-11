// Command gateway starts the Gateway: a loopback process that will forward a
// Call to the Upstream and append a Call record. It does not forward a Call
// yet. It reads no environment variable and holds no credential; see
// projects/ai-gateway/docs/adr/0001-forward-only-on-loopback.md.
package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"os/signal"
	"strconv"
	"syscall"
	"time"
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
	srv := &http.Server{Handler: handler(), ReadHeaderTimeout: 10 * time.Second}
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
	if n, err := strconv.Atoi(port); err != nil || n < 0 || n > 65535 {
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

// handler accepts POST /v1/messages only. It forwards nothing yet.
func handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("POST /v1/messages", func(w http.ResponseWriter, _ *http.Request) {
		http.Error(w, "forwarding is not built yet", http.StatusNotImplemented)
	})
	return mux
}
