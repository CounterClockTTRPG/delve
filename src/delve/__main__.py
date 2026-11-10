"""The `delve` command: serve, migrate, token, house-rules, account, setting, pack, dm-bridge and qa."""

from __future__ import annotations

import argparse
import dataclasses
import os
import secrets
import shutil
import socket
import sys
from collections.abc import MutableMapping, Sequence
from getpass import getpass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from delve import __version__
from delve.config import Config

if TYPE_CHECKING:
    from delve.dm.claude_cli.effort import TurnContext
    from delve.storage import Storage
    from delve.web.app import Registries


def build_registries(
    config: Config | None = None,
    *,
    storage: Storage | None = None,
    bridge_secret: str = "",
) -> Registries:
    """The providers of each layer. The rulesets and the settings are the installed packs' (DEL-307), beside Delve's
    own setting, Aun. When `claude` is on `PATH`, the `claude -p` DM comes first,
    so it is the default; without it, it is unavailable. The rest are still the fakes, titled as being for development.

    With `storage`, the `claude -p` DM keeps its conversations in `storage.dm_sessions` and reads the campaign's
    live fight and NPCs from it; `bridge_secret` is the one the app's internal tool endpoint checks."""
    from delve.dm.claude_cli import CLAUDE_CLI_CAPABILITIES, ClaudeCliProvider, MemorySessions
    from delve.dm.claude_cli.argv import CLAUDE
    from delve.dm.fake import FAKE_DM_CAPABILITIES, FakeDM
    from delve.domain.backends import ProviderCapabilities, Registry
    from delve.images.fake import FAKE_IMAGES_CAPABILITIES, FakeImages
    from delve.images.none import NO_PORTRAIT_CAPABILITIES, NoPortraits
    from delve.images.portraitgen import PORTRAITGEN_CAPABILITIES, PortraitgenImages
    from delve.packs.catalogs import Catalogs
    from delve.rules.catalog import register_rulesets
    from delve.setting.catalog import register_settings
    from delve.web.app import Registries

    def development(caps: ProviderCapabilities) -> ProviderCapabilities:
        return dataclasses.replace(caps, title=f"{caps.title} (development)", development=True)

    config = config or Config.from_env()
    registries = Registries(
        dm=Registry(), images=Registry(), rulesets=Registry(), settings_=Registry()
    )
    if shutil.which(CLAUDE):
        registries.dm.register(
            CLAUDE_CLI_CAPABILITIES,
            lambda: ClaudeCliProvider(
                config.data_dir,
                storage.dm_sessions if storage is not None else MemorySessions(),
                bridge_url=f"http://127.0.0.1:{config.port}",
                bridge_secret=bridge_secret,
                turn_context=(lambda campaign_id: dm_turn_context(storage, campaign_id)) if storage else None,
            ),
        )
    registries.dm.register(development(FAKE_DM_CAPABILITIES), lambda: FakeDM([]))
    # Portraits default to portraitgen, free; the paid jobs to Replicate, offered only when its token exists.
    registries.images.register(PORTRAITGEN_CAPABILITIES, PortraitgenImages)
    registries.images.register(NO_PORTRAIT_CAPABILITIES, NoPortraits)  # NPCs only (DEL-248)
    register_replicate(registries, config)
    registries.images.register(development(FAKE_IMAGES_CAPABILITIES), FakeImages)
    register_assetgen(registries, config)
    registries.catalogs = Catalogs.installed(config)
    register_rulesets(registries.rulesets, registries.catalogs.rulesets)
    register_settings(registries.settings_, registries.catalogs.settings)
    return registries


def register_replicate(registries: Registries, config: Config) -> None:
    """Replicate, when its token is in `REPLICATE_API_TOKEN` or `<data dir>/replicate-token`, read through
    `delve.images.connections`, which Connections also registers it with at run time."""
    from delve.images.connections import register_replicate as register

    register(registries.images, config.data_dir)


def register_assetgen(registries: Registries, config: Config) -> None:
    """assetgen, when `<data dir>/assetgen.json` holds its URL, last of the images, so it is never a default; its
    models are read live. Connections registers it again at run time."""
    from delve.images.assetgen import register_assetgen as register

    register(registries, config)


def dm_turn_context(storage: Storage, campaign_id: str) -> TurnContext:
    """What the DM's auto effort and reset need at a beat: whether a fight is live, and the campaign's NPCs."""
    from delve.dm.claude_cli.effort import TurnContext

    npcs = tuple(c.name for c in storage.characters.list(campaign_id) if c.kind == "npc")
    return TurnContext(in_combat=storage.combats.live(campaign_id) is not None, npc_names=npcs)


def token_links(config: Config, token: str) -> list[str]:
    """The links that open Delve with its token from another device on the LAN."""
    from delve.web.auth import token_links as links

    return links(config.port, token)


def _token(args: argparse.Namespace) -> int:
    from delve.web.auth import load_or_create_token, new_token

    config = Config.from_env(port=args.port)
    links = token_links(config, new_token(config) if args.new else load_or_create_token(config))
    for link in links:
        print(link)
    if not links:
        print(f"No LAN address found. On this machine, open http://localhost:{config.port}/", file=sys.stderr)
    if args.new:
        # A running Delve reads the file again on its next request (DEL-154).
        print("The old token no longer works, nor the links that carried it.", file=sys.stderr)
    return 0


WILDCARD_HOSTS = frozenset({"0.0.0.0", "::"})


def _serve(args: argparse.Namespace) -> int:
    from delve.play.accounts import has_owner_account
    from delve.play.clock import CLOCK_FILE_ENV, FileClock
    from delve.storage import SchemaTooNewError, database_copies, open_storage
    from delve.web import guard
    from delve.web.app import RESTART_EXIT, create_app, run
    from delve.web.auth import load_or_create_token

    config = Config.from_env(host=args.host, port=args.port)
    try:
        storage = open_storage(config)
    except SchemaTooNewError as error:
        print(error, file=sys.stderr)
        return 3
    try:
        load_or_create_token(config)  # the owner token's file: for the CLI, tests and recovery (`delve token`)
        secret = secrets.token_urlsafe(32)
        registries = build_registries(config, storage=storage, bridge_secret=secret)
        # Tests move the table's time through a file (`FileClock`); otherwise it is the system's.
        clock_file = os.environ.get(CLOCK_FILE_ENV)
        clock = FileClock(Path(clock_file)) if clock_file else None
        app = create_app(config, storage, registries, bridge_secret=secret, clock=clock)
        # A socket systemd passes (`delve.socket`) keeps the port while Delve restarts: only then can the owner's
        # "Restart Delve now" (DEL-366) stop Delve for systemd to start it again.
        restartable = "LISTEN_FDS" in os.environ
        try:
            sock = bind(config)
        except OSError:
            print(f"Port {config.port} is in use; start with --port <other>", file=sys.stderr)
            return 2

        print(start_message(config, owner_account=has_owner_account(storage), copies=database_copies(config)))
        if config.host in WILDCARD_HOSTS:
            links = [f"{origin}/" for origin in guard.lan_origins(config.port)]
            if links:
                print("From another device on the network, log in at:")
            for link in links:
                print(f"  {link}")
        sys.stdout.flush()
        with sock:
            restarting = run(app, sock, restartable=restartable)
    finally:
        storage.close()
    return RESTART_EXIT if restarting else 0


def start_message(config: Config, *, owner_account: bool = True, copies: Sequence[Path] = ()) -> str:
    """What `delve serve` says once it listens: where to log in, and the invites; with no owner account yet, how to
    make one (the human's ruling of 2026-10-24: the login page replaces the owner token's link); and the old copies of
    the database in the data directory (`database_copies`), which hold all it did, for the owner to remove (DEL-154,
    audit finding 13)."""
    message = (
        f"Delve is running. Log in at http://localhost:{config.port}/; players join through the invites on the play "
        "screen."
    )
    if not owner_account:
        message += (
            "\nMake the owner account before you open a tunnel or a proxy to Delve: delve account add <username> "
            "--owner (or open the login page on this machine). Until there is one, a browser on this machine is the "
            "owner."
        )
    if copies:
        some = f"{len(copies)} old copies of the database are" if len(copies) > 1 else "1 old copy of the database is"
        names = ", ".join(path.name for path in copies)
        them = "them" if len(copies) > 1 else "it"
        message += f"\n{some} in {config.data_dir}: {names}. Remove {them} once you no longer need {them}."
    return message


LISTEN_FDS_START = 3
"""The first socket systemd passes (`sd_listen_fds`)."""


def passed_socket(environ: MutableMapping[str, str] | None = None) -> socket.socket | None:
    """The listening socket systemd passed (socket activation, `delve.socket`), else None. It is ours when
    `LISTEN_PID` is this process or its parent: `uv run` starts `delve` as its child. systemd keeps the socket open
    while Delve restarts, so a request that comes meanwhile waits for the new server instead of being refused."""
    environ = os.environ if environ is None else environ
    try:
        count, pid = int(environ.get("LISTEN_FDS", "0")), int(environ.get("LISTEN_PID", "0"))
    except ValueError:
        return None
    if count < 1 or pid not in (os.getpid(), os.getppid()):
        return None
    for name in ("LISTEN_FDS", "LISTEN_PID", "LISTEN_FDNAMES"):  # not the DM's processes', which Delve starts
        environ.pop(name, None)
    return socket.socket(fileno=LISTEN_FDS_START)


def bind(config: Config) -> socket.socket:
    """Bind the listening socket before uvicorn starts, so a port in use is a message and not a traceback; the one
    systemd passed, when it passed one (`passed_socket`)."""
    passed = passed_socket()
    if passed is not None:
        return passed
    family = socket.AF_INET6 if ":" in config.host else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((config.host, config.port))
    except OSError:
        sock.close()
        raise
    return sock


def _migrate(args: argparse.Namespace) -> int:
    from delve.storage import SchemaTooNewError, migrate

    try:
        print(migrate(Config.from_env()))
    except SchemaTooNewError as error:
        print(error, file=sys.stderr)
        return 3
    return 0



def _monster_pictures_seed(args: argparse.Namespace) -> int:
    from delve.play import monster_pictures
    from delve.storage import open_storage

    folder = Path(args.assets).expanduser()
    if not (folder / "assets.json").is_file():
        print(
            f"{folder} has no assets.json: give the goldbox assets folder that holds it and tokens/.", file=sys.stderr
        )
        return 1
    loaded = monster_pictures.seed(open_storage(Config.from_env()), folder)
    print(f"Loaded {len(loaded)} monster pictures.")
    return 0



def _house_rules_import(args: argparse.Namespace) -> int:
    from delve.packs.catalogs import Catalogs
    from delve.play.house_rules import SEED_DIR, import_house_rules
    from delve.storage import SchemaTooNewError, open_storage

    root = args.dir or SEED_DIR
    if not root.is_dir():
        print(f"No house-rules directory at {root}", file=sys.stderr)
        return 1
    try:
        storage = open_storage(Config.from_env())
    except SchemaTooNewError as error:
        print(error, file=sys.stderr)
        return 3
    try:
        bundle = import_house_rules(storage, root, Catalogs.installed(Config.from_env()).packs)
    finally:
        storage.close()
    print(f'{len(bundle.rule_ids)} house rules in the bundle "{bundle.title}" ({bundle.id}), from {root}')
    return 0


def _blobs_prune(args: argparse.Namespace) -> int:
    """`delve blobs prune` (DEL-36): what in the blob store nothing names any more, and with `--delete` deletes it."""
    from datetime import timedelta

    from delve.images.thumbs import forget
    from delve.storage import SchemaTooNewError, open_storage

    if args.grace_hours < 0:
        print("--grace-hours can't be negative", file=sys.stderr)
        return 2
    config = Config.from_env()
    grace = timedelta(hours=args.grace_hours)
    try:
        storage = open_storage(config)
    except SchemaTooNewError as error:
        print(error, file=sys.stderr)
        return 3
    try:
        found = storage.blobs.prune(grace) if args.delete else storage.blobs.unused(grace)
    finally:
        storage.close()
    if args.delete:
        forget(config.data_dir, [blob.sha for blob in found.blobs])
    for blob in found.blobs:
        made = blob.created_at[:10] if blob.created_at else "no row"
        print(f"{blob.sha}  {blob.size:>12,}  {made:<10}  {blob.mime or '-'}")
    size = f"{found.size / 1e6:,.1f} MB"
    if args.delete:
        print(f"Deleted {len(found.blobs)} files nothing used, {size}.")
    else:
        print(f"{len(found.blobs)} files nothing uses, {size}: run again with --delete to delete them.")
    if found.kept:
        print(f"{found.kept} more that nothing uses yet are newer than {args.grace_hours:g} hours or a running job, and stay.")
    return 0


def _account_add(args: argparse.Namespace) -> int:
    """`delve account add` (players and tavern Task B2): an account with the password typed twice, never echoed."""
    from delve.play.accounts import check_new_password, create_account, username_of
    from delve.play.context import PlayError
    from delve.storage import SchemaTooNewError, open_storage

    try:
        username = username_of(args.username)
        password = getpass("Password: ")
        if getpass("Again: ") != password:
            print("The passwords differ.", file=sys.stderr)
            return 1
        check_new_password(password)
    except PlayError as error:
        print(error.message, file=sys.stderr)
        return 1
    try:
        storage = open_storage(Config.from_env())
    except SchemaTooNewError as error:
        print(error, file=sys.stderr)
        return 3
    try:
        account = create_account(
            storage, username, password, display_name=args.display_name, organiser=args.organiser, owner=args.owner
        )
    except PlayError as error:
        print(error.message, file=sys.stderr)
        return 1
    finally:
        storage.close()
    print(f"Account {account.username} made.")
    return 0


PICTURE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
"""A world map's picture to read, by its suffix: the types `POST /api/conversions/worldmap` takes."""
CHUNK = 1 << 20


def worldmap_query(
    setting: str, name: str, title: str, cell: str, distance: float, units: str, points: str
) -> dict[str, str]:
    """The query `POST /api/conversions/worldmap` takes to read a picture into `setting`'s map `name`."""
    query = {
        "setting_id": setting,
        "name": name,
        "title": title,
        "cell": cell,
        "distance": f"{distance:g}",
        "units": units,
    }
    if points:
        query["points"] = points
    return query


def _chunks(path: Path):
    with path.open("rb") as file:
        while chunk := file.read(CHUNK):
            yield chunk


def _setting_import_map(args: argparse.Namespace) -> int:
    """Stream the picture to the running Delve, which reads it into the setting's map in the background, in review.

    A thin client (settings plan decision 15): the server runs the job, one conversion at a time, and publishes it."""
    import httpx

    config = Config.from_env(port=args.port)
    picture: Path = args.picture
    media_type = PICTURE_TYPES.get(picture.suffix.lower())
    if not picture.is_file():
        print(f"There is no picture at {picture}", file=sys.stderr)
        return 1
    if media_type is None:
        print(f"Give the picture as PNG, JPEG or WebP (.png, .jpg, .jpeg, .webp), not {picture.name}", file=sys.stderr)
        return 1
    headers = {"Content-Type": media_type, "Content-Length": str(picture.stat().st_size)}
    if config.token_path.is_file():  # read, never created: the running Delve made it
        headers["Authorization"] = f"Bearer {config.token_path.read_text().strip()}"
    query = worldmap_query(args.setting, args.name, args.title, args.cell, args.distance, args.units, args.points)
    try:
        response = httpx.post(
            f"http://127.0.0.1:{config.port}/api/conversions/worldmap",
            params=query,
            content=_chunks(picture),
            headers=headers,
            timeout=httpx.Timeout(300, connect=5),
        )
    except httpx.ConnectError:
        print(f"Delve isn't running on port {config.port}: start it with delve serve.", file=sys.stderr)
        return 5
    except httpx.HTTPError as error:
        print(f"Delve didn't answer: {error}", file=sys.stderr)
        return 1
    body: Any = _json_or_none(response)
    if response.status_code != 202 or not isinstance(body, dict):
        error = body.get("error") if isinstance(body, dict) else None
        print(error or f"Delve refused the picture ({response.status_code}).", file=sys.stderr)
        return 1
    print(
        f"Reading {args.name} for {args.setting} in the background (conversion {body['id']}). Review it at "
        f"http://localhost:{config.port}/world-maps/setting/{args.setting}/{args.name}/review"
    )
    return 0


def _json_or_none(response: Any) -> Any:
    try:
        return response.json()
    except ValueError:
        return None


def _pack(args: argparse.Namespace) -> int:
    from delve.packs.loader import load_packs
    from delve.packs.transit import PackError, build_pack, install_pack, pack_folders, rebuild_pack, remove_pack

    packs_dir = Config.from_env().packs_dir
    try:
        if args.action == "build":
            print(build_pack(args.folder, args.out))
        elif args.action == "install":
            manifest = install_pack(args.source, packs_dir)
            print(f"Installed {manifest.kind} pack {manifest.id} {manifest.version}: {manifest.title}")
        elif args.action == "remove":
            remove_pack(args.id, packs_dir)
            print(f"Removed {args.id}")
        elif args.action == "rebuild":
            for pack_id in [args.id] if args.id else list(pack_folders(packs_dir)):
                rebuild_pack(pack_id, packs_dir)
                print(f"Rebuilt {pack_id}")
        else:
            loaded, skipped = load_packs(packs_dir)
            for pack in loaded:
                m = pack.manifest
                print(f"{m.id}  {m.kind}  {m.version}  {m.title}")
            for left_out in skipped:
                print(f"{left_out.folder.name}  skipped: {left_out.reason}")
    except PackError as error:
        print(error, file=sys.stderr)
        return 1
    return 0


def _dm_bridge(args: argparse.Namespace) -> int:
    from delve.dm.bridge import SECRET_ENV
    from delve.dm.bridge import main as bridge

    secret = os.environ.get(SECRET_ENV, "")
    if not secret:
        print(f"delve dm-bridge needs the secret of the running Delve in {SECRET_ENV}", file=sys.stderr)
        return 2
    return bridge(args.url, args.campaign, secret)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="delve", description="Delve: play, maps and modules, with Claude as the DM.")
    parser.add_argument("--version", action="version", version=f"delve {__version__}")
    commands = parser.add_subparsers(dest="command", metavar="command")

    serve = commands.add_parser("serve", help="run Delve: the API, the event stream and the app on one port")
    serve.add_argument("--host", help="address to listen on (default 0.0.0.0)")
    serve.add_argument("--port", type=int, help="port to listen on (default 7810)")
    serve.set_defaults(func=_serve)

    migrate = commands.add_parser("migrate", help="bring the database up to the current schema")
    migrate.set_defaults(func=_migrate)

    token = commands.add_parser("token", help="print the links that open Delve with its token")
    token.add_argument("--port", type=int, help="the port Delve listens on (default 7810)")
    token.add_argument("--new", action="store_true", help="make a new owner token; the old one stops working at once")
    token.set_defaults(func=_token)

    monsters = commands.add_parser("monster-pictures", help="the pictures of the kinds of monsters (DEL-275)")
    monsters.set_defaults(func=lambda _: monsters.print_help() or 2)
    monster_actions = monsters.add_subparsers(dest="action", metavar="action")
    seeder = monster_actions.add_parser(
        "seed", help="load the owner's own monster paintings from a goldbox assets folder; kinds with one keep theirs"
    )
    seeder.add_argument("assets", help="the folder holding assets.json and tokens/")
    seeder.set_defaults(func=_monster_pictures_seed)

    house_rules = commands.add_parser("house-rules", help="the library of house rules")
    house_rules.set_defaults(func=lambda _: house_rules.print_help() or 2)
    house_rules_actions = house_rules.add_subparsers(dest="action", metavar="action")
    importer = house_rules_actions.add_parser(
        "import", help="import ttrpg2's house rules (again: rules already there are kept as they are)"
    )
    importer.add_argument("dir", nargs="?", type=Path, help="a house-rules directory (default: the one Delve ships)")
    importer.set_defaults(func=_house_rules_import)

    blobs = commands.add_parser("blobs", help="the files modules, pictures and maps keep, in the blob store")
    blobs.set_defaults(func=lambda _: blobs.print_help() or 2)
    blobs_actions = blobs.add_subparsers(dest="action", metavar="action")
    prune = blobs_actions.add_parser(
        "prune", help="list the files nothing uses any more, and with --delete delete them"
    )
    prune.add_argument("--delete", action="store_true", help="delete them; without it, only list them")
    prune.add_argument(
        "--grace-hours",
        type=float,
        default=24,
        help="keep files put this recently, which what put them may still name (default 24)",
    )
    prune.set_defaults(func=_blobs_prune)

    account = commands.add_parser("account", help="the accounts people log in with")
    account.set_defaults(func=lambda _: account.print_help() or 2)
    account_actions = account.add_subparsers(dest="action", metavar="action")
    account_add = account_actions.add_parser("add", help="make an account; asks for its password")
    account_add.add_argument("username", help="3 to 32 of a to z, 0 to 9, '.', '_' and '-' (any case: it is folded)")
    account_add.add_argument("--display-name", help="the name others see (default: the username)")
    account_add.add_argument("--organiser", action="store_true", help="with the organiser's rights")
    account_add.add_argument("--owner", action="store_true", help="with every right of the install's owner")
    account_add.set_defaults(func=_account_add)

    setting = commands.add_parser("setting", help="the settings campaigns play in")
    setting.set_defaults(func=lambda _: setting.print_help() or 2)
    setting_actions = setting.add_subparsers(dest="action", metavar="action")
    import_map = setting_actions.add_parser(
        "import-map", help="read a world map's picture into a setting's map, left in review (Delve must be running)"
    )
    import_map.add_argument("setting", help="the setting's id, for example aun")
    import_map.add_argument("picture", type=Path, help="the picture: PNG, JPEG or WebP")
    import_map.add_argument("--name", required=True, help="the map's name in the setting")
    import_map.add_argument("--title", default="", help="the map's title (default: its name)")
    import_map.add_argument("--cell", choices=("hex", "square", "none"), default="hex", help="the grid (default hex)")
    import_map.add_argument(
        "--distance", type=float, required=True, help="one cell's distance, or with --cell none the points' distance"
    )
    import_map.add_argument("--units", choices=("km", "miles"), default="km", help="the distance's units (default km)")
    import_map.add_argument("--points", default="", help="with --cell none, two points on the picture: x1,y1,x2,y2")
    import_map.add_argument("--port", type=int, help="the port Delve listens on (default 7810)")
    import_map.set_defaults(func=_setting_import_map)

    pack = commands.add_parser("pack", help="the rulesets and settings installed as packs (DEL-307)")
    pack.set_defaults(func=lambda _: pack.print_help() or 2)
    pack_actions = pack.add_subparsers(dest="action", metavar="action")
    pack_build = pack_actions.add_parser("build", help="make a .delvepack file from a pack folder")
    pack_build.add_argument("folder", type=Path, help="the pack's folder")
    pack_build.add_argument("-o", "--out", type=Path, default=Path("."), help="the folder to write into (default .)")
    pack_build.set_defaults(func=_pack)
    pack_install = pack_actions.add_parser("install", help="install or update a pack; restart Delve to use it")
    pack_install.add_argument(
        "source", help="a .delvepack file, a pack folder, or a git URL (add #folder for a subfolder)"
    )
    pack_install.set_defaults(func=_pack)
    pack_actions.add_parser("list", help="the installed packs, and the ones left out with why").set_defaults(func=_pack)
    pack_remove = pack_actions.add_parser("remove", help="delete an installed pack")
    pack_remove.add_argument("id", help="the pack's id")
    pack_remove.set_defaults(func=_pack)
    pack_rebuild = pack_actions.add_parser("rebuild", help="run the packs' build again, in place")
    pack_rebuild.add_argument("id", nargs="?", help="the pack's id (default every pack)")
    pack_rebuild.set_defaults(func=_pack)

    dm_bridge = commands.add_parser(
        "dm-bridge", help="serve the DM's tools over stdio MCP, for claude -p (started by Delve, not by hand)"
    )
    dm_bridge.add_argument("--url", required=True, help="the running Delve, for example http://127.0.0.1:7810")
    dm_bridge.add_argument("--campaign", required=True, help="the campaign id the DM plays")
    dm_bridge.set_defaults(func=_dm_bridge)

    # Listed here for the help only: `main` hands `delve qa …` to `delve.conversions.qa`, which parses its own arguments.
    commands.add_parser("qa", help="the thorough conversion's tools, run by its agents in a job folder", add_help=False)
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["qa"]:
        from delve.conversions.qa import main as qa

        return qa(argv[1:])
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exit_:
        return int(exit_.code or 0)
    if args.command is None:
        parser.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
