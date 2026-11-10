"""Storage on one SQLite file, through SQLAlchemy Core, with blobs as files beside it."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine

from delve.storage.sqlite.accounts_repo import (
    SqliteAccountLinkRepository,
    SqliteAccountRepository,
    SqliteIdentityRepository,
)
from delve.storage.sqlite.blobs import SqliteBlobStore
from delve.storage.sqlite.board_repo import SqliteBoardRepository
from delve.storage.sqlite.campaign_maps_repo import SqliteCampaignMapRepository
from delve.storage.sqlite.campaigns_repo import SqliteCampaignRepository
from delve.storage.sqlite.characters_repo import SqliteCharacterRepository
from delve.storage.sqlite.combat_rounds_repo import SqliteCombatRoundRepository
from delve.storage.sqlite.combats_repo import SqliteCombatRepository
from delve.storage.sqlite.conversions_repo import SqliteConversionRepository
from delve.storage.sqlite.db import Database
from delve.storage.sqlite.histories_repo import SqliteCarryRepository, SqliteHistoryRepository
from delve.storage.sqlite.house_rules_repo import (
    SqliteBundleRepository,
    SqliteCampaignHouseRulesRepository,
    SqliteHouseRuleRepository,
)
from delve.storage.sqlite.join_requests_repo import SqliteJoinRequestRepository
from delve.storage.sqlite.login_sessions_repo import SqliteLoginSessionRepository
from delve.storage.sqlite.mail_repo import SqliteMailRepository
from delve.storage.sqlite.map_states_repo import SqliteMapStateRepository
from delve.storage.sqlite.module_comments_repo import SqliteModuleCommentRepository
from delve.storage.sqlite.module_sources_repo import SqliteModuleSourceRepository
from delve.storage.sqlite.module_texts_repo import SqliteModuleTextRepository
from delve.storage.sqlite.modules_repo import (
    SqliteModuleCategoryRepository,
    SqliteModuleRepository,
    SqliteRevisionRepository,
)
from delve.storage.sqlite.notes_repo import SqliteNoteRepository, SqliteSessionRepository
from delve.storage.sqlite.novels_repo import SqliteNovelRepository
from delve.storage.sqlite.play_repos import (
    SqliteCampaignStateRepository,
    SqliteEventRepository,
    SqliteRollRepository,
)
from delve.storage.sqlite.seats_repo import SqliteSeatRepository
from delve.storage.sqlite.setting_repos import (
    SqliteProposalRepository,
    SqliteSettingFactRepository,
    SqliteSettingMapRepository,
    SqliteSettingPageRepository,
)
from delve.storage.sqlite.settings_repo import SqliteSettingsRepository
from delve.storage.sqlite.snapshots_repo import SqliteBackupItemRepository, SqliteSnapshotRepository
from delve.storage.sqlite.table_repos import (
    SqliteBeatRepository,
    SqliteDmLogRepository,
    SqliteDmSessionRepository,
    SqlitePlaySettingsRepository,
    SqliteStoryRepository,
    SqliteTableSessionRepository,
    SqliteTranslationRepository,
)
from delve.storage.sqlite.world_repos import (
    SqliteCampaignFactRepository,
    SqliteCampaignImageRepository,
    SqliteClockRepository,
    SqliteFactionRepository,
    SqliteMerchantRepository,
    SqliteMonsterPictureRepository,
    SqlitePossessionRepository,
    SqliteQuestRepository,
    SqliteWorldMapRepository,
    SqliteWorldPictureRepository,
)


class SqliteStorage:
    def __init__(self, engine: Engine, blobs_dir: Path) -> None:
        self.engine = engine
        self.db = Database(engine)
        self.settings = SqliteSettingsRepository(self.db)
        self.modules = SqliteModuleRepository(self.db)
        self.module_categories = SqliteModuleCategoryRepository(self.db)
        self.revisions = SqliteRevisionRepository(self.db)
        self.module_texts = SqliteModuleTextRepository(self.db)
        self.module_sources = SqliteModuleSourceRepository(self.db)
        self.campaigns = SqliteCampaignRepository(self.db)
        self.seats = SqliteSeatRepository(self.db)
        self.join_requests = SqliteJoinRequestRepository(self.db)
        self.board = SqliteBoardRepository(self.db)
        self.accounts = SqliteAccountRepository(self.db)
        self.account_links = SqliteAccountLinkRepository(self.db)
        self.mail = SqliteMailRepository(self.db)
        self.account_identities = SqliteIdentityRepository(self.db)
        self.login_sessions = SqliteLoginSessionRepository(self.db)
        self.characters = SqliteCharacterRepository(self.db)
        self.map_states = SqliteMapStateRepository(self.db)
        self.campaign_maps = SqliteCampaignMapRepository(self.db)
        self.blobs = SqliteBlobStore(self.db, blobs_dir)
        self.campaign_states = SqliteCampaignStateRepository(self.db)
        self.rolls = SqliteRollRepository(self.db)
        self.events = SqliteEventRepository(self.db)
        self.combats = SqliteCombatRepository(self.db)
        self.combat_rounds = SqliteCombatRoundRepository(self.db)
        self.notes = SqliteNoteRepository(self.db)
        self.sessions = SqliteSessionRepository(self.db)
        self.house_rules = SqliteHouseRuleRepository(self.db)
        self.house_rule_bundles = SqliteBundleRepository(self.db)
        self.campaign_house_rules = SqliteCampaignHouseRulesRepository(self.db)
        self.beats = SqliteBeatRepository(self.db)
        self.story = SqliteStoryRepository(self.db)
        self.translations = SqliteTranslationRepository(self.db)
        self.dm_log = SqliteDmLogRepository(self.db)
        self.dm_sessions = SqliteDmSessionRepository(self.db)
        self.play_settings = SqlitePlaySettingsRepository(self.db)
        self.table_sessions = SqliteTableSessionRepository(self.db)
        self.conversions = SqliteConversionRepository(self.db)
        self.module_comments = SqliteModuleCommentRepository(self.db)
        self.factions = SqliteFactionRepository(self.db)
        self.clocks = SqliteClockRepository(self.db)
        self.quests = SqliteQuestRepository(self.db)
        self.campaign_facts = SqliteCampaignFactRepository(self.db)
        self.possessions = SqlitePossessionRepository(self.db)
        self.world_maps = SqliteWorldMapRepository(self.db)
        self.merchants = SqliteMerchantRepository(self.db)
        self.campaign_images = SqliteCampaignImageRepository(self.db)
        self.world_pictures = SqliteWorldPictureRepository(self.db)
        self.monster_pictures = SqliteMonsterPictureRepository(self.db)
        self.setting_pages = SqliteSettingPageRepository(self.db)
        self.setting_facts = SqliteSettingFactRepository(self.db)
        self.proposals = SqliteProposalRepository(self.db)
        self.setting_maps = SqliteSettingMapRepository(self.db)
        self.novels = SqliteNovelRepository(self.db)
        self.histories = SqliteHistoryRepository(self.db)
        self.carries = SqliteCarryRepository(self.db)
        self.snapshots = SqliteSnapshotRepository(self.db)
        self.backup_items = SqliteBackupItemRepository(self.db)

    @contextmanager
    def transaction(self) -> Iterator[None]:
        with self.db.transaction():
            yield

    @contextmanager
    def reading(self) -> Iterator[None]:
        with self.db.reading():
            yield

    def close(self) -> None:
        self.engine.dispose()
