package deep // want package:"reaches example.com/m/internal/agent via example.com/m/internal/helper -> example.com/m/internal/agent"

import "example.com/m/internal/helper"

func Do() { helper.Do() }
