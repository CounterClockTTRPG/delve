import socket
from pathlib import Path

import delve
from delve.__main__ import _setting_import_map, build_parser, build_registries, main, start_message, worldmap_query
from delve.config import Config
from delve.web import guard


def test_version(capsys):
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == f"delve {delve.__version__}"


def test_token_prints_links(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DELVE_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(guard, "lan_addresses", lambda: ["192.168.1.20", "2001:db8::5"])
    assert main(["token"]) == 0
    token = (tmp_path / "token").read_text().strip()
    assert capsys.readouterr().out.splitlines() == [
        f"http://192.168.1.20:7810/#token={token}",
        f"http://[2001:db8::5]:7810/#token={token}",
    ]
    assert main(["token", "--port", "7811"]) == 0
    assert capsys.readouterr().out.splitlines()[0] == f"http://192.168.1.20:7811/#token={token}"


def test_token_without_lan_says_so(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DELVE_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(guard, "lan_addresses", list)
    assert main(["token"]) == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "http://localhost:7810/" in captured.err


def test_start_message_names_the_login_and_the_invites(tmp_path):
    config = Config.from_env({"DELVE_DATA_DIR": str(tmp_path)}, port=7811)
    assert start_message(config) == (
        "Delve is running. Log in at http://localhost:7811/; players join through the invites on the play screen."
    )
    assert start_message(config, owner_account=False) == (
        "Delve is running. Log in at http://localhost:7811/; players join through the invites on the play screen.\n"
        "Make the owner account before you open a tunnel or a proxy to Delve: delve account add <username> --owner "
        "(or open the login page on this machine). Until there is one, a browser on this machine is the owner."
    )


def test_start_message_lists_old_database_copies(tmp_path):
    """Old copies of the database hold everything it did; Delve names them at start, for the owner to remove, and
    never removes them itself (DEL-154, audit finding 13)."""
    config = Config.from_env({"DELVE_DATA_DIR": str(tmp_path)}, port=7811)
    copies = [tmp_path / "delve.db.pre-0026", tmp_path / "delve.db.before-stonehell"]
    message = start_message(config, copies=copies)
    assert message.endswith(
        f"\n2 old copies of the database are in {tmp_path}: delve.db.pre-0026, delve.db.before-stonehell. Remove "
        "them once you no longer need them."
    )
    assert "old cop" not in start_message(config, copies=[])
    assert "1 old copy of the database is in" in start_message(config, copies=copies[:1])


def test_token_makes_a_private_data_dir(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DELVE_DATA_DIR", str(tmp_path / "new"))
    monkeypatch.setattr(guard, "lan_addresses", list)
    assert main(["token"]) == 0
    assert (tmp_path / "new").stat().st_mode & 0o777 == 0o700


def test_registries_hold_the_fakes_marked_development(tmp_path, monkeypatch, config_with_osric):
    monkeypatch.setenv("PATH", str(tmp_path))  # no `claude` here
    monkeypatch.setenv("DELVE_DATA_DIR", str(config_with_osric.data_dir))
    monkeypatch.delenv("REPLICATE_API_TOKEN", raising=False)  # nor a Replicate token
    registries = build_registries()
    assert [c.id for c in registries.dm.capabilities()] == ["fake"]
    assert [c.id for c in registries.images.capabilities()] == ["portraitgen", "none", "fake-images"]
    assert [c.id for c in registries.rulesets.capabilities()] == ["osric", "fake-rules"]
    assert [c.id for c in registries.settings_.capabilities()] == ["aun", "forgotten-realms", "greyhawk", "fake-setting"]
    assert registries.settings_.get("greyhawk").title == "Greyhawk"
    for registry in (registries.dm, registries.images, registries.rulesets, registries.settings_):
        caps = registry.capabilities()[-1]
        assert caps.title.endswith(" (development)")
        assert registry.get(caps.id) is not None


def test_setting_import_map_parses():
    args = build_parser().parse_args(
        ["setting", "import-map", "greyhawk", "greyhawk.jpg", "--name", "flanaess", "--distance", "30"]
    )
    assert (args.setting, args.picture, args.name, args.title) == ("greyhawk", Path("greyhawk.jpg"), "flanaess", "")
    assert (args.cell, args.distance, args.units, args.points, args.port) == ("hex", 30.0, "km", "", None)
    assert args.func is _setting_import_map
    assert main(["setting", "import-map", "greyhawk", "greyhawk.jpg", "--name", "flanaess"]) == 2, "--distance is needed"


def test_worldmap_query():
    assert worldmap_query("greyhawk", "flanaess", "The Flanaess", "hex", 30.0, "miles", "") == {
        "setting_id": "greyhawk",
        "name": "flanaess",
        "title": "The Flanaess",
        "cell": "hex",
        "distance": "30",
        "units": "miles",
    }
    assert worldmap_query("greyhawk", "x", "", "none", 12.5, "km", "1,2,3,4") == {
        "setting_id": "greyhawk",
        "name": "x",
        "title": "",
        "cell": "none",
        "distance": "12.5",
        "units": "km",
        "points": "1,2,3,4",
    }


def test_a_missing_picture_is_1(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DELVE_DATA_DIR", str(tmp_path))
    command = ["setting", "import-map", "greyhawk", "--name", "flanaess", "--distance", "30"]
    assert main([*command[:3], str(tmp_path / "nowhere.png"), *command[3:]]) == 1
    assert "nowhere.png" in capsys.readouterr().err
    gif = tmp_path / "map.gif"
    gif.write_bytes(b"GIF89a")
    assert main([*command[:3], str(gif), *command[3:]]) == 1
    assert "PNG, JPEG or WebP" in capsys.readouterr().err


def test_no_delve_running_is_5(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DELVE_DATA_DIR", str(tmp_path))
    picture = tmp_path / "map.png"
    picture.write_bytes(b"\x89PNG\r\n\x1a\n")
    with socket.socket() as sock:  # a port nothing listens on once it is closed
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    command = ["setting", "import-map", "greyhawk", str(picture), "--name", "flanaess", "--distance", "30"]
    assert main([*command, "--port", str(port)]) == 5
    assert capsys.readouterr().err.strip() == f"Delve isn't running on port {port}: start it with delve serve."


def _answers(monkeypatch, *answers):
    """`getpass` answers these, in order, and records its prompts."""
    prompts = []
    queue = list(answers)

    def fake_getpass(prompt=""):
        prompts.append(prompt)
        return queue.pop(0)

    monkeypatch.setattr("delve.__main__.getpass", fake_getpass)
    return prompts


def test_account_add(tmp_path, monkeypatch, capsys):
    from delve.play.accounts import authenticate
    from delve.storage import open_storage

    monkeypatch.setenv("DELVE_DATA_DIR", str(tmp_path))
    prompts = _answers(monkeypatch, "correct horse battery", "correct horse battery")
    assert main(["account", "add", " Ana ", "--display-name", "Ana the Bold"]) == 0
    assert prompts == ["Password: ", "Again: "]
    captured = capsys.readouterr()
    assert captured.out.strip() == "Account ana made." and "correct horse" not in captured.out + captured.err

    _answers(monkeypatch, "another password", "another password")
    assert main(["account", "add", "olga", "--owner"]) == 0
    _answers(monkeypatch, "a third password", "a third password")
    assert main(["account", "add", "bo.b", "--organiser"]) == 0
    storage = open_storage(Config(data_dir=tmp_path))
    try:
        ana = authenticate(storage, "ana", "correct horse battery")
        assert ana is not None and ana.profile.display_name == "Ana the Bold" and not ana.owner and not ana.organiser
        olga = authenticate(storage, "olga", "another password")
        assert olga is not None and olga.owner and not olga.organiser
        bo = authenticate(storage, "bo.b", "a third password")
        assert bo is not None and bo.organiser and not bo.owner
    finally:
        storage.close()


def test_account_add_passwords_differ(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DELVE_DATA_DIR", str(tmp_path))
    _answers(monkeypatch, "correct horse battery", "correct horse batterz")
    assert main(["account", "add", "ana"]) == 1
    captured = capsys.readouterr()
    assert "The passwords differ." in captured.err and "correct horse" not in captured.out + captured.err


def test_account_add_taken(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DELVE_DATA_DIR", str(tmp_path))
    _answers(monkeypatch, "correct horse battery", "correct horse battery")
    assert main(["account", "add", "ana"]) == 0
    capsys.readouterr()
    _answers(monkeypatch, "another password", "another password")
    assert main(["account", "add", "ANA"]) == 1
    assert "That username is taken." in capsys.readouterr().err
    _answers(monkeypatch, "short", "short")
    assert main(["account", "add", "bo.b"]) == 1
    assert "A password has at least 10 characters." in capsys.readouterr().err
    _answers(monkeypatch, "correct horse battery", "correct horse battery")
    assert main(["account", "add", "no"]) == 1
    assert "A username has 3 to 32 characters" in capsys.readouterr().err


# ----- socket activation (DEL-205) -----


def test_a_socket_systemd_passed_is_taken_by_this_process_or_its_uv_parent(monkeypatch):
    import os
    import socket

    from delve import __main__ as cli

    listening = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listening.bind(("127.0.0.1", 0))
    monkeypatch.setattr(cli, "LISTEN_FDS_START", listening.fileno())
    try:
        assert cli.passed_socket({}) is None
        assert cli.passed_socket({"LISTEN_FDS": "1", "LISTEN_PID": "1"}) is None, "another process's"
        assert cli.passed_socket({"LISTEN_FDS": "x", "LISTEN_PID": str(os.getpid())}) is None
        for pid in (os.getpid(), os.getppid()):
            environ = {"LISTEN_FDS": "1", "LISTEN_PID": str(pid), "LISTEN_FDNAMES": "delve.socket", "HOME": "/h"}
            passed = cli.passed_socket(environ)
            assert passed is not None and passed.getsockname() == listening.getsockname()
            assert environ == {"HOME": "/h"}, "the DM's processes don't see it"
            passed.detach()  # the same descriptor as `listening`
    finally:
        listening.close()


def test_pack_install_list_remove(tmp_path, monkeypatch, capsys):
    from delve.packs import loader

    monkeypatch.setenv("DELVE_DATA_DIR", str(tmp_path / "data"))
    loader.reset()
    source = Path(__file__).parent / "fixtures" / "packs" / "test-ruleset"
    assert main(["pack", "build", str(source), "-o", str(tmp_path / "out")]) == 0
    built = tmp_path / "out" / "test-ruleset-1.0.0.delvepack"
    assert capsys.readouterr().out.strip() == str(built)
    assert main(["pack", "install", str(built)]) == 0
    assert "Installed ruleset pack test-ruleset 1.0.0" in capsys.readouterr().out
    broken = tmp_path / "data" / "packs" / "broken"
    broken.mkdir()
    (broken / "pack.toml").write_text("id = 1")
    loader.reset()
    assert main(["pack", "list"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "test-ruleset  ruleset  1.0.0  Test ruleset"
    assert lines[1].startswith("broken  skipped: id missing")
    assert main(["pack", "rebuild"]) == 0
    assert capsys.readouterr().out.strip() == "Rebuilt test-ruleset"
    assert main(["pack", "remove", "test-ruleset"]) == 0
    assert main(["pack", "remove", "test-ruleset"]) == 1
    assert "no pack 'test-ruleset' is installed" in capsys.readouterr().err
    loader.reset()
