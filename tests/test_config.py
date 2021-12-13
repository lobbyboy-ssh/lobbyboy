from pathlib import Path

from lobbyboy.config import LBConfig

PARENT_DIR = Path(__file__).parent
CONFIG_FILE = PARENT_DIR.parent / "lobbyboy" / "conf" / "lobbyboy_config.toml"


def test_load_config():
    LBConfig.load(CONFIG_FILE)


def test_load_providers_from_config():
    config = LBConfig.load(CONFIG_FILE)
    assert len(config.provider_cls) > 0
