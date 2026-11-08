package indirect // want package:"reaches example.com/m/internal/agent via example.com/m/internal/deep -> example.com/m/internal/helper -> example.com/m/internal/agent, example.com/m/internal/modelclient via example.com/m/internal/eval -> example.com/m/internal/modelclient"

import (
	"example.com/m/internal/deep"   // want `R2: example.com/m/internal/warden/indirect may not import example.com/m/internal/deep, which reaches example.com/m/internal/agent \(example.com/m/internal/deep -> example.com/m/internal/helper -> example.com/m/internal/agent\)`
	"example.com/m/internal/eval"   // want `R2: example.com/m/internal/warden/indirect may not import example.com/m/internal/eval, which reaches example.com/m/internal/modelclient \(example.com/m/internal/eval -> example.com/m/internal/modelclient\)`
	"example.com/m/internal/helper" // want `R2: example.com/m/internal/warden/indirect may not import example.com/m/internal/helper, which reaches example.com/m/internal/agent \(example.com/m/internal/helper -> example.com/m/internal/agent\)`
)

func Run() { deep.Do(); eval.Do(); helper.Do() }
