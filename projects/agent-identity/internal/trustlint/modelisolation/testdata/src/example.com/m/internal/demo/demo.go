package demo

import (
	"example.com/m/internal/modelclient"       // want `R1: example.com/m/internal/demo may not import example.com/m/internal/modelclient; only example.com/m/internal/agent may`
	_ "example.com/m/internal/modelclient/sub" // want `R1: example.com/m/internal/demo may not import example.com/m/internal/modelclient/sub; only example.com/m/internal/agent may`
)

func Run() { modelclient.Call() }
