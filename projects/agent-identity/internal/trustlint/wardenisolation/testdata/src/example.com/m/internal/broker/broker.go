package broker // want package:"reaches example.com/m/internal/agent via example.com/m/internal/agent, example.com/m/internal/warden via example.com/m/internal/warden"

import (
	"example.com/m/internal/agent"  // want `R2: example.com/m/internal/broker may not import example.com/m/internal/agent; the Broker must not depend on it`
	"example.com/m/internal/warden" // want `R2: example.com/m/internal/broker may not import example.com/m/internal/warden; the Broker must not depend on it`
)

func Run() { agent.Run(); warden.Run() }
