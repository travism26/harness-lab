package good

import (
	"fmt"
	"log"
	"log/slog"
	"strings"

	"example.com/m/wire"
)

type plain struct {
	name string
	n    int
}

type list struct {
	next *list
	val  string
}

func ok(tok wire.JWTSVID, name string, p plain, l *list) string {
	slog.Info("x", "len", len(tok), "name", name)
	log.Printf("%s", name)
	fmt.Println(name)
	fmt.Println(p, l)
	slog.Info("x", []any{"name", name}...)
	_ = strings.Repeat(string(tok), 2)
	return fmt.Sprintf("%s", name)
}
