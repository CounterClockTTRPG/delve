"""The setting layer (settings plan Task 4): the install's pages, overrides and facts, and a campaign's proposals, over
the shipped setting, which stays read-only.

Every reader of a setting goes through it: the DM's lookups and search, Ask the DM, "Did you know", the Settings area
and the play screen's Setting tab. `dm=True` is the DM's and the organisers' view, everything; `dm=False` is a seat's,
which never holds a DM-only page, fact or proposal, and reads every text through `player_text`. With a `campaign_id`,
that campaign's visible proposals apply: the pending and rejected ones, and for a seat only those that aren't
DM-only. An accepted proposal is an ordinary addition by then."""

from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import replace

from delve.domain.reference import LoreFact, ReferenceHit, SettingPage
from delve.domain.setting_content import Proposal, SettingAddition, title_key
from delve.domain.world import Calendar, WorldMapSource
from delve.setting.setting import Setting
from delve.setting.text import dm_section, player_text, snippet, wiki_markdown
from delve.storage.interfaces import Storage

SEARCH_CAP = 50
FACT_TITLE_CHARS = 60
_WORD = re.compile(r"[\w'-]+")


def _summary(fields: dict[str, str]) -> str:
    """A page's fields but its name, as one line, as the shipped lookups give them."""
    return ", ".join(f"{key}: {value}" for key, value in fields.items() if key != "name" and value)


class SettingLayer:
    """A `Setting` made of `shipped` and what `storage` holds for it: see the module's docstring."""

    def __init__(self, shipped: Setting, storage: Storage, *, campaign_id: str | None = None, dm: bool = False) -> None:
        self.shipped = shipped
        self.storage = storage
        self.campaign_id = campaign_id
        self.dm = dm
        self.id = shipped.id
        self.title = shipped.title

    def kinds(self) -> tuple[str, ...]:
        return self.shipped.kinds()

    def calendar(self) -> Calendar:
        return self.shipped.calendar()

    # --- what this reader may see ----------------------------------------------------------------------------------

    def _sees(self, dm_only: bool) -> bool:
        return self.dm or not dm_only

    def _text(self, text: str) -> str:
        return text if self.dm else player_text(text)

    def _proposals(self, *kinds: str) -> list[Proposal]:
        """This campaign's visible proposals of `kinds`, in id order."""
        if self.campaign_id is None:
            return []
        found = self.storage.proposals.list(self.id, campaign_id=self.campaign_id)
        return sorted(
            (p for p in found if p.kind in kinds and p.status in ("pending", "rejected") and self._sees(p.dm_only)),
            key=lambda p: p.id,
        )

    def _dm_only_page(self, keys: set[str], added: SettingAddition | None) -> bool:
        """Whether the page of `keys` is a DM-only one: the install's, or a new page this campaign proposed."""
        if added is not None and added.dm_only:
            return True
        if self.campaign_id is None:
            return False
        return any(
            p.kind == "page" and p.dm_only and p.status in ("pending", "rejected") and title_key(p.title) in keys
            for p in self.storage.proposals.list(self.id, campaign_id=self.campaign_id)
        )

    def _additions(self, kind: str | None = None) -> list[SettingAddition]:
        """The install's pages this reader may see, by title."""
        return [a for a in self.storage.setting_pages.list(self.id, kind=kind) if self._sees(a.dm_only)]

    # --- pages -----------------------------------------------------------------------------------------------------

    def shipped_page(self, title: str) -> SettingPage | None:
        """The shipped setting's page (following its redirects), whatever the install holds."""
        return self.shipped.page(title)

    def addition(self, title: str) -> SettingAddition | None:
        """The install's page of `title`, which is stored under the shipped page's title when `title` is a redirect."""
        shipped = self.shipped.page(title)
        return self.storage.setting_pages.get(self.id, shipped.title if shipped else title)

    def page(self, title: str) -> SettingPage | None:
        """The page this reader reads as `title`: a new page this campaign proposed, else the install's addition (an
        override when the shipped setting has the page), else the shipped page; then this campaign's proposed edits
        of it, in order. A seat reads no DM-only page, and no DM-only section: when the page is DM-only, a seat reads
        the shipped page as shipped, else nothing, and no edit of it makes one."""
        shipped = self.shipped.page(title)
        canonical = shipped.title if shipped else title
        keys = {title_key(title), title_key(canonical)}
        mine = [p for p in self._proposals("page", "edit") if title_key(p.title) in keys]
        proposed = [p for p in mine if p.kind == "page"]
        added = self.storage.setting_pages.get(self.id, canonical)
        if not self.dm and self._dm_only_page(keys, added):
            return replace(shipped, text=player_text(shipped.text)) if shipped else None
        if proposed:
            p = proposed[-1]
            found: SettingPage | None = SettingPage(
                p.title, p.page_kind, {}, p.text, (), "proposal", p.dm_only, p.campaign_id, "markdown"
            )
        elif added is not None and self._sees(added.dm_only):
            found = SettingPage(
                added.title,
                added.kind or (shipped.kind if shipped else ""),
                dict(added.fields),
                added.text,
                shipped.categories if shipped else (),
                "override" if shipped else "addition",
                added.dm_only,
                None,
                "markdown",
            )
        else:
            found = shipped
        for edit in (p for p in mine if p.kind == "edit"):
            if found is None:
                found = SettingPage(canonical, edit.page_kind, {}, "", (), "proposal", False, None, "markdown")
            base = wiki_markdown(found.text) if found.format == "wiki" else found.text
            if edit.mode == "replace":
                text = edit.text
            else:
                addendum = dm_section(edit.text) if edit.dm_only else edit.text
                text = f"{base}\n\n{addendum}" if base else addendum
            found = replace(found, text=text, format="markdown", campaign_id=edit.campaign_id)
        if found is not None and not self.dm:
            found = replace(found, text=player_text(found.text))
        return found

    # --- search and lookup -----------------------------------------------------------------------------------------

    def search(self, query: str, limit: int = 10) -> list[ReferenceHit]:
        """Every word of `query` matched (ignoring case) in this campaign's new pages, then the install's pages, then
        the shipped setting's search, then the facts; a shipped page whose text an addition replaced is left out. A
        word only in a DM-only section matches nothing for a seat. At most `limit`, at most 50."""
        limit = max(0, min(limit, SEARCH_CAP))
        words = _WORD.findall(query)
        if not words or not limit:
            return []
        folded = [word.casefold() for word in words]

        def matches(*texts: str) -> bool:
            haystack = "\n".join(texts).casefold()
            return all(word in haystack for word in folded)

        hits: list[ReferenceHit] = []
        for p in self._proposals("page"):
            text = self._text(p.text)
            if matches(p.title, text):
                hits.append(ReferenceHit(p.page_kind, p.title, p.title, snippet(text, words), "proposal", p.dm_only))
        additions = self._additions()
        replaced = {title_key(a.title) for a in additions}
        for a in additions:
            text = self._text(a.text)
            if matches(a.title, text):
                origin = "override" if self.shipped.page(a.title) else "addition"
                hits.append(ReferenceHit(a.kind, a.title, a.title, snippet(text, words), origin, a.dm_only))
        try:
            shipped = self.shipped.search(" ".join(words), min(limit + len(replaced), SEARCH_CAP))
        except ValueError:
            shipped = []
        hits += [hit for hit in shipped if title_key(hit.title) not in replaced]
        for fact in self.facts():
            if matches(fact.text):
                hits.append(
                    ReferenceHit(
                        "fact",
                        f"fact:{fact.source}:{fact.id}",
                        fact.text[:FACT_TITLE_CHARS],
                        snippet(fact.text, words),
                        "fact",
                        fact.dm_only,
                    )
                )
        return hits[:limit]

    def lookup(self, kind: str, query: str, limit: int = 5) -> list[ReferenceHit]:
        """The install's pages of `kind` whose title holds `query` (ignoring case) with the shipped lookup's hits, an
        overridden title once, from the install (an override without a kind of its own keeps the shipped page's), and
        this campaign's new pages of `kind` before either, as `page()` reads them; by title, at most `limit`. An
        unknown kind raises `ValueError`."""
        needle = query.casefold()
        found = [a for a in self._additions() if needle in a.title.casefold() and a.kind in (kind, "")]
        shipped = self.shipped.lookup(kind, query, limit + len(found))
        by_key = {title_key(hit.title): hit for hit in shipped}
        additions = [a for a in found if a.kind == kind or title_key(a.title) in by_key]
        for a in additions:
            origin = "override" if title_key(a.title) in by_key or self.shipped.page(a.title) else "addition"
            text = _summary(a.fields) or snippet(self._text(a.text), ())
            by_key[title_key(a.title)] = ReferenceHit(kind, a.title, a.title, text, origin, a.dm_only)
        for p in self._proposals("page"):
            if needle in p.title.casefold() and p.page_kind in (kind, ""):
                text = snippet(self._text(p.text), ())
                by_key[title_key(p.title)] = ReferenceHit(kind, p.title, p.title, text, "proposal", p.dm_only)
        return sorted(by_key.values(), key=lambda hit: hit.title)[:limit]

    # --- facts -----------------------------------------------------------------------------------------------------

    def facts(self, query: str = "") -> list[LoreFact]:
        """The install's facts and this campaign's visible proposed facts that this reader may see, whose text holds
        `query` (ignoring case) as this reader reads it: a word only in a DM-only section matches nothing for a seat;
        oldest first."""
        needle = query.casefold()
        found = [
            (f.created_at, LoreFact(f.id, self._text(f.text), f.category, "install", f.dm_only))
            for f in self.storage.setting_facts.list(self.id, query=query if self.dm else "")
            if self._sees(f.dm_only)
        ]
        found += [
            (p.created_at, LoreFact(p.id, self._text(p.text), p.category, "campaign", p.dm_only))
            for p in self._proposals("fact")
        ]
        return [
            fact for _, fact in sorted(found, key=lambda pair: pair[0]) if fact.text and needle in fact.text.casefold()
        ]

    def lore_facts(self, n: int, category: str = "", seed: int | None = None) -> list[LoreFact]:
        """Up to `n` "Did you know" facts: this layer's `facts()` (of `category` when given) and the shipped
        setting's draw, in an order `seed` decides; without a seed, the shipped setting's own random draw and a fresh
        order."""
        own = [fact for fact in self.facts() if category in ("", fact.category)]
        pool = own + self.shipped.lore_facts(n, category, seed)
        salt = seed if seed is not None else secrets.token_hex(8)

        def order(fact: LoreFact) -> str:
            return hashlib.sha256(f"{salt}:{fact.source}:{fact.id}".encode()).hexdigest()

        return sorted(pool, key=order)[: max(0, n)]

    # --- maps ------------------------------------------------------------------------------------------------------

    def world_maps(self) -> tuple[WorldMapSource, ...]:
        """The install's ready maps of the setting, else the shipped setting's."""
        own = tuple(m for m in self.storage.setting_maps.list(self.id) if m.status == "ready")
        return own or self.shipped.world_maps()


def layer_for(
    storage: Storage, shipped: Setting | None, *, campaign_id: str | None = None, dm: bool = False
) -> SettingLayer | None:
    """The layer over `shipped`, None when there is no setting."""
    return None if shipped is None else SettingLayer(shipped, storage, campaign_id=campaign_id, dm=dm)
