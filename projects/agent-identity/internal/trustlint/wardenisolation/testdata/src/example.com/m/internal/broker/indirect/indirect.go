package indirect // want package:"reaches example.com/m/internal/agent via example.com/m/internal/helper -> example.com/m/internal/agent"

import (
	"example.com/m/internal/helper" // want `R2: example.com/m/internal/broker/indirect may not import example.com/m/internal/helper, which reaches example.com/m/internal/agent \(example.com/m/internal/helper -> example.com/m/internal/agent\)`
)

func Run() { helper.Do() }
