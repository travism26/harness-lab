package main

import (
	"bytes"
	"context"
	"net"
	"os"
	"path/filepath"
	"runtime"
	"sync"
	"testing"
	"time"
)

// upstreamArg names an Upstream that no test dials.
const upstreamArg = "http://127.0.0.1:1/v1/messages"

type result struct {
	code    int
	stderr  string
	listens int
}

// start runs the Gateway and, once it listens, cancels it. It reports whether it listened.
func start(t *testing.T, args ...string) (result, net.Addr) {
	t.Helper()
	var res result
	var stderr bytes.Buffer
	var addr net.Addr
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	listen := func(network, address string) (net.Listener, error) {
		res.listens++
		return net.Listen(network, address)
	}
	res.code = run(ctx, args, &stderr, listen, func(a net.Addr) {
		addr = a
		cancel()
	})
	res.stderr = stderr.String()
	return res, addr
}

func TestRefusesNonLoopbackListen(t *testing.T) {
	for _, l := range []string{"0.0.0.0:8791", "[::]:8791", "localhost:8791", "192.168.1.5:8791", ":8791", "127.0.0.1", "127.0.0.1:x", "127.0.0.1:+80", "[::1]:-1"} {
		t.Run(l, func(t *testing.T) {
			res, _ := start(t, "--listen", l, "--upstream", upstreamArg, "--audit", filepath.Join(t.TempDir(), "a.jsonl"))
			if res.code == 0 || res.listens != 0 {
				t.Fatalf("code=%d listens=%d, want non-zero and no listen; stderr: %s", res.code, res.listens, res.stderr)
			}
		})
	}
}

func TestAcceptsLoopback(t *testing.T) {
	for _, l := range []string{"127.0.0.1:0", "[::1]:0"} {
		t.Run(l, func(t *testing.T) {
			if l == "[::1]:0" {
				if ln, err := net.Listen("tcp", l); err != nil {
					t.Skip("no IPv6 loopback")
				} else {
					ln.Close()
				}
			}
			res, addr := start(t, "--listen", l, "--upstream", upstreamArg, "--audit", filepath.Join(t.TempDir(), "a.jsonl"))
			if res.code != 0 || res.listens != 1 || addr == nil {
				t.Fatalf("code=%d listens=%d addr=%v; stderr: %s", res.code, res.listens, addr, res.stderr)
			}
		})
	}
}

func TestMissingUpstreamExitsBeforeListen(t *testing.T) {
	audit := filepath.Join(t.TempDir(), "a.jsonl")
	res, _ := start(t, "--listen", "127.0.0.1:0", "--audit", audit)
	if res.code == 0 || res.listens != 0 {
		t.Fatalf("code=%d listens=%d, want non-zero and no listen", res.code, res.listens)
	}
	if _, err := os.Stat(audit); err == nil {
		t.Fatal("audit file created despite missing --upstream")
	}
}

func TestAuditFileIsPrivate(t *testing.T) {
	for _, precreate := range []bool{false, true} {
		name := "created"
		if precreate {
			name = "tightened"
		}
		t.Run(name, func(t *testing.T) {
			if precreate && runtime.GOOS == "windows" {
				t.Skip("no unix modes")
			}
			audit := filepath.Join(t.TempDir(), "a.jsonl")
			if precreate {
				if err := os.WriteFile(audit, nil, 0o644); err != nil {
					t.Fatal(err)
				}
			}
			if res, _ := start(t, "--listen", "127.0.0.1:0", "--upstream", upstreamArg, "--audit", audit); res.code != 0 {
				t.Fatalf("code=%d; stderr: %s", res.code, res.stderr)
			}
			if runtime.GOOS == "windows" {
				return
			}
			fi, err := os.Stat(audit)
			if err != nil {
				t.Fatal(err)
			}
			if fi.Mode().Perm() != 0o600 {
				t.Fatalf("audit mode = %v, want 0600", fi.Mode().Perm())
			}
		})
	}
}

func TestEnvironmentChangesNothing(t *testing.T) {
	// A stand-in proxy that must never be dialed.
	proxy, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer proxy.Close()
	dialed := make(chan struct{}, 1)
	go func() {
		if c, err := proxy.Accept(); err == nil {
			c.Close()
			dialed <- struct{}{}
		}
	}()
	t.Setenv("HTTP_PROXY", "http://"+proxy.Addr().String())
	t.Setenv("HTTPS_PROXY", "http://"+proxy.Addr().String())
	t.Setenv("ANTHROPIC_API_KEY", "not-a-real-key")
	t.Setenv("LISTEN", "0.0.0.0:8791")

	res, addr := start(t, "--listen", "127.0.0.1:0", "--upstream", upstreamArg, "--audit", filepath.Join(t.TempDir(), "a.jsonl"))
	if res.code != 0 || addr == nil {
		t.Fatalf("code=%d; stderr: %s", res.code, res.stderr)
	}
	if !addr.(*net.TCPAddr).IP.IsLoopback() {
		t.Fatalf("bound %v", addr)
	}
	select {
	case <-dialed:
		t.Fatal("the proxy from the environment was dialed")
	case <-time.After(100 * time.Millisecond):
	}
}

func TestCredentialFlagDoesNotExist(t *testing.T) {
	res, _ := start(t, "--api-key", "x", "--upstream", upstreamArg)
	if res.code == 0 || res.listens != 0 {
		t.Fatalf("code=%d listens=%d", res.code, res.listens)
	}
}

// acceptSignal reports the first successful Accept.
type acceptSignal struct {
	net.Listener
	once sync.Once
	got  chan struct{}
}

func (a *acceptSignal) Accept() (net.Conn, error) {
	c, err := a.Listener.Accept()
	if err == nil {
		a.once.Do(func() { close(a.got) })
	}
	return c, err
}

// TestShutdownClosesConnWithNoRequest is the race that failed CI: a client
// dials and writes nothing, so the connection stays StateNew. Shutdown used
// to wait out its whole five-second deadline and exit 1.
func TestShutdownClosesConnWithNoRequest(t *testing.T) {
	var stderr bytes.Buffer
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	accepted := make(chan struct{})
	listen := func(network, address string) (net.Listener, error) {
		ln, err := net.Listen(network, address)
		if err != nil {
			return nil, err
		}
		return &acceptSignal{Listener: ln, got: accepted}, nil
	}
	addrCh := make(chan net.Addr, 1)
	done := make(chan int, 1)
	audit := filepath.Join(t.TempDir(), "a.jsonl")
	go func() {
		done <- run(ctx, []string{"--listen", "127.0.0.1:0", "--upstream", upstreamArg, "--audit", audit}, &stderr, listen, func(a net.Addr) {
			addrCh <- a
		})
	}()
	var addr net.Addr
	select {
	case addr = <-addrCh:
	case <-time.After(2 * time.Second):
		t.Fatal("did not listen")
	}
	conn, err := net.Dial("tcp", addr.String())
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	select {
	case <-accepted:
	case <-time.After(2 * time.Second):
		t.Fatal("server did not accept")
	}
	cancel()
	select {
	case code := <-done:
		if code != 0 {
			t.Fatalf("exit %d: %s", code, stderr.String())
		}
	case <-time.After(2 * time.Second):
		t.Fatal("shutdown did not return before the deadline")
	}
}
