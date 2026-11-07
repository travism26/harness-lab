# agent-identity

The AI permission assistant: an Agent with its own SPIFFE identity asks the Warden read-only questions about who holds which Permission, and the Warden decides with fixed rules, never a model. Lab-wide terms (Project, Stand-in service and the rest) are in the [root glossary](../../GLOSSARY.md). SPIFFE's own terms (SPIFFE ID, JWT-SVID, trust domain, Workload API) are used as defined in [SPIFFE concepts](https://spiffe.io/docs/latest/spiffe-about/spiffe-concepts/).

## Language

### Who takes part

**Agent**:
The workload that holds its own SPIFFE identity, takes a Caller's question and asks the Warden on the Caller's behalf.
_Avoid_: Assistant, agent service, bot

**Warden**:
The Stand-in service that verifies the Agent's JWT-SVID, makes the Lookup check and reads Seed data to give an Answer. It decides with fixed rules, never with a model.
_Avoid_: CAM, mock, access service, permission service, auth server

**User**:
A synthetic person in the Seed data. Any User can be the Caller or the Target of a Lookup.
_Avoid_: Account, member, employee

**Caller**:
The User whose question the Agent is answering, and on whose behalf it asks the Warden.
_Avoid_: User (alone), end user, requester, principal, subject

**Target**:
The User a Lookup asks about. The Caller and the Target can be the same User.
_Avoid_: Target user, subject

### What the Warden holds

**Tenant**:
A synthetic organization, such as acme or globex, that holds its own Users and their Permissions. Every User belongs to exactly one Tenant.
_Avoid_: Org, organization, account, workspace

**Permission**:
A named thing a User may do in their Tenant, written `resource:verb`, such as `invoice:approve`.
_Avoid_: Action, right, privilege, scope, entitlement

**Role**:
A named set of Permissions given to Users, such as Finance Approver.
_Avoid_: Group, position

**Seed data**:
The fixed synthetic Tenants, Users, Roles and Permissions the Warden reads. Never real data, never changed at run time.
_Avoid_: Fixtures, mock data, test data, database

**Agent allowlist**:
The Warden's list of SPIFFE IDs that may make Lookups at all.
_Avoid_: Whitelist, ACL, trusted agents

### Asking and answering

**Model**:
The language model the Agent consults to turn a Caller's question into a Proposal. It never sees what the Warden returns.
_Avoid_: LLM, AI, assistant

**Model client**:
The one part of the Agent that talks to the Model: it asks for a Proposal, checks it, and either returns it or reports why it failed. It knows nothing about the Caller.
_Avoid_: Harness, LLM client, SDK, wrapper

**Proposal**:
The Model's structured suggestion of a Lookup: a Target and a Permission. The Tenant and the Caller come from the Login, never from the Model. Not trusted until the Agent has checked it.
_Avoid_: Request, intent, query

**Lookup**:
The one read-only question the Agent asks the Warden: does this Target hold this Permission?
_Avoid_: Query, request, check

**Lookup check**:
The Warden's decision on whether this Caller may make this Lookup about this Target, made before any Seed data about the Target is read.
_Avoid_: Access check, authorization, inspection

**Answer**:
The result of an allowed Lookup: yes or no, and on yes, the Role the Permission comes from. A "no" is an Answer, never a Denial.
_Avoid_: Result, verdict, decision

**Denial**:
The Warden refusing a Lookup. It reveals nothing about whether the Target exists or what they hold.
_Avoid_: No, rejection, forbidden

**Reply**:
What the Agent tells the Caller, built by fixed rules from an Answer, a Denial or a failure. Never the Model's own words.
_Avoid_: Response, explanation, output

### Who the Caller is

**Login**:
The fixed synthetic step that establishes the Caller to the Agent and signs the Caller assertion. Demo-only, not real authentication.
_Avoid_: Auth, sign-in, session

**Caller assertion**:
The Login's signed, short-lived statement of who the Caller is and which Agent may act for them. The Agent carries it untouched to the Warden alongside its JWT-SVID, and the Warden trusts it only once the signature verifies and it names that Agent. Never taken from model output, a request body or an unsigned header.
_Avoid_: Caller context, session, delegation, on-behalf-of token
