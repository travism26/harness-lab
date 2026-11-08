package warden

// seedUser is what the Warden knows about one User: their Tenant and their one
// Role.
type seedUser struct {
	Tenant string
	Role   string
}

// seedUsers is the Seed data: every User the Warden knows, by tenant/name id.
var seedUsers = map[string]seedUser{
	"acme/alice": {Tenant: "acme", Role: "Access Auditor"},
	"acme/tom":   {Tenant: "acme", Role: "Finance Approver"},
	"acme/bob":   {Tenant: "acme", Role: "Employee"},
	"globex/tom": {Tenant: "globex", Role: "Finance Approver"},
	"globex/sam": {Tenant: "globex", Role: "Access Auditor"},
}

// permissionRead is the Permission that lets a Caller look up another User in
// their own Tenant.
const permissionRead = "permission:read"

// seedRoles is the Role catalog: the Permissions each Role holds.
var seedRoles = map[string][]string{
	"Access Auditor":   {permissionRead},
	"Finance Approver": {"invoice:approve", "invoice:read"},
	"Employee":         {"invoice:read"},
}

// roleHolds reports whether the Role holds the Permission.
func roleHolds(role, permission string) bool {
	for _, p := range seedRoles[role] {
		if p == permission {
			return true
		}
	}
	return false
}

// knownPermission reports whether any Role holds the Permission: the
// Permission catalog is the union of every Role's Permissions.
func knownPermission(permission string) bool {
	for role := range seedRoles {
		if roleHolds(role, permission) {
			return true
		}
	}
	return false
}
