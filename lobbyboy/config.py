import json
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass, replace, field, fields, asdict
from json import JSONDecodeError
from pathlib import Path
from typing import Dict, List, Tuple

import toml

from lobbyboy.utils import lb_dict_factory

logger = logging.getLogger(__name__)


@dataclass
class LBConfigUser:
    authorized_keys: str = ""
    password: bool = False

    def auth_key_pairs(self) -> List[Tuple]:
        """

        Returns:
            tuple: (key_type, key_data)
        """
        return [tuple(ssh_key.split(maxsplit=1)) for ssh_key in self.authorized_keys.split("\n") if ssh_key]


@dataclass
class LBConfigProvider:
    load_module: str
    min_life_to_live: str = "50m"  # 最少存活时间
    bill_time_unit: str = "55m"
    private_key: str = "auto"
    extra_ssh_keys: List[str] = field(default_factory=list)
    favorite_droplets: List[str] = field(default_factory=list)
    api_token: str = ""
    destroy_safe_time: str = "3m"
    server_name_prefix: str = "lobbyboy"

    # todo unique configuration of each provider
    vagrantfile: str = ""


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
    # indicate whether this server is managed by lobbyboy or not.
    manage: bool = True

    def __post_init__(self):
        if isinstance(self.workspace, str):
            self.workspace = Path(self.workspace)

    @property
    def live_sec(self) -> int:
        return int(time.time()) - self.created_timestamp


@dataclass
class LBConfig:
    _file: Path
    _raw: Dict = field(default_factory=dict)
    data_dir: Path = None
    user: Dict[str, LBConfigUser] = field(default_factory=dict)
    provider: Dict[str, LBConfigProvider] = field(default_factory=dict)
    listen_port: int = 12200
    listen_ip: str = "0.0.0.0"
    log_level: str = "DEBUG"
    min_destroy_interval: str = "5m"
    servers_file: str = "available_servers_db.json"

    def __post_init__(self):
        # TODO
        if self.data_dir:
            self.data_dir = Path(self.data_dir)
        if any(1 for i in self.user.values() if not isinstance(i, LBConfigUser)):
            self.user = {name: LBConfigUser(**config) for name, config in self.user.items()}  # noqa
        if any(1 for i in self.provider.values() if not isinstance(i, LBConfigProvider)):
            self.provider = {name: LBConfigProvider(**config) for name, config in self.provider.items()}  # noqa

    def reload(self) -> "LBConfig":
        return load_config(self._file)

    @property
    def servers_db_path(self) -> Path:
        return self.data_dir.joinpath(self.servers_file)

    @classmethod
    def load_local_servers(cls, db_path: Path) -> OrderedDict[str, LBServerMeta]:
        """
        load from available_servers_db.json file, return result
        """
        servers_json = []
        try:
            with open(db_path, "r+") as f:
                if content := f.read():
                    servers_json = json.loads(content)
        except (FileNotFoundError, JSONDecodeError) as e:
            logger.error(f"Error when reading local db {str(db_path)}, {str(e)}")
            return OrderedDict()
        logger.debug(f"open server_json, find {len(servers_json)} available_servers: {servers_json}")
        return OrderedDict({server.server_name: server for i in servers_json if (server := LBServerMeta(**i))})

    @classmethod
    def update_local_servers(
        cls,
        db_path: Path,
        new: List[LBServerMeta] = None,
        deleted: List[LBServerMeta] = None,
    ) -> Dict[str, LBServerMeta]:
        local_servers = cls.load_local_servers(db_path)

        _add_servers = new or []
        local_servers.update({server.server_name: server for server in _add_servers})

        _remove_servers = deleted or []
        for server in _remove_servers:
            local_servers.pop(server.server_name, None)

        with open(db_path, "w+") as f:
            c = [asdict(i, dict_factory=lb_dict_factory) for i in local_servers.values()]
            f.write(json.dumps(c))
        return local_servers


def load_config(config_file: Path) -> LBConfig:
    raw_head_config = toml.load(config_file)
    logger.debug(f"loading configs from {str(config_file)}, config: {raw_head_config}")

    config = LBConfig(_file=config_file, _raw=raw_head_config)
    config_file_file = {
        f.name: raw_head_config[f.name]
        for f in fields(LBConfig)
        if f.name in raw_head_config and not f.name.startswith("_")
    }
    return replace(config, **config_file_file)
