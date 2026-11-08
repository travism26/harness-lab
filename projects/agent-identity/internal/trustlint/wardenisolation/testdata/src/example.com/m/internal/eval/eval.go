package eval // want package:"reaches example.com/m/internal/modelclient via example.com/m/internal/modelclient"

import "example.com/m/internal/modelclient"

func Do() { modelclient.Call() }
