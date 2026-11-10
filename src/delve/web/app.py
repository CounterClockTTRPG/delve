"""The one web app: API, event stream and SPA on one port. Every error it answers is JSON `{"error": …}`."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import secrets
import socket
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

from delve import __version__
from delve.cloud import backup
from delve.cloud import library as library_updates
from delve.cloud.connections import Stores
from delve.config import Config
from delve.conversions import close_folders, close_lost, close_orphans
from delve.dm.claude_cli import account
from delve.dm.provider import DMProvider
from delve.domain.backends import Registry
from delve.domain.campaigns import MissingPack
from delve.histories.jobs import close_orphan_histories
from delve.images.provider import ImageProvider
from delve.mail import sender as mail_sender
from delve.novels.jobs import close_orphan_novels
from delve.packs.catalogs import IN_TREE, Catalogs
from delve.play import beats, images, monster_pictures, translate
from delve.play import module_banners as module_banners_play
from delve.play.clock import Clock, SystemClock
from delve.play.passwords import BUSY, PasswordsBusy
from delve.rules.ruleset import Ruleset
from delve.setting.setting import Setting
from delve.storage import Storage
from delve.web import events
from delve.web.auth import (
    AccountIdentity,
    ChainedIdentity,
    OwnerTokenIdentity,
    SeatTokenIdentity,
    ThisMachineIdentity,
    load_or_create_secret,
    load_or_create_token,
)
from delve.web.devices import device_secret_path
from delve.web.guard import RequestGuard
from delve.web.routes import (
    accounts,
    assets,
    board,
    campaign_maps,
    campaigns,
    characters,
    connections,
    conversions,
    dsl,
    fixits,
    health,
    histories,
    house_rules,
    internal_tools,
    join,
    join_requests,
    legal,
    library,
    listing,
    lore,
    map_drafts,
    map_state,
    maps,
    module_banners,
    module_categories,
    module_source,
    module_world_maps,
    modules,
    novels,
    owner_token,
    packs,
    password_help,
    play,
    players,
    portraits,
    preferences,
    pregens,
    profiles,
    retry,
    rulesets,
    seats,
    setting_area,
    setting_world_maps,
    sign_up,
    table_settings,
    timeline,
    voice,
    world,
    world_import,
    world_pictures,
    worlds,
)
from delve.web.routes import mail as mail_routes
from delve.web.routes import monster_pictures as monster_picture_routes
from delve.web.routes import oidc as oidc_routes
from delve.web.routes import schedule as schedule_routes
from delve.web.routes import storage as storage_routes
from delve.web.seats import seat_lookup
from delve.web.spa import DEFAULT_STATIC_DIR, install_spa


@dataclass
class Registries:
    """The providers of each swappable layer. `settings_` holds the settings in the glossary's sense: the worlds
    campaigns play in, such as Aun; the trailing underscore keeps them apart from the app's Preferences."""

    dm: Registry[DMProvider]
    images: Registry[ImageProvider]
    rulesets: Registry[Ruleset]
    settings_: Registry[Setting]
    catalogs: Catalogs = IN_TREE
    """The rulesets and settings a campaign can name: the installed packs' beside the built-in ones."""


def create_app(
    config: Config,
    storage: Storage,
    registries: Registries,
    static_dir: Path | None = None,
    *,
    bridge_secret: str | None = None,
    clock: Clock | None = None,
) -> FastAPI:
    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # The event stream hands events on on this loop, whichever thread publishes them (DEL-166).
        app.state.events.bind(asyncio.get_running_loop())
        # A conversion still running was left by a Delve that stopped: it fails, with that reason; a thorough one is
        # paused instead, its folder kept.
        close_orphans(storage)
        # The Claude account's usage, as the CLI last reported it, for the host's play header.
        account.configure(config.data_dir)
        # A queued conversion whose book was lost as Delve stopped fails; the others stay in the queue.
        close_lost(storage)
        # A job folder no unfinished job owns (Delve stopped as a made job removed it, or as a job was cancelled) goes.
        close_folders(storage, config.data_dir)
        # So was a novel being written: it fails, keeping its chapters, and Continue writes the rest.
        close_orphan_novels(storage)
        # So was a carried party's history: it fails, keeping what it wrote, and Write again writes it anew.
        close_orphan_histories(storage)
        # So was an uploaded PDF, or a world map's picture, that no running job owns.
        conversions.remove_leftover_uploads(app)
        world_import.remove_leftover_pictures(app)
        # The thorough conversions paused by that stop go back in the queue, which starts unless it is paused; one
        # paused at the usage limit waits for its reset.
        await conversions.resume_paused(app)
        # So was a translation under way: it fails, and the English stays to read.
        storage.translations.fail_unfinished()
        # An open beat left by a Delve that stopped closes now, unless its timer still runs.
        beats.resume(play.table_of(app))
        # A painting a stopped Delve left behind is painted again, once; a module banner's is failed, to paint again.
        images.resume(play.table_of(app))
        monster_pictures.resume(storage)
        module_banners_play.interrupted(storage)
        # A banner waiting for a gate that opened while Delve was stopped is painted now.
        play.wake_banners(app)
        # The backup store and the library (cloud storage), from their files; the library's right is probed behind.
        await app.state.stores.start()
        # The daily backup (cloud storage), checked now, so one missed while Delve was down runs, and every minute.
        schedule = asyncio.create_task(backup.schedule_loop(app))
        # The library's newer versions of downloaded modules, checked now and at each day's backup time.
        updates = asyncio.create_task(library_updates.updates_loop(app))
        # The outbox's mail, handed to the provider as it comes due (DEL-314): routes only queue.
        mail = asyncio.create_task(mail_sender.sender_loop(app))
        yield
        schedule.cancel()
        updates.cancel()
        mail.cancel()
        await asyncio.gather(schedule, updates, mail, return_exceptions=True)
        await app.state.backups.stop()
        await asyncio.gather(*beats.stop_timers(play.table_of(app)), return_exceptions=True)
        await asyncio.gather(*translate.stop(play.table_of(app)), return_exceptions=True)
        await asyncio.gather(*images.stop(play.table_of(app)), return_exceptions=True)
        # A conversion this process runs stops with it; the next start closes it as failed, or pauses a thorough one.
        services = conversions.conversions(app)
        services.stopping = True  # the queue starts nothing more
        for scheduled in services.resumes.values():
            scheduled.cancel()
        tasks = [live.task for live in services.live.values() if live.task is not None]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        # Stop the DM processes (the resident `claude`s) with the app.
        for provider in registries.dm.built():
            close = getattr(provider, "close", None)
            if close is not None:
                await close()
        # And the image providers' HTTP clients.
        for provider in registries.images.built():
            aclose = getattr(provider, "aclose", None)
            if aclose is not None:
                await aclose()
        # And the stores' HTTP clients.
        await app.state.stores.aclose()

    app = FastAPI(
        title="Delve", version=__version__, docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan
    )
    app.state.config = config
    # Set by `run` when Delve can stop for systemd to start it again (DEL-366); None otherwise, as in the tests.
    app.state.restart = None
    # A pack installed or removed from the web since Delve started: it is used once Delve restarts.
    app.state.packs_changed = False
    app.state.storage = storage
    app.state.registries = registries
    # The table keeps time by `clock`: the beat timer and presence (a test moves it; `delve serve`, see `FileClock`),
    # and login sessions' last use.
    app.state.clock = clock or SystemClock()
    # Who is asking (`delve.web.auth`, `docs/identity.md`): the first of these that knows the caller.
    # The owner token follows its file, so `delve token --new` and Preferences' "Make a new owner token" end the old
    # one at once (DEL-154).
    app.state.owner_token = OwnerTokenIdentity(load_or_create_token(config), config.token_path)
    app.state.identity = ChainedIdentity(
        app.state.owner_token,
        AccountIdentity(storage, app.state.clock),
        SeatTokenIdentity(seat_lookup(storage)),
        ThisMachineIdentity(storage),
    )
    # Failed logins per username and address (players and tavern Task C4); in memory, so a restart forgets them.
    app.state.login_throttle = accounts.LoginThrottle()
    # Sign-ups asked per address (DEL-156); in memory too.
    app.state.sign_up_throttle = sign_up.SignUpThrottle()
    # What the device cookies are signed with (DEL-154, `delve.web.devices`): in the data dir, mode 0600.
    app.state.device_secret = load_or_create_secret(device_secret_path(config.data_dir), 32)
    app.state.events = events.EventBus(events.StoredTables(storage), app.state.clock)
    app.state.events.on_presence = lambda campaign_id: play.presence_changed(app, campaign_id)
    # The DM's tool bridge proves it was started by this process with this secret (spec §6.2); it is never stored.
    app.state.bridge_secret = bridge_secret or secrets.token_urlsafe(32)
    app.state.stores = Stores(config.data_dir)
    # One backup run at a time, the schedule's or Back up now's; its end tells the Storage section.
    app.state.backups = backup.Backups()
    app.state.backups.on_finish = lambda _: app.state.events.publish(
        "preferences", preferences.preferences_json(preferences.current_preferences(app))
    )

    app.add_middleware(RequestGuard)
    app.add_exception_handler(HTTPException, error_response)
    app.add_exception_handler(RequestValidationError, invalid_request)
    app.add_exception_handler(PasswordsBusy, passwords_busy)
    app.add_exception_handler(MissingPack, missing_pack_response)

    app.include_router(health.router)
    app.include_router(events.router)
    app.include_router(preferences.router)
    app.include_router(connections.router)
    app.include_router(mail_routes.router)
    app.include_router(modules.router)
    app.include_router(module_categories.router)
    app.include_router(module_banners.router)
    app.include_router(module_source.router)
    app.include_router(assets.router)
    app.include_router(maps.router)
    app.include_router(dsl.router)
    app.include_router(campaigns.router)
    app.include_router(characters.router)
    app.include_router(house_rules.router)
    app.include_router(map_state.router)
    app.include_router(play.router)
    app.include_router(pregens.router)
    app.include_router(portraits.router)
    app.include_router(internal_tools.router)
    app.include_router(worlds.router)
    app.include_router(world_import.router)
    app.include_router(conversions.router)
    app.include_router(novels.router)
    app.include_router(histories.router)
    app.include_router(map_drafts.router)
    app.include_router(join.router)
    app.include_router(join_requests.router)
    app.include_router(board.router)
    app.include_router(accounts.router)
    app.include_router(owner_token.router)
    app.include_router(players.router)
    app.include_router(sign_up.router)
    app.include_router(password_help.router)
    app.include_router(legal.router)
    app.include_router(oidc_routes.router)
    app.include_router(profiles.router)
    app.include_router(seats.router)
    app.include_router(lore.router)
    app.include_router(world.router)
    app.include_router(world_pictures.router)
    app.include_router(monster_picture_routes.router)
    app.include_router(module_world_maps.router)
    app.include_router(setting_area.router)
    app.include_router(setting_world_maps.router)
    app.include_router(campaign_maps.router)
    app.include_router(rulesets.router)
    # Voice at the table, the initiative timeline and module fix-ups (table voice and fixes Task 0).
    app.include_router(voice.router)
    app.include_router(timeline.router)
    app.include_router(retry.router)
    app.include_router(fixits.router)
    app.include_router(table_settings.router)
    app.include_router(listing.router)
    app.include_router(schedule_routes.router)
    # The backup store and the shared module library (cloud storage plan Task 4).
    app.include_router(storage_routes.router)
    # The shared module library, for organisers (cloud storage plan Task 9).
    app.include_router(library.router)
    app.include_router(packs.router)
    install_spa(app, static_dir or DEFAULT_STATIC_DIR, error_response)
    return app


def error_response(request: Request, exc: HTTPException) -> JSONResponse:
    body = exc.detail if isinstance(exc.detail, dict) else {"error": exc.detail}
    return JSONResponse(body, status_code=exc.status_code, headers=exc.headers)


def missing_pack_response(request: Request, exc: MissingPack) -> JSONResponse:
    """409 for a campaign whose ruleset or setting isn't installed: it can't be played until its pack is."""
    return JSONResponse({"error": exc.message}, status_code=409)


def passwords_busy(request: Request, exc: PasswordsBusy) -> JSONResponse:
    """503 for a password that couldn't be checked or hashed in time (Clara's final audit, finding 3)."""
    return JSONResponse({"error": BUSY}, status_code=503)


def invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
    """422 with where and why the request is refused, never the value sent, which may be a password (audit-auth
    finding 9)."""
    details = [{key: value for key, value in error.items() if key != "input"} for error in exc.errors()]
    return JSONResponse({"error": "invalid request", "details": jsonable_encoder(details)}, status_code=422)


# The paths that hold a one-time token: an account's set-password or reset link, and a table's join link.
TOKEN_PATH = re.compile(r"(/api/account-links/|/account/link/|/api/join/|/join/)[^/?\s]+")
# The query parameters whose value the access log drops: the PDF form's comments (table voice and fixes Task F1).
PRIVATE_QUERY = re.compile(r"([?&]comments=)[^&\s]*")


class AccessLogRedactor(logging.Filter):
    """Takes the tokens out of the access log's paths (players and tavern Task C4): no log line holds one; nor the
    PDF form's comments (`PRIVATE_QUERY`)."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(_redacted(a) if isinstance(a, str) else a for a in record.args)
        return True


def _redacted(text: str) -> str:
    return PRIVATE_QUERY.sub(r"\1…", TOKEN_PATH.sub(r"\1…", text))


def server_config(app: FastAPI) -> uvicorn.Config:
    """uvicorn's settings for the app.

    `proxy_headers=False`: uvicorn's default would let a loopback proxy's `X-Forwarded-For` and `X-Forwarded-Proto`
    replace the request's client and scheme before Delve sees them, so a tunnel's visitor would no longer look like
    a proxy here. Delve reads those headers itself, in `delve.web.guard` (`is_this_machine`, `client_address`,
    `came_over_https`), from the client as it connected.

    `ws_max_size=64 KiB` and no per-message deflate: the voice socket is the only WebSocket, and its messages are at
    most 1024 bytes (`voice.FRAME_BYTES`, `voice.TEXT_BYTES`). uvicorn's 16 MiB default would hold a whole oversized
    message in memory before the hub could drop it, and deflate would let a small compressed one inflate to the cap.
    A message over 64 KiB closes the socket (1009) as it comes in; one between 1 and 64 KiB is the hub's to drop."""
    return uvicorn.Config(app, workers=1, proxy_headers=False, ws_max_size=64 * 1024, ws_per_message_deflate=False)


SHUTDOWN_GRACE_S = 5
"""How long a stopping server waits for its requests to end before it cancels them; the event streams end at once."""


class DelveServer(uvicorn.Server):
    """uvicorn's server, which ends the app's event streams as soon as it starts shutting down (`EventBus.close`),
    so a restart isn't held up by the browsers listening; it waits at most `SHUTDOWN_GRACE_S` for the rest."""

    def __init__(self, config: uvicorn.Config, app: FastAPI) -> None:
        super().__init__(config)
        self._delve_app = app

    async def shutdown(self, sockets: list[socket.socket] | None = None) -> None:
        events = getattr(self._delve_app.state, "events", None)
        if events is not None:
            events.close()
        await super().shutdown(sockets=sockets)


RESTART_EXIT = 75
"""The exit code of a Delve that stopped to be restarted (DEL-366, after a pack changed): not 0, so systemd's
`Restart=on-failure` starts it again, while the socket it holds (`delve.socket`) keeps the requests waiting."""


def run(app: FastAPI, sock: socket.socket, *, restartable: bool = False) -> bool:
    """Serve the app with uvicorn (`server_config`), in this one process, on a socket that is already bound. With
    `restartable` (a socket systemd passed, which keeps the port while Delve restarts), `app.state.restart()` stops
    the server as Ctrl-C would, and this answers True: the caller exits with `RESTART_EXIT` for systemd to start
    Delve again. Without it, `app.state.restart` is None."""
    config = server_config(app)
    config.timeout_graceful_shutdown = SHUTDOWN_GRACE_S
    logging.getLogger("uvicorn.access").addFilter(AccessLogRedactor())
    server = DelveServer(config, app)
    asked: list[bool] = []

    def restart() -> None:
        asked.append(True)
        server.should_exit = True

    app.state.restart = restart if restartable else None
    server.run(sockets=[sock])
    return bool(asked)
