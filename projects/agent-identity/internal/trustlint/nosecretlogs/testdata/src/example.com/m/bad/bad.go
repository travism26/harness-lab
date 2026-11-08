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
