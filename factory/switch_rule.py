"""The switch rule (docs/factory/README.md, docs/adr/0003).

While only the owner's work is involved, the factory's Claude Code runs on the
owner's subscription token. It must switch to an OpenRouter key before anyone
else's issue or PR is acted on, before an unattended scheduled job runs, or if
it strains subscription usage.

The owner makes the switch by setting the repository variable
FACTORY_CLAUDE_LOGIN to `openrouter`. The first two conditions can be checked
in code, so every agent step checks them and refuses to start on the
subscription token when either holds. The third is the owner's judgement.
"""

from typing import Iterable, Optional

SUBSCRIPTION = "subscription"
OPENROUTER = "openrouter"
LOGINS = (SUBSCRIPTION, OPENROUTER)


def is_factory_app(login: str, app_slug: str) -> bool:
    """GitHub names the App `<slug>[bot]` in event payloads and `app/<slug>`
    in the gh CLI's JSON; both are the factory itself."""
    return bool(app_slug) and login.lower() in (f"{app_slug}[bot]".lower(), f"app/{app_slug}".lower())


def others(authors: Iterable[str], owner: str, app_slug: str) -> list:
    """The authors who are neither the repo owner nor the factory App."""
    return sorted({a for a in authors
                   if a and a.lower() != owner.lower() and not is_factory_app(a, app_slug)})


def refusal(login: str, authors: Iterable[str], owner: str, app_slug: str,
            scheduled: bool = False) -> Optional[str]:
    """Why this run may not start on the configured login, or None if it may.

    authors are the people whose work the run acts on: the Ticket's author,
    the PR's author. A run on the OpenRouter key may act on anyone's work."""
    if login not in LOGINS:
        return (f"FACTORY_CLAUDE_LOGIN is {login!r}; it must be one of "
                f"{', '.join(LOGINS)}")
    if login == OPENROUTER:
        return None
    if scheduled:
        return ("an unattended scheduled run never uses the subscription token; "
                "set FACTORY_CLAUDE_LOGIN to openrouter")
    strangers = others(authors, owner, app_slug)
    if strangers:
        return (f"this work is by {', '.join(strangers)}, not the owner, so the switch rule "
                "forbids the subscription token; set FACTORY_CLAUDE_LOGIN to openrouter "
                "and re-run")
    return None
