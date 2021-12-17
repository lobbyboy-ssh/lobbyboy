import json
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass, field, fields, asdict
from json import JSONDecodeError
from pathlib import Path
from typing import Dict, List, Tuple, OrderedDict as typeOrderedDict, Optional, Type, Any

import toml

from lobbyboy.exceptions import InvalidConfigException
from lobbyboy.utils import lb_dict_factory, confirm_dc_type, get_cls

logger = logging.getLogger(__name__)


@dataclass
class LBConfigUser:
    authorized_keys: str = None
    password: Optional[str] = None

    def auth_key_pairs(self) -> List[Tuple]:
        """

        Returns:
            tuple: (key_type, key_data)
        """
        if not self.authorized_keys:
            return []
        return [tuple(ssh_key.split(maxsplit=1)) for ssh_key in self.authorized_keys.split("\n") if ssh_key]


@dataclass
class LBConfigProvider:
    """
    The basic configuration set of provider.

    If a `provider` needs to configure custom fields, it should inherit this.
    """

    load_module: str = None
    enable: bool = True
    min_life_to_live: str = None
    bill_time_unit: str = None
    destroy_safe_time: str = None
    server_name_prefix: str = None
    api_token: str = None
    extra_ssh_keys: List[str] = field(default_factory=list)


@dataclass
class LBServerMeta:
    provider_name: str
    workspace: Path
    server_name: str
    server_host: str = "127.0.0.1"
    server_user: str = "root"
    server_port: int = 22
    created_timestamp: int = field(default_factory=lambda: int(time.time()))
    # TODO support below features when create server
    # extra ssh args when connect to this server by ssh, eg: ["-o", "ProxyCommand=$jumpServer"]
    ssh_extra_args: List[str] = field(default_factory=list)
    # indicate whether this server is managed by us or not.
    manage: bool = True

    def __post_init__(self):
        self.confirm_data_type()

    def confirm_data_type(self):
        if self.workspace:
            self.workspace = Path(self.workspace)

    @property
    def live_sec(self) -> int:
        return int(time.time()) - self.created_timestamp


@dataclass
class LBConfig:
    _file: Path
    _raw: Dict = field(default_factory=dict)
    data_dir: Path = None
    listen_port: int = None
    listen_ip: str = None
    min_destroy_interval: str = None
    servers_file: str = None
    log_level: str = None
    user: Dict[str, Type[LBConfigUser]] = field(default_factory=dict)
    provider: Dict[str, LBConfigProvider] = field(default_factory=dict)
    # Hold all providers class.
    _provider_cls: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, config_file: Path) -> "LBConfig":
        """Load config from file."""
        logger.debug(f"Loading LB configs from {str(config_file)}.")

        raw_config: Dict = toml.load(config_file)  # noqa

        # update it from config file
        config_file_file = {
            f.name: raw_config[f.name] for f in fields(cls) if f.name in raw_config and not f.name.startswith("_")
        }
        config = cls(**config_file_file, _file=config_file, _raw=raw_config)

        config.confirm_data_type()

        # validation
        is_valid, reason = config.validate()
        if not is_valid:
            raise InvalidConfigException(reason)
        return config

    def reload(self) -> "LBConfig":
        return self.load(self._file)

    def validate(self) -> Tuple[bool, Optional[str]]:
        """

        Returns:
            tuple(bool, str): (config_is_valid, reason)
        """
        if self.data_dir is None:
            return False, "missing required config: please check 'data_dir' in your config file."
        # TODO, config validator
        return True, None

    def confirm_data_type(self):
        if self._file:
            self._file = Path(self._file)
        if self.data_dir:
            self.data_dir = Path(self.data_dir)
        self.user = {u: confirm_dc_type(config, LBConfigUser) for u, config in self.user.items()}

        # Initialize the configuration with each provider's own config class.
        config: Dict
        for name, config in self.provider.items():
            if not config.get("enable", True):
                continue

            load_module = config.get("load_module", "")
            provider_cls = get_cls(load_module)
            if not provider_cls:
                raise InvalidConfigException(
                    f'Invalid `load_module` config for {name}, it must be in format "module_path::class_name", '
                    f"please check your config and whether file exists."
                )
            self.provider[name] = confirm_dc_type(config, provider_cls.config)
            self._provider_cls[name] = provider_cls

    @property
    def provider_cls(self):
        return self._provider_cls

    @property
    def servers_db_path(self) -> Path:
        return self.data_dir.joinpath(self.servers_file)


def load_local_servers(servers_db_path: Path) -> typeOrderedDict[str, LBServerMeta]:
    """
    load from `servers_file` config, return result
    """
    servers_json = []
    try:
        with open(servers_db_path, "r+") as f:
            content = f.read()
            if content:
                servers_json = json.loads(content)
    except (FileNotFoundError, JSONDecodeError) as e:
        logger.error(f"Error when reading local db {str(servers_db_path)}, {str(e)}")
        return OrderedDict()
    logger.debug(f"open server_json, find {len(servers_json)} available_servers: {servers_json}")
    d = OrderedDict()
    for i in servers_json:
        server = LBServerMeta(**i)
        d[server.server_name] = server
    return d


def update_local_servers(
    servers_db_path: Path,
    new: List[LBServerMeta] = None,
    deleted: List[LBServerMeta] = None,
) -> Dict[str, LBServerMeta]:
    local_servers = load_local_servers(servers_db_path)

    _add_servers = new or []
    local_servers.update({server.server_name: server for server in _add_servers})

    _remove_servers = deleted or []
    for server in _remove_servers:
        local_servers.pop(server.server_name, None)

    with open(servers_db_path, "w+") as f:
        c = [asdict(i, dict_factory=lb_dict_factory) for i in local_servers.values()]  # noqa
        f.write(json.dumps(c))
    return local_servers
