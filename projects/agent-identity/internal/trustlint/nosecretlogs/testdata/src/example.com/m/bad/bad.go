package bad

import (
	"fmt"
	"io"
	"log"
	"log/slog"

	"example.com/m/wire"
)

type aliasToken = wire.JWTSVID

func leakAlias(tok aliasToken) {
	slog.Info("x", "t", tok)               // want `R3: value of token type example.com/m/wire.JWTSVID passed to log/slog.Info`
	fmt.Println(aliasToken("from-string")) // want `R3: value of token type example.com/m/wire.JWTSVID passed to fmt.Println`
}

func leak(w io.Writer, tok wire.JWTSVID, b *wire.Bearer, logger *slog.Logger) {
	slog.Info("x", "t", tok)          // want `R3: value of token type example.com/m/wire.JWTSVID passed to log/slog.Info`
	logger.Debug("x", "t", tok)       // want `R3: value of token type example.com/m/wire.JWTSVID passed to \(\*log/slog.Logger\).Debug`
	fmt.Println(tok)                  // want `R3: value of token type example.com/m/wire.JWTSVID passed to fmt.Println`
	fmt.Fprintf(w, "%s", string(tok)) // want `R3: value of token type example.com/m/wire.JWTSVID passed to fmt.Fprintf`
	log.Printf("%v", tok)             // want `R3: value of token type example.com/m/wire.JWTSVID passed to log.Printf`
	slog.String("t", string(tok))     // want `R3: value of token type example.com/m/wire.JWTSVID passed to log/slog.String`
	fmt.Print(any((tok)))             // want `R3: value of token type example.com/m/wire.JWTSVID passed to fmt.Print`
	fmt.Println(b)                    // want `R3: value of token type example.com/m/wire.Bearer passed to fmt.Println`
	log.New(w, "", 0).Print(tok)      // want `R3: value of token type example.com/m/wire.JWTSVID passed to \(\*log.Logger\).Print`
}

type holder struct {
	name string
	tok  wire.JWTSVID
}

type hidden struct {
	name string
	tok  wire.Bearer
}

type node struct {
	next *node
	tok  wire.JWTSVID
}

func leakNested(h holder, hp *hidden, toks []wire.JWTSVID, m map[string]wire.JWTSVID, n *node) {
	fmt.Printf("%+v", h)   // want `R3: value of type example.com/m/bad.holder contains token type example.com/m/wire.JWTSVID, passed to fmt.Printf`
	slog.Info("x", "h", h) // want `R3: value of type example.com/m/bad.holder contains token type example.com/m/wire.JWTSVID, passed to log/slog.Info`
	fmt.Println(toks)      // want `R3: value of type \[\]example.com/m/wire.JWTSVID contains token type example.com/m/wire.JWTSVID, passed to fmt.Println`
	fmt.Println(m)         // want `R3: value of type map\[string\]example.com/m/wire.JWTSVID contains token type example.com/m/wire.JWTSVID, passed to fmt.Println`
	fmt.Printf("%+v", hp)  // want `R3: value of type \*example.com/m/bad.hidden contains token type example.com/m/wire.Bearer, passed to fmt.Printf`
	fmt.Println(n)         // want `R3: value of type \*example.com/m/bad.node contains token type example.com/m/wire.JWTSVID, passed to fmt.Println`
}

func leakFormatted(tok wire.JWTSVID) (string, error) {
	_ = fmt.Sprintf("%s", tok)           // want `R3: value of token type example.com/m/wire.JWTSVID passed to fmt.Sprintf`
	return "", fmt.Errorf("bad %s", tok) // want `R3: value of token type example.com/m/wire.JWTSVID passed to fmt.Errorf`
}

func leakSpread(tok wire.JWTSVID) {
	slog.Info("x", []any{"t", tok}...) // want `R3: value of token type example.com/m/wire.JWTSVID passed to log/slog.Info`
}
