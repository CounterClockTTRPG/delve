"""Ask the DM on an SRD 3.5 campaign: the asker's character reads with the engine's numbers, AC, BAB and saves, in place
of AC and THAC0, which a d20 party digest leaves out (the 502 of 2026-11-19)."""

from __future__ import annotations

from delve.dm.fake import FakeDM
from delve.domain.settings import BackendChoice
from delve.play import seats
from delve.play.ask import ask_prompt
from delve.play.table import AppServices


def test_ask_prompt_reads_a_d20_characters_numbers(srd35_storage, srd35_campaign):
    from tests.fixtures.rulesets import srd35_catalogs

    storage, campaign = srd35_storage, srd35_campaign
    dm = FakeDM([])
    services = AppServices(
        storage=storage,
        catalogs=srd35_catalogs(),
        spec_lookup=lambda name: None,
        dm=lambda campaign_id: (dm, BackendChoice("fake", "fake-large")),
        side=lambda campaign_id: (dm, BackendChoice("fake", "fake-small")),
        publish=lambda kind, data, **where: None,
    )
    asker = seats.owner_seat(storage, campaign.id)
    bram = storage.characters.create(campaign.id, "Bram")
    seats.claim(storage, bram.id, asker)

    prompt = ask_prompt(services, campaign.id, "How hard is Bram to hit?", asker)

    line = next(line for line in prompt.splitlines() if line.startswith("- Bram"))
    assert "THAC0" not in line
    assert "AC " in line and "touch " in line and "flat-footed " in line and "BAB " in line and "Will " in line
