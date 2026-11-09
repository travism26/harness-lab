package main

import (
	"example.com/m/internal/agent"       // want `R2: example.com/m/cmd/broker may not import example.com/m/internal/agent; the Broker must not depend on it`
	"example.com/m/internal/eval"        // want `R2: example.com/m/cmd/broker may not import example.com/m/internal/eval; the Broker must not depend on it`
	"example.com/m/internal/helper"      // want `R2: example.com/m/cmd/broker may not import example.com/m/internal/helper, which reaches example.com/m/internal/agent \(example.com/m/internal/helper -> example.com/m/internal/agent\)`
	"example.com/m/internal/modelclient" // want `R2: example.com/m/cmd/broker may not import example.com/m/internal/modelclient; the Broker must not depend on it`
	"example.com/m/internal/warden"      // want `R2: example.com/m/cmd/broker may not import example.com/m/internal/warden; the Broker must not depend on it`
)

func main() { agent.Run(); eval.Do(); helper.Do(); modelclient.Call(); warden.Run() }
