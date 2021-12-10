from pathlib import Path

from lobbyboy.config import load_config


def test_load_config():
    config_file = Path(__file__).parent.parent / "lobbyboy" / "conf" / "lobbyboy_config.toml"
    load_config(config_file)
