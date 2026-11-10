from delve.config import Config


def test_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    c = Config.from_env({})
    assert c.port == 7810 and c.host == "0.0.0.0"
    assert c.data_dir == tmp_path / ".local/share/delve"
    assert c.db_path.name == "delve.db" and c.token_path.name == "token"


def test_env_and_overrides(tmp_path):
    c = Config.from_env({"DELVE_DATA_DIR": str(tmp_path)}, port=7811)
    assert c.data_dir == tmp_path and c.port == 7811
