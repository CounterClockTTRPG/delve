"""Who a table's mail goes to (DEL-314): shared by the schedule's "tell the players" and the host's message."""

from __future__ import annotations

from delve.domain.accounts import Account
from delve.mail import outbox
from delve.mail.compose import Kind
from delve.play import seats


def recipients(
    storage, campaign_id: str, kind: Kind, *, seat_ids: list[str] | None, sender_seat_id: str
) -> list[Account]:
    """The accounts at the table that a message of `kind` may reach: the live host, co-hosts and players
    (`seats.at_the_table`, no observers), host first, without the sender's own account and without repeats, only those
    with an address for `kind` now (`outbox.address_for`). `seat_ids` narrows it to those seats (None: all)."""
    sender = storage.seats.get(sender_seat_id)
    mine = seats.shown_account(storage, sender) if sender is not None else None
    found: dict[str, Account] = {}
    for seat in seats.at_the_table(storage, campaign_id):
        if seat_ids is not None and seat.id not in seat_ids:
            continue
        account = seats.shown_account(storage, seat)
        if account is None or (mine is not None and account.id == mine.id) or account.id in found:
            continue
        if outbox.address_for(account, kind) is not None:
            found[account.id] = account
    return list(found.values())
