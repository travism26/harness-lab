package viabrokerhelper // want package:"reaches example.com/m/internal/agent via example.com/m/internal/usesbroker -> example.com/m/internal/broker -> example.com/m/internal/agent, example.com/m/internal/broker via example.com/m/internal/usesbroker -> example.com/m/internal/broker, example.com/m/internal/modelclient via example.com/m/internal/usesbroker -> example.com/m/internal/broker -> example.com/m/internal/warden -> example.com/m/internal/modelclient, example.com/m/internal/warden via example.com/m/internal/usesbroker -> example.com/m/internal/broker -> example.com/m/internal/warden"

import (
	// The Broker in these fixtures imports the Warden and the Agent, so a Warden
	// package that reaches the Broker reaches them too.
	"example.com/m/internal/usesbroker" // want `R2: example.com/m/internal/warden/viabrokerhelper may not import example.com/m/internal/usesbroker, which reaches example.com/m/internal/agent \(example.com/m/internal/usesbroker -> example.com/m/internal/broker -> example.com/m/internal/agent\)` `R2: example.com/m/internal/warden/viabrokerhelper may not import example.com/m/internal/usesbroker, which reaches example.com/m/internal/broker \(example.com/m/internal/usesbroker -> example.com/m/internal/broker\)` `R2: example.com/m/internal/warden/viabrokerhelper may not import example.com/m/internal/usesbroker, which reaches example.com/m/internal/modelclient \(example.com/m/internal/usesbroker -> example.com/m/internal/broker -> example.com/m/internal/warden -> example.com/m/internal/modelclient\)`
)

func Run() { usesbroker.Run() }
