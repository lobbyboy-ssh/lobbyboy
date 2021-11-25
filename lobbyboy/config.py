import json
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass, replace, field, fields, asdict
from json import JSONDecodeError
from pathlib import Path
from typing import Dict, List, Tuple, OrderedDict as typeOrderedDict, Optional

import toml

from lobbyboy.exceptions import InvalidConfigException
from lobbyboy.utils import lb_dict_factory, confirm_dc_type

logger = logging.getLogger(__name__)


@dataclass
class LBConfigUser:
    authorized_keys: str = None
    password: bool = None

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
    load_module: str = None
    min_life_to_live: str = None
    bill_time_unit: str = None
    api_token: str = None
    destroy_safe_time: str = None
    server_name_prefix: str = None
    extra_ssh_keys: List[str] = field(default_factory=list)
    favorite_instance_types: List[str] = field(default_factory=list)

    # todo unique configuration of each provider
    vagrantfile: str = None


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
    _file: Path = None
    _raw: Dict = field(default_factory=dict)
    data_dir: Path = None
    user: Dict[str, LBConfigUser] = field(default_factory=dict)
    provider: Dict[str, LBConfigProvider] = field(default_factory=dict)
    listen_port: int = None
    listen_ip: str = None
    log_level: str = None
    min_destroy_interval: str = None
    servers_file: str = None

    def __post_init__(self):
        self.confirm_data_type()

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
        if self.data_dir:
            self.data_dir = Path(self.data_dir)
        self.user = {u: confirm_dc_type(config, LBConfigUser) for u, config in self.user.items()}
        self.provider = {p: confirm_dc_type(config, LBConfigProvider) for p, config in self.provider.items()}

    def reload(self) -> "LBConfig":
        return load_config(self._file)

    @property
    def servers_db_path(self) -> Path:
        return self.data_dir.joinpath(self.servers_file)

    @classmethod
    def load_local_servers(cls, db_path: Path) -> typeOrderedDict[str, LBServerMeta]:
        """
        load from `servers_file` config, return result
        """
        servers_json = []
        try:
            with open(db_path, "r+") as f:
                content = f.read()
                if content:
                    servers_json = json.loads(content)
        except (FileNotFoundError, JSONDecodeError) as e:
            logger.error(f"Error when reading local db {str(db_path)}, {str(e)}")
            return OrderedDict()
        logger.debug(f"open server_json, find {len(servers_json)} available_servers: {servers_json}")
        d = OrderedDict()
        for i in servers_json:
            server = LBServerMeta(**i)
            d[server.server_name] = server
        return d

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

    # init config
    config = LBConfig(_file=config_file, _raw=raw_head_config)

    # update it from config file
    config_file_file = {
        f.name: raw_head_config[f.name]
        for f in fields(LBConfig)
        if f.name in raw_head_config and not f.name.startswith("_")
    }
    config = replace(config, **config_file_file)

    # validation
    is_valid, reason = config.validate()
    if not is_valid:
        raise InvalidConfigException(reason)
    return config
