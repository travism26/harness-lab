package usesbroker // want package:"reaches example.com/m/internal/broker via example.com/m/internal/broker"

import "example.com/m/internal/broker"

func Run() { broker.Run() }
