"""The total state and the menu of the tray icon, without Qt (feature 0020).

The tones are the tones of the sidebar dots (``service_state.STATES``), so the
tray and the window always agree.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from .accounts import Account
from .service_state import AccountStatus

DANGER = "danger"
WARNING = "warning"
SUCCESS = "success"

LABEL = "label"
ACTION = "action"
RESYNC = "resync"
"""An item that opens the window with the confirmation. The tray never starts a resync itself."""

_ACTION_TEXTS = {"restart": "Restart {name}", "start": "Start {name}"}


@dataclass(frozen=True)
class MenuItem:
    kind: str
    text: str
    confdir: str = ""


def total_tone(statuses: Iterable[AccountStatus]) -> str:
    """``danger`` if 1 account has it, else ``warning`` if 1 account has it, else ``success``."""
    tones = {status.state.tone for status in statuses}
    if DANGER in tones:
        return DANGER
    if WARNING in tones:
        return WARNING
    return SUCCESS


def _status(statuses: Mapping[str, AccountStatus], account: Account) -> AccountStatus | None:
    return statuses.get(str(account.confdir))


def tooltip(accounts: list[Account], statuses: Mapping[str, AccountStatus]) -> str:
    lines = ["Skyhus"]
    for account in accounts:
        status = _status(statuses, account)
        if status is not None:
            lines.append(f"{account.name}: {status.state.label}")
    return "\n".join(lines)


def menu_items(accounts: list[Account], statuses: Mapping[str, AccountStatus]) -> list[MenuItem]:
    """1 line per account and the action for its state, if it has one."""
    items = []
    for account in accounts:
        status = _status(statuses, account)
        if status is None:
            continue
        confdir = str(account.confdir)
        items.append(MenuItem(LABEL, f"{account.name} — {status.state.label}", confdir))
        action = status.state.action if account.service else ""
        if action in _ACTION_TEXTS:
            items.append(MenuItem(ACTION, _ACTION_TEXTS[action].format(name=account.name), confdir))
        elif action == "resync":
            items.append(MenuItem(RESYNC, f"Restart {account.name} with resync …", confdir))
    return items
