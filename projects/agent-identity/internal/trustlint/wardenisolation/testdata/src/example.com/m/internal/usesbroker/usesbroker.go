package usesbroker // want package:"reaches example.com/m/internal/agent via example.com/m/internal/broker -> example.com/m/internal/agent, example.com/m/internal/broker via example.com/m/internal/broker, example.com/m/internal/modelclient via example.com/m/internal/broker -> example.com/m/internal/warden -> example.com/m/internal/modelclient, example.com/m/internal/warden via example.com/m/internal/broker -> example.com/m/internal/warden"

import "example.com/m/internal/broker"

func Run() { broker.Run() }
