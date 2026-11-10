"""Who a table's mail goes to (DEL-314): the live host, co-hosts and players with an address for the kind, not the
one who made the change, not an observer."""

from dataclasses import replace

from delve.mail.table_mail import recipients
from tests.mail.conftest import with_address
from tests.web.test_join_api import campaign  # noqa: F401


def seat_for(storage, campaign_id, name, role, account=None):
    return storage.seats.create(campaign_id, name, "en", role, account_id=None if account is None else account.id)


def test_recipients_are_the_reachable_others_at_the_table(storage, campaign):  # noqa: F811
    host = with_address(storage, "hostess")
    ana = with_address(storage, "ana")
    bob = with_address(storage, "bob")
    cy = with_address(storage, "cy")
    quiet = with_address(storage, "quiet")
    storage.accounts.set_mail_switches(quiet.id, mail_host=False, mail_board=True)
    nobody = storage.accounts.create("nomail", replace(ana.profile))
    hs = seat_for(storage, campaign.id, "H", "host", host)
    seat_for(storage, campaign.id, "Ana", "player", ana)
    seat_for(storage, campaign.id, "Bob", "cohost", bob)
    seat_for(storage, campaign.id, "Cy", "observer", cy)
    seat_for(storage, campaign.id, "Q", "player", quiet)
    seat_for(storage, campaign.id, "N", "player", nobody)
    left = seat_for(storage, campaign.id, "Gone", "player", with_address(storage, "gone"))
    storage.seats.save(replace(left, left_at="2026-10-01T00:00:00+00:00"))
    got = recipients(storage, campaign.id, "schedule", seat_ids=None, sender_seat_id=hs.id)
    assert sorted(a.username for a in got) == ["ana", "bob"]


def test_a_chosen_list_narrows_it(storage, campaign):  # noqa: F811
    host = with_address(storage, "hostess")
    ana, bob = with_address(storage, "ana"), with_address(storage, "bob")
    hs = seat_for(storage, campaign.id, "H", "host", host)
    a = seat_for(storage, campaign.id, "Ana", "player", ana)
    seat_for(storage, campaign.id, "Bob", "player", bob)
    got = recipients(storage, campaign.id, "host", seat_ids=[a.id], sender_seat_id=hs.id)
    assert [x.username for x in got] == ["ana"]
    assert recipients(storage, campaign.id, "host", seat_ids=[], sender_seat_id=hs.id) == []
