// Command go-sandbox serves the Pass rate endpoint on the loopback interface.
package main

import (
	"log"
	"net/http"
	"time"

	"github.com/travism26/harness-lab/projects/go-sandbox/internal/httpapi"
)

// addr is loopback only, so the service is not reachable from other machines.
const addr = "127.0.0.1:8080"

func newServer() *http.Server {
	return &http.Server{
		Addr:              addr,
		Handler:           httpapi.Handler(),
		ReadHeaderTimeout: 5 * time.Second,
	}
}

func main() {
	log.Fatal(newServer().ListenAndServe())
}
