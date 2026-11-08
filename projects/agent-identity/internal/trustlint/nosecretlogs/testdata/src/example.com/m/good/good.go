package good

import (
	"fmt"
	"log"
	"log/slog"

	"example.com/m/wire"
)

func ok(tok wire.JWTSVID, name string) string {
	slog.Info("x", "len", len(tok), "name", name)
	log.Printf("%s", name)
	fmt.Println(name)
	return fmt.Sprintf("%s", tok)
}
