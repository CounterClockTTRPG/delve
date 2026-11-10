"""The doubles of the private Greyhawk and Realms packs (`tests/fixtures/packs`), for a test that needs a setting's
class, calendar or map without a catalog: loaded as packs are (`tests.fixtures.rulesets`), then imported."""

from tests.fixtures.rulesets import osric_packs

osric_packs()  # puts the doubles' packages on the path, as the loader does

from delve_fixture_greyhawk.pack import GREYHAWK_CALENDAR, GreyhawkSetting
from delve_fixture_realms.pack import HARPTOS_CALENDAR, RealmsSetting

__all__ = ["GREYHAWK_CALENDAR", "HARPTOS_CALENDAR", "GreyhawkSetting", "RealmsSetting"]
