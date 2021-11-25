import os
import re
import logging
import socket
import threading
from datetime import timedelta, datetime, date
from enum import Enum, unique
from io import StringIO
from pathlib import Path
from typing import List, Dict, Tuple, Callable, Union, Any, Type

import paramiko
from paramiko.channel import Channel

from lobbyboy.exceptions import UnsupportedPrivateKeyTypeException, UserCancelException, TimeStrParseTypeException

logger = logging.getLogger(__name__)


DoGSSAPIKeyExchange = True
active_session: Dict[str, List[paramiko.Transport]] = {}
available_server_db_lock = threading.Lock()
active_session_lock = threading.Lock()

UNIT_SEC_PAIRS = {
    "s": 1,
    "m": 1 * 60,
    "h": 1 * 60 * 60,
    "d": 1 * 60 * 60 * 24,
}


def lb_dict_factory(d: Union[Dict, Tuple], ignore_fields: List[str] = None, ignore_rules: Callable = None) -> Dict:
    _ignore_fields = ignore_fields or []
    _ignore_rules = ignore_rules or (lambda x: False)
    dd = d.items() if isinstance(d, dict) else d
    _d = {}
    for k, v in dd:
        if k is None:
            continue
        if k in _ignore_fields:
            continue
        if _ignore_rules(k):
            continue
        if isinstance(v, Path):
            v = str(v)
        if isinstance(v, datetime):
            v = v.strftime("%Y-%m-%d %H:%M:%S")
        if isinstance(v, date):
            v = v.strftime("%Y-%m-%d")
        _d[k] = v
    return _d


def port_is_open(ip: str, port: int = 22) -> bool:
    a_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    a_socket.settimeout(2)
    result = a_socket.connect_ex((ip, port))
    a_socket.close()
    return result == 0


def to_seconds(time_str: str) -> int:
    """
    Args:
        time_str: str, 10s, 10m, 10h, 10d

    Returns:
        int: seconds
    """
    for unit, sec in UNIT_SEC_PAIRS.items():
        re_time_str = r"(\d+){unit}".format(unit=unit)
        matched = re.match(re_time_str, time_str)
        if matched:
            return int(matched.group(1)) * sec
    raise TimeStrParseTypeException(f"Can not parse {time_str}")


def humanize_seconds(seconds: int):
    """human-readable, eg: 364121 -> '4 days 5:08:41'"""
    return str(timedelta(seconds=seconds))


def send_to_channel(channel: Channel, msg: str = "", prefix: str = "", suffix: str = "\r\n"):
    if isinstance(msg, bytes):
        msg = msg.decode()
    channel.send(f"{prefix or ''}{msg}{suffix or ''}".encode())


def confirm_dc_type(value: Any, should_be: Type):
    """
    confirm that the value is of the correct type during dataclass conversion, try converting it if it is not
    consider replacing it with [dacite](https://github.com/konradhalas/dacite/)

    Args:
        value: the value that we want to check
        should_be: the value type we expect or convert to

    Returns:
        value: the value that was passed in, converted if needed
    """
    if isinstance(value, should_be):
        return value
    elif isinstance(value, dict):
        return should_be(**value)
    logger.error(f"{should_be.__name__} unable to confirm type of {value}, type: {type(value)}")
    return value


def choose_option(channel: Channel, options: List[str], option_prompt: str = None, ask_prompt: str = None) -> int:
    """
    ask user to choose one option from channel
    """
    logger.info(f"need user choose from {options}\nprompt: {option_prompt}")
    send_to_channel(channel, option_prompt or "Available options:")
    for index, option in enumerate(options):
        send_to_channel(channel, f"{index:>3} - {option}")
    _ask_prompt = ask_prompt or f"Please enter the number of choice[{0}-{len(options) - 1}]: "
    send_to_channel(channel, _ask_prompt, suffix="")

    result = read_user_input_line(channel)
    try:
        num_selected = int(result)
        if 0 <= num_selected < len(options):
            logger.info(f"user choose {result} for option {option_prompt}")
            send_to_channel(channel, f"You selected: {options[num_selected]}")
            return num_selected
        raise Exception(f"user choose {result} for option {option_prompt}, but it's out of range")
    except Exception:  # noqa
        logger.error(f"user choose {result} for option {option_prompt} invalid, re-choose...")
        send_to_channel(channel, f"unknown choose, please choose again [{0}-{len(options) - 1}]")
        return choose_option(channel, options, option_prompt=option_prompt, ask_prompt=ask_prompt)


def read_user_input_line(channel) -> str:
    # TODO do not support del
    # receive user input correctly: see [ANSI escape code](https://en.wikipedia.org/wiki/ANSI_escape_code)
    chars = []
    while 1:
        content = channel.recv(1)
        logger.debug(f"channel recv: {content}")
        if content in [b"\x04", b"\x03"]:
            raise UserCancelException()
        elif content == b"\r":
            send_to_channel(channel)
            break
        elif content in [b"\x7f"]:
            send_to_channel(channel, "\x08\x1b[K", suffix="")
            continue
        else:
            send_to_channel(channel, content, suffix="")
            chars.append(content)
    return b"".join(chars).decode()


@unique
class KeyTypeSupport(Enum):
    # openssh ssh-keygen: The default length is 3072 bits (RSA) or 256 bits (ECDSA).
    # todo default length of DSS/ED25519
    RSA = "RSA", 3072
    DSS = "DSS"
    ED25519 = "ED25519"
    ECDSA = "ECDSA", 256

    def __init__(self, key, default_key_length=None):
        super().__init__()
        self._key = key
        self.default_key_length = default_key_length

    @property
    def key(self) -> str:
        return self._key


def confirm_ssh_key_pair(key_type: KeyTypeSupport = KeyTypeSupport.RSA, key_len: int = None, save_path: Path = None):
    pri_key, pub_key = try_load_key_from_file(from_path=save_path, key_type=key_type)
    if pri_key and pub_key:
        return pri_key, pub_key

    pri_key, pub_key = generate_ssh_key_pair(key_type=key_type, key_len=key_len)
    if not save_path:
        return pri_key, pub_key
    return write_key_to_file(pri_key, pub_key, key_type=key_type, save_path=save_path)


def generate_ssh_key_pair(key_type: KeyTypeSupport = KeyTypeSupport.RSA, key_len: int = None) -> Tuple[str, str]:
    _key_length = key_len or key_type.default_key_length
    if not _key_length:
        raise UnsupportedPrivateKeyTypeException()

    if key_type == KeyTypeSupport.RSA:
        key = paramiko.RSAKey.generate(bits=_key_length)
    elif key_type == KeyTypeSupport.DSS:
        key = paramiko.DSSKey.generate(bits=_key_length)
    elif key_type == KeyTypeSupport.ECDSA:
        key = paramiko.ECDSAKey.generate(bits=_key_length)
    elif key_type == KeyTypeSupport.Ed25519:
        # Todo
        raise UnsupportedPrivateKeyTypeException()
    else:
        raise UnsupportedPrivateKeyTypeException()

    out = StringIO()
    key.write_private_key(out)
    return out.getvalue(), f"{key.get_name()} {key.get_base64()}"


def write_key_to_file(pri_key: str, pub_key: str, key_type: KeyTypeSupport, save_path: Path) -> Tuple[str, str]:
    save_path = save_path.joinpath(".ssh")
    save_path.mkdir(parents=True, exist_ok=True, mode=0o700)
    private_key_file = save_path.joinpath(f"id_{key_type.key.lower()}")
    public_key_file = save_path.joinpath(f"id_{key_type.key.lower()}.pub")

    if private_key_file.exists() and public_key_file.exists():
        logger.info(f"ssh key pair exists: {private_key_file}/{public_key_file}, skip generation.")
        return pri_key, pub_key

    with open(private_key_file, "w+") as f:
        f.write(pri_key)
    os.chmod(private_key_file, 0o600)
    with open(public_key_file, "w+") as f:
        f.write(pub_key)
    os.chmod(public_key_file, 0o600)
    return pri_key, pub_key


def try_load_key_from_file(from_path: Path, key_type: KeyTypeSupport, raise_error: bool = False) -> Tuple[str, str]:
    from_path = from_path.joinpath(".ssh")
    private_key_file = from_path.joinpath(f"id_{key_type.key.lower()}")
    public_key_file = from_path.joinpath(f"id_{key_type.key.lower()}.pub")

    pri_key = pub_key = ""
    if private_key_file.exists():
        with open(private_key_file, "r+") as f:
            pri_key = f.read()
    if public_key_file.exists():
        with open(public_key_file, "r+") as f:
            pub_key = f.read()

    if not (pri_key and pub_key) and raise_error:
        raise FileNotFoundError(f"ssh key pair not found: {private_key_file}/{public_key_file}")
    return pri_key, pub_key
