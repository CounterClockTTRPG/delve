"""The tables, as SQLAlchemy Core `Table` objects. Migrations, not `create_all`, make them."""

from __future__ import annotations

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    Table,
    Text,
    UniqueConstraint,
    text,
)

metadata = MetaData()

settings = Table(
    "settings",
    metadata,
    Column("key", Text, primary_key=True),
    Column("value", JSON, nullable=False),
    Column("updated_at", Text, nullable=False),
)

modules = Table(
    "modules",
    metadata,
    Column("id", Text, primary_key=True),
    Column("title", Text, nullable=False),
    Column("metadata", JSON, nullable=False),
    Column("created_at", Text, nullable=False),
    Column("updated_at", Text, nullable=False),
    # A draft can't start a campaign until it is marked ready (plan 5 Task 4).
    Column("draft", Boolean, nullable=False, server_default=text("0")),
    # Its entry in the shared library (cloud storage, DEL-110), NULL until it is published or downloaded: the entry's
    # key, the version it is at, that version's `.dscn` hash, `published` or `downloaded`, and who published it.
    Column("library_key", Text, nullable=True),
    Column("library_version", Integer, nullable=True),
    Column("library_hash", Text, nullable=True),
    Column("library_origin", Text, nullable=True),
    Column("library_author", Text, nullable=True),
    # Its category (DEL-114), NULL for none; and its banner (DEL-123): the picture's blob, type and source (`painted`,
    # `uploaded`, `picture:<attachment id>`), and a painting's status (`painting`, `failed`), error and brief.
    Column("category_id", Text, nullable=True),
    Column("banner_blob", Text, nullable=True),
    Column("banner_mime", Text, nullable=True),
    Column("banner_source", Text, nullable=True),
    Column("banner_status", Text, nullable=True),
    Column("banner_error", Text, nullable=True),
    Column("banner_prompt", Text, nullable=True),
)

# The organisers' categories of modules (DEL-114), in their order.
module_categories = Table(
    "module_categories",
    metadata,
    Column("id", Text, primary_key=True),
    Column("name", Text, nullable=False),
    Column("position", Integer, nullable=False),
)

# The working copy's maps, in the order they were first put (`position`).
module_maps = Table(
    "module_maps",
    metadata,
    Column("module_id", Text, ForeignKey("modules.id", ondelete="CASCADE"), primary_key=True),
    Column("name", Text, primary_key=True),
    Column("position", Integer, nullable=False),
    Column("role", Text, nullable=False),
    Column("source", Text, nullable=False),
    Column("is_default", Boolean, nullable=False),
)

# Immutable snapshots; `maps` is a JSON list of {name, role, source, is_default}, `text` the working copy's text then,
# `source` its source then (None for a revision made before sources, until the module's source is first read).
module_revisions = Table(
    "module_revisions",
    metadata,
    Column("module_id", Text, ForeignKey("modules.id", ondelete="CASCADE"), primary_key=True),
    Column("number", Integer, primary_key=True),
    Column("title", Text, nullable=False),
    Column("metadata", JSON, nullable=False),
    Column("maps", JSON, nullable=False),
    Column("created_at", Text, nullable=False),
    Column("text", JSON, nullable=True),
    Column("source", JSON, nullable=True),
)

# The working copy's text, keys and entities: `delve.modules.text.ModuleText.to_json`. A module without text has no
# row. The full-text index of each revision's sections, `module_text_index`, is an FTS5 table the repository queries
# with SQL of its own.
module_texts = Table(
    "module_texts",
    metadata,
    Column("module_id", Text, ForeignKey("modules.id", ondelete="CASCADE"), primary_key=True),
    Column("text", JSON, nullable=False),
    Column("updated_at", Text, nullable=False),
)

# The working copy's source: `delve.modules.source.ModuleSource.to_json`, its texts, entities, keys and attachments.
module_sources = Table(
    "module_sources",
    metadata,
    Column("module_id", Text, ForeignKey("modules.id", ondelete="CASCADE"), primary_key=True),
    Column("source", JSON, nullable=False),
    Column("updated_at", Text, nullable=False),
)

# A module with campaigns can't be deleted: the foreign keys restrict it.
campaigns = Table(
    "campaigns",
    metadata,
    Column("id", Text, primary_key=True),
    Column("name", Text, nullable=False),
    Column("module_id", Text, ForeignKey("modules.id", ondelete="RESTRICT"), nullable=False),
    Column("revision", Integer, nullable=False),
    Column("created_at", Text, nullable=False),
    Column("ruleset", Text, nullable=False, server_default="adnd2e"),
    Column("setting", Text, nullable=True),
    # The token of the join link (plan 4 Task 1); a new one replaces it, and the old link stops working.
    Column("join_token", Text, nullable=True),
    # in_progress, paused or complete (plan 7 Task 1): an open enum, kept as text.
    Column("status", Text, nullable=False, server_default="in_progress"),
    # Voice at the table, `allowed` or `off`, and the initiative mode, `combatant` or `side` (table voice and fixes
    # Task 0), both set by the host.
    Column("voice", Text, nullable=False, server_default="allowed"),
    Column("initiative", Text, nullable=False, server_default="combatant"),
    # Who may watch (DEL-215): anyone with the link, those a host lets in, or nobody.
    Column("observers", Text, nullable=False, server_default="anyone"),
    # The table's listing (DEL-204): `private` or `public`, the players' description, and the places for players
    # (null: no limit).
    Column("visibility", Text, nullable=False, server_default="private"),
    Column("description", Text, nullable=False, server_default=""),
    Column("slots", Integer, nullable=True),
    # The table's schedule (DEL-204 part C), JSON: its rule and the host's changes to single sessions; null for none.
    Column("schedule", JSON, nullable=True),
    ForeignKeyConstraint(
        ["module_id", "revision"],
        ["module_revisions.module_id", "module_revisions.number"],
        ondelete="RESTRICT",
    ),
    Index("uq_campaigns_join_token", "join_token", unique=True),
)

# Accounts (players and tavern Task B1): a person who logs in, with their profile and rights: `organiser`, and
# `owner`, every right of the install's owner (the human's ruling of 2026-10-24). `username` is case-folded;
# `password_hash` is null until a set-password link is used; `external_id` is reserved for an outside identity
# provider's subject, and nothing writes it yet.
accounts = Table(
    "accounts",
    metadata,
    Column("id", Text, primary_key=True),
    Column("username", Text, nullable=False, unique=True),
    Column("password_hash", Text, nullable=True),
    Column("created_at", Text, nullable=False),
    Column("disabled_at", Text, nullable=True),
    Column("organiser", Boolean, nullable=False, server_default=text("0")),
    Column("owner", Boolean, nullable=False, server_default=text("0")),
    Column("external_id", Text, nullable=True, unique=True),
    Column("display_name", Text, nullable=False),
    Column("pronouns", Text, nullable=False, server_default=""),
    Column("avatar_emblem", Text, nullable=True),
    Column("avatar_sha", Text, nullable=True),
    Column("colour", Text, nullable=False, server_default="teal"),
    Column("language", Text, nullable=False, server_default="en"),
    Column("about", Text, nullable=False, server_default=""),
    Column("host_note", Text, nullable=False, server_default=""),
    Column("time_zone", Text, nullable=True),
    # A sign-up waiting for the owner's or an organiser's approval, with what it told them (DEL-156).
    Column("pending", Boolean, nullable=False, server_default=text("0")),
    Column("request_note", Text, nullable=False, server_default=""),
    # When the player asked for a new password from the login page, until it is answered or dismissed (DEL-268).
    Column("reset_asked_at", Text, nullable=True),
    # The confirmed address, one typed in and waiting for its link, and the switches for a host's and the board's mail
    # (DEL-314).
    Column("email", Text, nullable=True),
    Column("email_pending", Text, nullable=True),
    Column("mail_host", Boolean, nullable=False, server_default=text("1")),
    Column("mail_board", Boolean, nullable=False, server_default=text("1")),
)

# One-time links that confirm an address, known only by their token's SHA-256 hex digest (DEL-314).
email_confirmations = Table(
    "email_confirmations",
    metadata,
    Column("token_hash", Text, primary_key=True),
    Column("account_id", Text, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
    Column("address", Text, nullable=False),
    Column("created_at", Text, nullable=False),
    Column("expires_at", Text, nullable=False),
    Column("used_at", Text, nullable=True),
    Index("ix_email_confirmations_account", "account_id"),
)

# Mail waiting to go, sent or given up. It keeps no recipient address (DEL-314).
mail_outbox = Table(
    "mail_outbox",
    metadata,
    Column("id", Text, primary_key=True),
    Column("kind", Text, nullable=False),
    Column("account_id", Text, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
    Column("language", Text, nullable=False),
    Column("subject", Text, nullable=False),
    Column("text", Text, nullable=False),
    Column("html", Text, nullable=False),
    Column("reply_to", Text, nullable=True),
    Column("unsubscribe", Text, nullable=True),
    Column("created_at", Text, nullable=False),
    Column("attempts", Integer, nullable=False, server_default="0"),
    Column("next_at", Text, nullable=False),
    Column("sent_at", Text, nullable=True),
    Column("failed_at", Text, nullable=True),
    Column("failure", Text, nullable=False, server_default=""),
    Index("ix_mail_outbox_due", "sent_at", "failed_at", "next_at"),
)

# One-time links that set or reset an account's password, known only by their token's SHA-256 hex digest.
account_links = Table(
    "account_links",
    metadata,
    Column("token_hash", Text, primary_key=True),
    Column("account_id", Text, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
    Column("kind", Text, nullable=False),
    Column("created_at", Text, nullable=False),
    Column("expires_at", Text, nullable=False),
    Column("used_at", Text, nullable=True),
    # Made by an owner: only such a link works for an owner's or an organiser's account (DEL-150).
    Column("by_owner", Boolean, nullable=False, server_default=text("0")),
    Index("ix_account_links_account_id", "account_id"),
)

# An outside identity an account logs in with (DEL-206): a provider's `sub`; one per provider per account.
account_identities = Table(
    "account_identities",
    metadata,
    Column("provider", Text, primary_key=True),
    Column("subject", Text, primary_key=True),
    Column("account_id", Text, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
    Column("email", Text, nullable=False, server_default=text("''")),
    Column("linked_at", Text, nullable=False),
    Index("ix_account_identities_account_provider", "account_id", "provider", unique=True),
)

# A browser logged in to an account (players and tavern Task C1): its token is stored only as its SHA-256 hex digest.
login_sessions = Table(
    "login_sessions",
    metadata,
    Column("id", Text, primary_key=True),
    Column("account_id", Text, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
    Column("token_hash", Text, nullable=False, unique=True),
    Column("created_at", Text, nullable=False),
    Column("last_used_at", Text, nullable=False),
    Column("device", Text, nullable=False, server_default=""),
    Column("address", Text, nullable=False, server_default=""),
    Index("ix_login_sessions_account", "account_id"),
)

# The people at a campaign's table (plan 4 Task 1). `role` is host, cohost, player or observer; one seat per campaign
# is the host. A seat's token is stored only as its SHA-256 hex digest; the owner's seat (`owner`) has none.
seats = Table(
    "seats",
    metadata,
    Column("id", Text, primary_key=True),
    Column("campaign_id", Text, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
    Column("name", Text, nullable=False),
    Column("language", Text, nullable=False),
    Column("role", Text, nullable=False),
    Column("organiser", Boolean, nullable=False, server_default=text("0")),
    Column("owner", Boolean, nullable=False, server_default=text("0")),
    Column("token_hash", Text, nullable=True, unique=True),
    Column("joined_at", Text, nullable=False),
    Column("left_at", Text, nullable=True),
    # The account sitting in the seat (players and tavern Task B1): one live seat per account and campaign.
    Column("account_id", Text, ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True),
    Index("ix_seats_campaign", "campaign_id"),
    Index("uq_seats_one_owner", "campaign_id", unique=True, sqlite_where=text("owner = 1")),
    Index(
        "uq_seats_account_live",
        "campaign_id",
        "account_id",
        unique=True,
        sqlite_where=text("account_id IS NOT NULL AND left_at IS NULL"),
    ),
)

# An account's request to join a public table (DEL-204): `pending`, `accepted`, `declined` or `withdrawn`, with its
# thread of messages between the player and the hosts (JSON, oldest first), when it was decided and the seat an accept
# made. One pending request per account and table.
join_requests = Table(
    "join_requests",
    metadata,
    Column("id", Text, primary_key=True),
    Column("campaign_id", Text, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
    Column("account_id", Text, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
    Column("status", Text, nullable=False),
    Column("messages", JSON, nullable=False),
    Column("created_at", Text, nullable=False),
    Column("decided_at", Text, nullable=True),
    Column("seat_id", Text, ForeignKey("seats.id", ondelete="SET NULL"), nullable=True),
    # A player's request, or an observer's at a table whose watchers a host lets in (DEL-215).
    Column("role", Text, nullable=False, server_default="player"),
    Index("ix_join_requests_campaign", "campaign_id"),
    Index("ix_join_requests_account", "account_id"),
    Index(
        "uq_join_requests_one_pending",
        "campaign_id",
        "account_id",
        unique=True,
        sqlite_where=text("status = 'pending'"),
    ),
)

# The message board (DEL-297). A zone is the site's or a table's own (`campaign_id`, one zone per campaign, set null
# when the campaign goes); `read` and `write` are its levels, `moderators` and `members` JSON lists of account ids.
# Topics, posts and read marks follow their zone and topic. No keys to accounts: an author's id may outlive the account.
board_zones = Table(
    "board_zones",
    metadata,
    Column("id", Text, primary_key=True),
    Column("name", Text, nullable=False),
    Column("description", Text, nullable=False, server_default=""),
    Column("position", Integer, nullable=False, server_default="0"),
    Column("read", Text, nullable=False),
    Column("write", Text, nullable=False),
    Column("pictures", Boolean, nullable=False, server_default=text("0")),
    Column("campaign_id", Text, ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True),
    Column("moderators", JSON, nullable=False),
    Column("members", JSON, nullable=False),
    Column("created_at", Text, nullable=False),
    Index("uq_board_zones_campaign", "campaign_id", unique=True),
)

board_topics = Table(
    "board_topics",
    metadata,
    Column("id", Text, primary_key=True),
    Column("zone_id", Text, ForeignKey("board_zones.id", ondelete="CASCADE"), nullable=False),
    Column("title", Text, nullable=False),
    Column("author_id", Text, nullable=True),
    Column("created_at", Text, nullable=False),
    Column("last_post_at", Text, nullable=False),
    Column("last_author_id", Text, nullable=True),
    Column("posts", Integer, nullable=False, server_default="1"),
    Column("pinned", Boolean, nullable=False, server_default=text("0")),
    Column("locked", Boolean, nullable=False, server_default=text("0")),
    Index("ix_board_topics_zone", "zone_id"),
)

# `picture` is `{"blob", "mime", "width", "height"}` or NULL; `removed` is `author` or `moderator`.
board_posts = Table(
    "board_posts",
    metadata,
    Column("id", Text, primary_key=True),
    Column("topic_id", Text, ForeignKey("board_topics.id", ondelete="CASCADE"), nullable=False),
    Column("author_id", Text, nullable=True),
    Column("text", Text, nullable=False),
    Column("created_at", Text, nullable=False),
    Column("edited_at", Text, nullable=True),
    Column("removed", Text, nullable=True),
    Column("picture", JSON, nullable=True),
    Index("ix_board_posts_topic", "topic_id"),
)

# The time of the newest post an account has read in a topic, and the time an account first opened the board.
board_reads = Table(
    "board_reads",
    metadata,
    Column("account_id", Text, nullable=False),
    Column("topic_id", Text, ForeignKey("board_topics.id", ondelete="CASCADE"), nullable=False),
    Column("at", Text, nullable=False),
    PrimaryKeyConstraint("account_id", "topic_id"),
)

# The accounts following a topic, and when each was last mailed about it (DEL-314).
board_follows = Table(
    "board_follows",
    metadata,
    Column("account_id", Text, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False),
    Column("topic_id", Text, ForeignKey("board_topics.id", ondelete="CASCADE"), nullable=False),
    Column("notified_at", Text, nullable=True),
    PrimaryKeyConstraint("account_id", "topic_id"),
)

board_visits = Table(
    "board_visits",
    metadata,
    Column("account_id", Text, primary_key=True),
    Column("first_at", Text, nullable=False),
)

# PCs and NPCs. `sheet` and `state` are `Sheet.to_dict()` and `CharacterState.to_dict()`, the sheet without its
# `label` and `kind`, which are the `name` and `kind` columns. `order` is the marching order (PCs); NPCs have NULL.
# `controller_id` is the seat that plays the character, NULL when none does.
characters = Table(
    "characters",
    metadata,
    Column("id", Text, primary_key=True),
    Column("campaign_id", Text, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("name", Text, nullable=False),
    Column("created_at", Text, nullable=False),
    Column("kind", Text, nullable=False, server_default="pc"),
    Column("sheet", JSON, nullable=False, server_default="{}"),
    Column("state", JSON, nullable=False, server_default="{}"),
    Column("order", Integer, nullable=True),
    Column("controller_id", Text, ForeignKey("seats.id", ondelete="SET NULL"), nullable=True),
    # Why and when a PC left the party (died, retired or left), NULL while it is in it (table voice and fixes Task 0).
    Column("departure", Text, nullable=True),
    Column("departed_at", Text, nullable=True),
)

map_states = Table(
    "map_states",
    metadata,
    Column("campaign_id", Text, ForeignKey("campaigns.id", ondelete="CASCADE"), primary_key=True),
    Column("map_name", Text, primary_key=True),
    Column("state", JSON, nullable=False),
    Column("updated_at", Text, nullable=False),
)

# The bytes are on disk at <data dir>/blobs/<aa>/<sha256>; a row is written only after its file is in place.
blobs = Table(
    "blobs",
    metadata,
    Column("sha256", Text, primary_key=True),
    Column("mime", Text, nullable=False),
    Column("size", Integer, nullable=False),
    Column("created_at", Text, nullable=False),
)

module_blobs = Table(
    "module_blobs",
    metadata,
    Column("module_id", Text, ForeignKey("modules.id", ondelete="CASCADE"), primary_key=True),
    Column("role", Text, primary_key=True),
    Column("sha256", Text, ForeignKey("blobs.sha256", ondelete="RESTRICT"), primary_key=True),
)

# The campaign's clock, session number, coin and loot pile: `CampaignState.to_dict()` less the id. `start_date`
# (`{year, day_of_year}`), `weather` (today's per terrain) and `world` (the party's world position) are NULL until
# play first sets them (plan 6 Task 2).
campaign_state = Table(
    "campaign_state",
    metadata,
    Column("campaign_id", Text, ForeignKey("campaigns.id", ondelete="CASCADE"), primary_key=True),
    Column("day", Integer, nullable=False),
    Column("hour", Integer, nullable=False),
    Column("minute", Integer, nullable=False),
    Column("session", Integer, nullable=False),
    Column("coin", JSON, nullable=False),
    Column("loot", JSON, nullable=False),
    Column("updated_at", Text, nullable=False),
    Column("start_date", JSON, nullable=True),
    Column("weather", JSON, nullable=True),
    Column("world", JSON, nullable=True),
    Column("journey", JSON, nullable=True),
)

# The dice log (spec §6.5). `key` is the JSON of [beat, actor, purpose, target, combat_round]: one roll per key.
rolls = Table(
    "rolls",
    metadata,
    Column("id", Text, primary_key=True),
    Column("campaign_id", Text, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
    Column("key", Text, nullable=False),
    Column("beat", Text, nullable=False),
    Column("actor", Text, nullable=True),
    Column("purpose", Text, nullable=False),
    Column("target", Text, nullable=True),
    Column("combat_round", Integer, nullable=True),
    Column("notation", Text, nullable=False),
    Column("faces", JSON, nullable=False),
    Column("kept", JSON, nullable=False),
    Column("modifier", Integer, nullable=False),
    Column("total", Integer, nullable=False),
    Column("at", Text, nullable=False),
    UniqueConstraint("campaign_id", "key", name="uq_rolls_campaign_key"),
    Index("ix_rolls_campaign_beat", "campaign_id", "beat"),
)

# The story log: what happened, in order.
events = Table(
    "events",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("campaign_id", Text, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
    Column("session", Integer, nullable=False),
    Column("beat", Text, nullable=False),
    Column("type", Text, nullable=False),
    Column("data", JSON, nullable=False),
    Column("at", Text, nullable=False),
    Index("ix_events_campaign_id", "campaign_id", "id"),
)

# Sessions (evenings of play) and their recaps.
sessions = Table(
    "sessions",
    metadata,
    Column("campaign_id", Text, ForeignKey("campaigns.id", ondelete="CASCADE"), primary_key=True),
    Column("number", Integer, primary_key=True),
    Column("title", Text, nullable=False),
    Column("started_at", Text, nullable=False),
    Column("ended_at", Text, nullable=True),
    Column("recap_md", Text, nullable=True),
)

# The DM's notes: `kind` is "secret" (DM-only, may be revealed), "room" (a DM-only note about a room of a map) or
# "log" (a public chronicle line). `related_to` names a character, NPC, place or quest; `tags` is a JSON list.
notes = Table(
    "notes",
    metadata,
    Column("id", Text, primary_key=True),
    Column("campaign_id", Text, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
    Column("kind", Text, nullable=False),
    Column("text", Text, nullable=False),
    Column("tags", JSON, nullable=False),
    Column("related_to", Text, nullable=False, server_default=""),
    Column("revealed", Boolean, nullable=False, server_default="0"),
    Column("map_name", Text, nullable=True),
    Column("node", Text, nullable=True),
    Column("session", Integer, nullable=False),
    Column("created_at", Text, nullable=False),
    Column("updated_at", Text, nullable=False),
    Index("ix_notes_campaign_kind", "campaign_id", "kind"),
)

# Fights, the `Combat` state machine as JSON. At most one per campaign is live (phase other than "ended").
combats = Table(
    "combats",
    metadata,
    Column("id", Text, primary_key=True),
    Column("campaign_id", Text, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
    Column("phase", Text, nullable=False),
    Column("state", JSON, nullable=False),
    Column("created_at", Text, nullable=False),
    Column("updated_at", Text, nullable=False),
    Index(
        "uq_combats_one_live",
        "campaign_id",
        unique=True,
        sqlite_where=text("phase != 'ended'"),
    ),
)

# A fight's rounds as the initiative timeline shows them (table voice and fixes Task 0): each round's slots in
# initiative order (the DM's truth; the timeline route redacts it per seat), its outcomes once resolved, and when the
# table may see them (`released_at`, after the DM's text for the round). `beat_id` has no foreign key: a tool call
# outside a beat has none.
combat_rounds = Table(
    "combat_rounds",
    metadata,
    Column("combat_id", Text, ForeignKey("combats.id", ondelete="CASCADE"), nullable=False),
    Column("round", Integer, nullable=False),
    Column("campaign_id", Text, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
    Column("beat_id", Text, nullable=True),
    Column("mode", Text, nullable=False),
    Column("slots", JSON, nullable=False),
    Column("outcomes", JSON, nullable=True),
    Column("rolled_at", Text, nullable=False),
    Column("resolved_at", Text, nullable=True),
    Column("released_at", Text, nullable=True),
    PrimaryKeyConstraint("combat_id", "round"),
    Index("ix_combat_rounds_campaign", "campaign_id", "combat_id"),
)

# House rules (spec §9): the library is shared by every campaign on the install. `phases` is a JSON list of
# character-creation, level-up, combat, items, behaviour and always; `ruleset`, `setting` and `subject` are NULL for
# "any" (subject: the race, class or item the rule is about).
house_rules = Table(
    "house_rules",
    metadata,
    Column("id", Text, primary_key=True),
    Column("title", Text, nullable=False),
    Column("body_md", Text, nullable=False),
    Column("kind", Text, nullable=False),
    Column("phases", JSON, nullable=False),
    Column("ruleset", Text, nullable=True),
    Column("setting", Text, nullable=True),
    Column("subject", Text, nullable=True),
    Column("enabled", Boolean, nullable=False),
    Column("created_at", Text, nullable=False),
    Column("updated_at", Text, nullable=False),
    Index("ix_house_rules_kind_subject_title", "kind", "subject", "title"),
)

house_rules_bundles = Table(
    "house_rules_bundles",
    metadata,
    Column("id", Text, primary_key=True),
    Column("title", Text, nullable=False),
    Column("description_md", Text, nullable=False),
    Column("created_at", Text, nullable=False),
    Column("updated_at", Text, nullable=False),
)

# A bundle's ordered rule_ids. Deleting a rule takes it out of every bundle.
house_rules_bundle_rules = Table(
    "house_rules_bundle_rules",
    metadata,
    Column("bundle_id", Text, ForeignKey("house_rules_bundles.id", ondelete="CASCADE"), primary_key=True),
    Column("rule_id", Text, ForeignKey("house_rules.id", ondelete="CASCADE"), primary_key=True),
    Column("position", Integer, nullable=False),
)

# A campaign's choice: it points to bundles and single rules, in order, and copies nothing (spec §9).
house_rules_campaign_bundles = Table(
    "house_rules_campaign_bundles",
    metadata,
    Column("campaign_id", Text, ForeignKey("campaigns.id", ondelete="CASCADE"), primary_key=True),
    Column("bundle_id", Text, ForeignKey("house_rules_bundles.id", ondelete="CASCADE"), primary_key=True),
    Column("position", Integer, nullable=False),
)

house_rules_campaign_rules = Table(
    "house_rules_campaign_rules",
    metadata,
    Column("campaign_id", Text, ForeignKey("campaigns.id", ondelete="CASCADE"), primary_key=True),
    Column("rule_id", Text, ForeignKey("house_rules.id", ondelete="CASCADE"), primary_key=True),
    Column("position", Integer, nullable=False),
)

# Beats (spec §7.1). `submissions` is a JSON list of {player, character_ids, kind, text}. At most one beat per
# campaign is current: open (players submit) or running (the DM answers).
beats = Table(
    "beats",
    metadata,
    Column("id", Text, primary_key=True),
    Column("campaign_id", Text, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
    Column("number", Integer, nullable=False),
    Column("status", Text, nullable=False),
    Column("submissions", JSON, nullable=False),
    Column("opened_at", Text, nullable=False),
    Column("closed_at", Text, nullable=True),
    UniqueConstraint("campaign_id", "number", name="uq_beats_campaign_number"),
    Index("uq_beats_one_current", "campaign_id", unique=True, sqlite_where=text("status IN ('open', 'running')")),
)

# The story the players see, numbered by `seq` per campaign. Every payload is player-safe (plan 2b Task 2).
story = Table(
    "story",
    metadata,
    Column("id", Text, primary_key=True),
    Column("campaign_id", Text, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
    Column("beat_id", Text, ForeignKey("beats.id", ondelete="CASCADE"), nullable=True),
    Column("seq", Integer, nullable=False),
    Column("kind", Text, nullable=False),
    Column("payload", JSON, nullable=False),
    Column("at", Text, nullable=False),
    # Who at the table may see it: null for everyone (plan 4 Task 3, `delve.play.audience`).
    Column("audience", JSON, nullable=True),
    UniqueConstraint("campaign_id", "seq", name="uq_story_campaign_seq"),
    # A beat's delete cascades here (DEL-164).
    Index("ix_story_beat", "beat_id"),
)

# A story entry in a language other than English, as far as it is translated (plan 4 Task 7). The entry stays English.
translations = Table(
    "translations",
    metadata,
    Column("entry_id", Text, ForeignKey("story.id", ondelete="CASCADE"), primary_key=True),
    Column("language", Text, primary_key=True),
    Column("text", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("updated_at", Text, nullable=False),
    Column("answer", Text, nullable=True),
)

# The DM's raw stream, event by event: DM-only, for debugging.
dm_log = Table(
    "dm_log",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("campaign_id", Text, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
    Column("beat_id", Text, ForeignKey("beats.id", ondelete="CASCADE"), nullable=True),
    Column("raw", JSON, nullable=False),
    Column("at", Text, nullable=False),
    Index("ix_dm_log_campaign_beat", "campaign_id", "beat_id"),
    # A beat's delete cascades here, and the index above serves no lookup by beat alone (DEL-164).
    Index("ix_dm_log_beat", "beat_id"),
)

# The DM provider's resumable conversation per campaign (the `claude -p` session id) and how big its context is.
dm_sessions = Table(
    "dm_sessions",
    metadata,
    Column("campaign_id", Text, ForeignKey("campaigns.id", ondelete="CASCADE"), primary_key=True),
    Column("provider", Text, nullable=False),
    Column("session_id", Text, nullable=True),
    Column("context_tokens", Integer, nullable=False),
    Column("updated_at", Text, nullable=False),
)

# The campaign's own play settings (tone, detail, and the DM's model and effort over Preferences' choice), as JSON.
play_settings = Table(
    "play_settings",
    metadata,
    Column("campaign_id", Text, ForeignKey("campaigns.id", ondelete="CASCADE"), primary_key=True),
    Column("raw", JSON, nullable=False),
    Column("updated_at", Text, nullable=False),
)

# The table's session state (DEL-199): gathering, playing or on a break, the absent PCs' choices and the raised hands.
table_sessions = Table(
    "table_sessions",
    metadata,
    Column("campaign_id", Text, ForeignKey("campaigns.id", ondelete="CASCADE"), primary_key=True),
    Column("state", Text, nullable=False),
    Column("since", Text, nullable=True),
    Column("absent", JSON, nullable=False),
    Column("hands", JSON, nullable=False),
    Column("break_at", Text, nullable=True),
    Column("updated_at", Text, nullable=False),
    # The seats away mid-session (DEL-224), by seat id: `{"at", "part"}`.
    Column("away", JSON, nullable=False, server_default="{}"),
)

# A campaign's own maps (campaign maps, 2026-10-23): dungeon maps made for one campaign, never the module's canon,
# played beside its revision's maps and gone with the campaign. `position` keeps the order they were first put.
campaign_maps = Table(
    "campaign_maps",
    metadata,
    Column("campaign_id", Text, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
    Column("name", Text, nullable=False),
    Column("position", Integer, nullable=False),
    Column("source", Text, nullable=False),
    Column("created_at", Text, nullable=False),
    Column("updated_at", Text, nullable=False),
    PrimaryKeyConstraint("campaign_id", "name"),
)


# Conversions (plan 5 Task 4): a job that makes a module from a PDF or a request. `warnings` is a JSON list of
# {code, message, ref}. At most one runs at a time.
conversions = Table(
    "conversions",
    metadata,
    Column("id", Text, primary_key=True),
    Column("kind", Text, nullable=False),
    Column("title", Text, nullable=False),
    Column("mode", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("step", Text, nullable=False),
    Column("done", Integer, nullable=False),
    Column("total", Integer, nullable=False),
    Column("module_id", Text, ForeignKey("modules.id", ondelete="SET NULL"), nullable=True),
    Column("warnings", JSON, nullable=False),
    Column("error", Text, nullable=True),
    Column("created_at", Text, nullable=False),
    Column("updated_at", Text, nullable=False),
    # What a job works on (`{"module_id", …}`), what it made when that is no module, and the questions it asked.
    Column("target", JSON, nullable=True),
    Column("result", JSON, nullable=True),
    Column("questions", JSON, nullable=True),
    # What its Claude calls cost so far, in USD; null while none reported one (and for a job from before 0015).
    Column("cost_usd", Float, nullable=True),
    # The PDF form's comments for Claude, and the keys of the questions and doubts an organiser closed
    # (`question:<id>`, `doubt:<index>`; table voice and fixes Task 0).
    Column("comments", Text, nullable=False, server_default=""),
    Column("closed", JSON, nullable=True),
    Index("uq_conversions_one_running", "status", unique=True, sqlite_where=text("status = 'running'")),
)


# Fix-it comments on a module (table voice and fixes Task 0): what an organiser asks to be fixed, optionally tied to a
# map, a room, a text or an entity (`anchor`), and the job that acts on it (`conversion_id`) from `revision`.
module_comments = Table(
    "module_comments",
    metadata,
    Column("id", Text, primary_key=True),
    Column("module_id", Text, ForeignKey("modules.id", ondelete="CASCADE"), nullable=False),
    Column("text", Text, nullable=False),
    Column("anchor", JSON, nullable=True),
    Column("status", Text, nullable=False, server_default="open"),
    Column("conversion_id", Text, ForeignKey("conversions.id", ondelete="SET NULL"), nullable=True),
    Column("revision", Integer, nullable=True),
    Column("error", Text, nullable=True),
    Column("author", Text, nullable=False, server_default=""),
    Column("created_at", Text, nullable=False),
    Column("updated_at", Text, nullable=False),
    Index("ix_module_comments_module_status", "module_id", "status"),
)


# The world (plan 6 Task 2). Every table belongs to a campaign and goes with it.


def _campaign() -> Column:
    return Column("campaign_id", Text, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False)


# A campaign's factions, by the id the module or the DM gave them. `source_ref` is the module entity it was seeded from.
factions = Table(
    "factions",
    metadata,
    _campaign(),
    Column("id", Text, nullable=False),
    Column("name", Text, nullable=False),
    Column("alignment", Text, nullable=False, server_default=""),
    Column("goals", Text, nullable=False, server_default=""),
    Column("scope", Text, nullable=False, server_default=""),
    Column("known", Boolean, nullable=False, server_default=text("0")),
    Column("strength", Integer, nullable=False, server_default="100"),
    Column("reputation", Integer, nullable=False, server_default="0"),
    Column("notes_md", Text, nullable=False, server_default=""),
    Column("source_ref", Text, nullable=True),
    PrimaryKeyConstraint("campaign_id", "id"),
)

# Countdown and progress clocks. `faction_id` names a faction of the same campaign, with no foreign key: a composite
# SET NULL would clear the campaign too, so deleting a faction clears it in the repository.
clocks = Table(
    "clocks",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    _campaign(),
    Column("label", Text, nullable=False),
    Column("faction_id", Text, nullable=True),
    Column("kind", Text, nullable=False),
    Column("days_remaining", Integer, nullable=True),
    Column("segments", Integer, nullable=True),
    Column("filled", Integer, nullable=True),
    Column("on_complete", Text, nullable=False, server_default=""),
    Column("started_day", Integer, nullable=False),
    Column("done_day", Integer, nullable=True),
    Index("ix_clocks_campaign", "campaign_id"),
)

# Quests. `related` is a JSON list of entity refs, `log` a JSON list of {day, text, known}.
quests = Table(
    "quests",
    metadata,
    _campaign(),
    Column("id", Text, nullable=False),
    Column("title", Text, nullable=False),
    Column("giver", Text, nullable=False, server_default=""),
    Column("scope", Text, nullable=False, server_default="local"),
    Column("stakes", Text, nullable=False, server_default=""),
    Column("status", Text, nullable=False),
    Column("known", Boolean, nullable=False, server_default=text("0")),
    Column("started_day", Integer, nullable=True),
    Column("ended_day", Integer, nullable=True),
    Column("related", JSON, nullable=False),
    Column("log", JSON, nullable=False),
    Column("notes_md", Text, nullable=False, server_default=""),
    Column("source_ref", Text, nullable=True),
    PrimaryKeyConstraint("campaign_id", "id"),
)

# The campaign's own lore facts, which the DM writes (the setting's are in the reference store).
campaign_facts = Table(
    "campaign_facts",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    _campaign(),
    Column("text", Text, nullable=False),
    Column("category", Text, nullable=False, server_default=""),
    Column("day", Integer, nullable=False),
    Index("ix_campaign_facts_campaign", "campaign_id"),
)

# Mounts, ships, houses. `owner_id` NULL is the party; a deleted owner leaves the possession to the party.
possessions = Table(
    "possessions",
    metadata,
    _campaign(),
    Column("id", Text, nullable=False),
    Column("name", Text, nullable=False),
    Column("kind", Text, nullable=False),
    Column("owner_id", Text, ForeignKey("characters.id", ondelete="SET NULL"), nullable=True),
    Column("location", Text, nullable=False, server_default=""),
    Column("value_gp", Integer, nullable=False, server_default="0"),
    Column("description", Text, nullable=False, server_default=""),
    Column("notes_md", Text, nullable=False, server_default=""),
    Column("inventory", JSON, nullable=False),
    Column("stats", JSON, nullable=False),
    Column("portrait", JSON, nullable=True),
    Column("created_at", Text, nullable=False),
    Column("updated_at", Text, nullable=False),
    PrimaryKeyConstraint("campaign_id", "id"),
)

# The campaign's world maps in the `.map` language; `source` is module, setting or campaign, `revealed` a JSON list of
# the hidden features players may now see.
world_maps = Table(
    "world_maps",
    metadata,
    _campaign(),
    Column("name", Text, nullable=False),
    Column("title", Text, nullable=False),
    Column("source", Text, nullable=False),
    Column("dsl", Text, nullable=False),
    Column("revealed", JSON, nullable=False),
    Column("updated_at", Text, nullable=False),
    # Plateau 7: the Delve GeoJSON document (None: a `.map` not yet converted), the base picture (a world_pictures
    # id), `ready` or `review`, what the party knows, and the reading of the picture.
    Column("geo", JSON, nullable=True),
    Column("picture", Text, nullable=True),
    Column("status", Text, nullable=False, server_default="ready"),
    Column("knowledge", JSON, nullable=True),
    Column("reading", JSON, nullable=True),
    PrimaryKeyConstraint("campaign_id", "name"),
)

# Magic merchants and their shelves, rolled once and kept until restocked. DM-only.
merchants = Table(
    "merchants",
    metadata,
    _campaign(),
    Column("id", Text, nullable=False),
    Column("name", Text, nullable=False),
    Column("npc_id", Text, ForeignKey("characters.id", ondelete="SET NULL"), nullable=True),
    Column("settlement", Text, nullable=False),
    Column("cost", Text, nullable=False),
    Column("seed", Integer, nullable=False),
    Column("rolled_day", Integer, nullable=False),
    Column("items", JSON, nullable=False),
    Column("sold", JSON, nullable=False),
    PrimaryKeyConstraint("campaign_id", "id"),
)

# Paid images: portraits, possessions' pictures and scenes. `blob` is the sha256 of the bytes in the blob store once
# done; `audience` is a story entry's (NULL: everyone). `attempts` counts the paintings asked for; `provider_job` is
# the provider's job, followed after a restart, and `queue` its place in the provider's queue (DEL-138).
campaign_images = Table(
    "campaign_images",
    metadata,
    Column("id", Text, primary_key=True),
    _campaign(),
    Column("kind", Text, nullable=False),
    Column("subject_id", Text, nullable=True),
    Column("status", Text, nullable=False),
    Column("blob", Text, nullable=True),
    Column("mime", Text, nullable=True),
    Column("prompt", Text, nullable=False, server_default=""),
    Column("caption", Text, nullable=False, server_default=""),
    Column("backend", Text, nullable=False, server_default=""),
    Column("audience", JSON, nullable=True),
    Column("error", Text, nullable=True),
    Column("attempts", Integer, nullable=False, server_default="0"),
    Column("provider_job", Text, nullable=True),
    Column("queue", Integer, nullable=True),
    Column("created_at", Text, nullable=False),
    Index("ix_campaign_images_campaign", "campaign_id"),
    Index("ix_campaign_images_status", "status"),
)


# Maps (plan 7 Task 1). A world map's base picture, cut into tiles: `id` is the original's sha256, `tiles` maps
# "z/x/y" to the tile's blob sha. Pictures are shared by every map that uses them.
# A kind of monster's picture, for every campaign (DEL-275), by the kind's slug.
monster_pictures = Table(
    "monster_pictures",
    metadata,
    Column("slug", Text, primary_key=True),
    Column("name", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("blob", Text),
    Column("mime", Text),
    Column("source", Text, nullable=False),
    Column("prompt", Text, nullable=False, server_default=""),
    Column("error", Text),
    Column("created_at", Text, nullable=False),
    Column("updated_at", Text, nullable=False),
)

world_pictures = Table(
    "world_pictures",
    metadata,
    Column("id", Text, primary_key=True),
    Column("mime", Text, nullable=False),
    Column("width_px", Integer, nullable=False),
    Column("height_px", Integer, nullable=False),
    Column("max_zoom", Integer, nullable=False),
    Column("tiles", JSON, nullable=False),
    Column("created_at", Text, nullable=False),
)

# The setting's content of this install (settings plan Task 2), over the shipped setting, which stays read-only.
# A setting's added and overridden pages, one per setting and `title_key` (the title, whitespace collapsed and
# casefolded); whether a page is an override is decided against the shipped setting, never stored.
setting_pages = Table(
    "setting_pages",
    metadata,
    Column("setting", Text, nullable=False),
    Column("title_key", Text, nullable=False),
    Column("title", Text, nullable=False),
    Column("kind", Text, nullable=False),
    Column("fields", JSON, nullable=False),
    Column("text", Text, nullable=False),
    Column("dm_only", Boolean, nullable=False),
    Column("created_at", Text, nullable=False),
    Column("updated_at", Text, nullable=False),
    PrimaryKeyConstraint("setting", "title_key"),
)

setting_facts = Table(
    "setting_facts",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("setting", Text, nullable=False),
    Column("text", Text, nullable=False),
    Column("category", Text, nullable=False),
    Column("dm_only", Boolean, nullable=False),
    Column("created_at", Text, nullable=False),
    Column("updated_at", Text, nullable=False),
)

# The DM's proposals to the setting; they go with their campaign.
proposals = Table(
    "proposals",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("setting", Text, nullable=False),
    _campaign(),
    Column("kind", Text, nullable=False),
    Column("title", Text, nullable=False),
    Column("text", Text, nullable=False),
    Column("mode", Text, nullable=False),
    Column("page_kind", Text, nullable=False),
    Column("category", Text, nullable=False),
    Column("dm_only", Boolean, nullable=False),
    Column("status", Text, nullable=False),
    Column("created_at", Text, nullable=False),
    Column("decided_at", Text, nullable=True),
    Index("ix_proposals_setting_status", "setting", "status"),
    Index("ix_proposals_campaign_id", "campaign_id"),
)

# A setting's own world maps: always a Delve GeoJSON document, over an optional base picture (a world_pictures id).
setting_maps = Table(
    "setting_maps",
    metadata,
    Column("setting", Text, nullable=False),
    Column("name", Text, nullable=False),
    Column("title", Text, nullable=False),
    Column("geo", JSON, nullable=False),
    Column("picture", Text, nullable=True),
    Column("status", Text, nullable=False),
    Column("reading", JSON, nullable=True),
    Column("created_at", Text, nullable=False),
    Column("updated_at", Text, nullable=False),
    PrimaryKeyConstraint("setting", "name"),
)

# Novels (novelization plan Task 1): a campaign or a module told as a story, exactly one of the two, and gone with it.
# `sessions` is the campaign's range `[first, last]` (null for all), `chapters` a JSON list of {title, summary, text}.
novels = Table(
    "novels",
    metadata,
    Column("id", Text, primary_key=True),
    Column("title", Text, nullable=False),
    Column("campaign_id", Text, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=True),
    Column("module_id", Text, ForeignKey("modules.id", ondelete="CASCADE"), nullable=True),
    Column("revision", Integer, nullable=True),
    Column("sessions", JSON, nullable=True),
    Column("length", Text, nullable=False),
    Column("tone", Text, nullable=False),
    Column("custom_tone", Text, nullable=False),
    Column("language", Text, nullable=False),
    Column("instructions", Text, nullable=False),
    Column("chapters", JSON, nullable=False),
    Column("status", Text, nullable=False),
    Column("error", Text, nullable=True),
    Column("conversion_id", Text, nullable=True),
    Column("cost_usd", Float, nullable=True),
    Column("created_at", Text, nullable=False),
    Column("updated_at", Text, nullable=False),
    CheckConstraint("(campaign_id IS NULL) != (module_id IS NULL)", name="ck_novels_one_source"),
    Index("ix_novels_campaign_id", "campaign_id"),
    Index("ix_novels_module_id", "module_id"),
)

# Histories (carry-the-party-on plan Task 1): one per campaign, the DM's and the table's texts, gone with it.
campaign_histories = Table(
    "campaign_histories",
    metadata,
    Column("campaign_id", Text, ForeignKey("campaigns.id", ondelete="CASCADE"), primary_key=True),
    Column("dm_md", Text, nullable=False),
    Column("table_md", Text, nullable=False),
    Column("status", Text, nullable=False),
    Column("error", Text, nullable=True),
    Column("edited", Boolean, nullable=False),
    Column("conversion_id", Text, nullable=True),
    Column("cost_usd", Float, nullable=True),
    Column("created_at", Text, nullable=False),
    Column("updated_at", Text, nullable=False),
)

# A party carried on: from a campaign (null once it is deleted) into a new one, once, with the old characters' ids.
campaign_carries = Table(
    "campaign_carries",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("from_campaign_id", Text, ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True),
    Column("to_campaign_id", Text, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, unique=True),
    Column("character_ids", JSON, nullable=False),
    Column("carried_at", Text, nullable=False),
    Index("ix_campaign_carries_from_campaign_id", "from_campaign_id"),
)

# What the backup store last got of each module, campaign and setting (cloud storage, DEL-110): its bundle's hash and
# size, so a run uploads only what changed. A failed upload records nothing, and is tried again next run.
backup_items = Table(
    "backup_items",
    metadata,
    Column("kind", Text, nullable=False),
    Column("item_id", Text, nullable=False),
    Column("hash", Text, nullable=False),
    Column("size", Integer, nullable=False),
    Column("backed_up_at", Text, nullable=False),
    PrimaryKeyConstraint("kind", "item_id"),
)
