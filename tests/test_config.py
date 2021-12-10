from pathlib import Path

from lobbyboy.config import load_config
from lobbyboy.main import load_providers

PARENT_DIR = Path(__file__).parent
CONFIG_FILE = PARENT_DIR.parent / "lobbyboy" / "conf" / "lobbyboy_config.toml"


def test_load_config():
    load_config(CONFIG_FILE)


def test_load_providers_from_config():
    config = load_config(CONFIG_FILE)
    providers = load_providers(config.provider, PARENT_DIR.parent / "dev_datadir")
    assert len(providers) > 0
