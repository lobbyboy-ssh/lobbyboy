import copy
import os.path
import sys
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from unittest import mock

import pytest

from lobbyboy.exceptions import CantEnsureBytesException, TimeStrParseTypeException
from lobbyboy.utils import (
    confirm_dc_type,
    dict_factory,
    encoder_factory,
    ensure_bytes,
    humanize_seconds,
    import_class,
    port_is_open,
    send_to_channel,
    to_seconds,
)
from tests.conftest import test_pair


@dataclass
class FakeDataclass:
    A: int = 1
    B: str = "b"


test_args_encoder_factory = [
    test_pair(input=date(2001, 1, 19), expected="2001-01-19"),
    test_pair(input=datetime(2000, 1, 10, 23, 58, 59), expected="2000-01-10 23:58:59"),
    test_pair(input=Decimal("19.3"), expected="19.3"),
    test_pair(input=Path("/go/to/test/path"), expected="/go/to/test/path"),
    test_pair(input=FakeDataclass(), expected={"A": 1, "B": "b"}),
    test_pair(input={"A": "A"}, expected={"A": "A"}),
]


@pytest.mark.parametrize("test", test_args_encoder_factory)
def test_encoder_factory(test: test_pair):
    encoder = encoder_factory(raise_error=False)
    assert encoder(test.input) == test.expected


test_mutation_args_encoder_factory = [
    test_pair(input=date(2001, 1, 19), expected="2001/01/19"),
    test_pair(input=datetime(2000, 1, 10, 23, 58, 59), expected="20000110 235859"),
    test_pair(input=Decimal("19.3"), expected=19),
    test_pair(input=Path("/go/to/test/path"), expected="path"),
    test_pair(input={"B": "C"}, expected={"B": "C"}),
]


@pytest.mark.parametrize("test", test_mutation_args_encoder_factory)
def test_encoder_factory_mutation(test: test_pair):
    encoder = encoder_factory(
        date_fmt="%Y/%m/%d",
        dt_fmt="%Y%m%d %H%M%S",
        decimal_factory=int,
        path_factory=lambda x: os.path.basename(x),
        raise_error=False,
    )
    assert encoder(test.input) == test.expected


def test_encoder_factory_exception():
    encoder = encoder_factory()
    with pytest.raises(TypeError):
        encoder(range(3))


test_args_dict_factory = [
    test_pair(
        input=[
            {
                "A": "A",
                "B": "B",
                "ignore_field_1": "ignore_field_1",
                "ignore_field_2": "ignore_field_2",
                "_ignore_1": "_ignore_1",
                "_ignore_2": "_ignore_2",
            },
            ["ignore_field_1", "ignore_field_2"],
            lambda x: x.startswith("_"),
        ],
        expected={"A": "A", "B": "B"},
    ),
    test_pair(
        input=[
            {
                "C": Decimal("19.3"),
                "ignore_field_4": "ignore_field_14",
                "_ignore_2": "_ignore_2",
            },
            ["ignore_field_4", "ignore_field_5"],
            lambda x: False,
            encoder_factory(raise_error=False),
        ],
        expected={"C": "19.3", "_ignore_2": "_ignore_2"},
    ),
]


@pytest.mark.parametrize("test", test_args_dict_factory)
def test_dict_factory(test: test_pair):
    original = copy.deepcopy(test.input)
    assert dict_factory(*test.input) == test.expected
    assert original == test.input


@mock.patch("socket.socket.connect_ex")
def test_port_is_open(fake_socket):
    test_ip = "127.0.0.1"

    fake_socket.side_effect = mock.MagicMock(return_value=0)
    is_open = port_is_open(test_ip)
    assert is_open is True

    fake_socket.side_effect = mock.MagicMock(return_value=1)
    is_open = port_is_open(test_ip)
    assert is_open is False


test_args_to_seconds = [
    test_pair(input="0", expected=0),
    test_pair(input="10s", expected=10),
    test_pair(input="1m", expected=60),
    test_pair(input="59m", expected=60 * 59),
    test_pair(input="1h", expected=60 * 60),
    test_pair(input="20h", expected=60 * 60 * 20),
    test_pair(input="1d", expected=60 * 60 * 24 * 1),
    test_pair(input="3d", expected=60 * 60 * 24 * 3),
]


@pytest.mark.parametrize("test", test_args_to_seconds)
def test_to_seconds(test: test_pair):
    assert to_seconds(test.input) == test.expected


test_exception_args_to_seconds = [
    test_pair(input="-1", expected=TimeStrParseTypeException),
    test_pair(input="2", expected=TimeStrParseTypeException),
    test_pair(input="1w", expected=TimeStrParseTypeException),
    test_pair(input="1min", expected=TimeStrParseTypeException),
]


@pytest.mark.parametrize("test", test_exception_args_to_seconds)
def test_to_seconds_exception(test: test_pair):
    with pytest.raises(test.expected):
        to_seconds(test.input)


test_args_humanize_seconds = [
    test_pair(input=0, expected="0:00:00"),
    test_pair(input=44, expected="0:00:44"),
    test_pair(input=364121, expected="4 days, 5:08:41"),
]


@pytest.mark.parametrize("test", test_args_humanize_seconds)
def test_humanize_seconds(test: test_pair):
    assert humanize_seconds(test.input) == test.expected


test_args_ensure_bytes = [
    test_pair(input="test", expected=b"test"),
    test_pair(input=b"test", expected=b"test"),
]


@pytest.mark.parametrize("test", test_args_ensure_bytes)
def test_ensure_bytes(test: test_pair):
    assert ensure_bytes(test.input) == test.expected


test_exception_args_ensure_bytes = [
    test_pair(input=None, expected=CantEnsureBytesException),
    test_pair(input=0, expected=CantEnsureBytesException),
]


@pytest.mark.parametrize("test", test_exception_args_ensure_bytes)
def test_ensure_bytes_exception(test: test_pair):
    with pytest.raises(test.expected):
        ensure_bytes(test.input)


test_args_send_to_channel = [
    test_pair(input=["fake_msg1", "prefix1", "suffix1"], expected=None),
    test_pair(input=["fake_msg2", b"prefix2", "suffix2"], expected=None),
    test_pair(input=["fake_msg3", "prefix3", b"suffix3"], expected=None),
]


@pytest.mark.parametrize("test", test_args_send_to_channel)
def test_send_to_channel(test: test_pair):
    fake_channel = mock.MagicMock()
    assert send_to_channel(fake_channel, *test.input) == test.expected


test_args_confirm_dc_type = [
    test_pair(input=[FakeDataclass(A=2, B="1"), FakeDataclass], expected=FakeDataclass(A=2, B="1")),
    test_pair(input=[dict(A=2, B="1"), FakeDataclass], expected=FakeDataclass(A=2, B="1")),
    test_pair(input=[None, FakeDataclass], expected=None),
    test_pair(input=[[1, 2, 3], FakeDataclass], expected=[1, 2, 3]),
]


@pytest.mark.parametrize("test", test_args_confirm_dc_type)
def test_confirm_dc_type(test: test_pair):
    assert test.expected == confirm_dc_type(*test.input)


def test_choose_option():
    ...


def test_read_user_input_line():
    ...


def test_confirm_ssh_key_pair():
    ...


def test_generate_ssh_key_pair():
    ...


def test_write_key_to_file():
    ...


def test_try_load_key_from_file():
    ...


def test_import_class():
    assert import_class("") is None
    assert import_class("Test") is None
    assert import_class("Test::A::B") is None

    with mock.patch("importlib.import_module") as imp:
        imp.side_effect = mock.MagicMock(return_value=sys.modules[__name__])
        assert import_class(f"FAKE_MODULE::{FakeDataclass.__name__}") is FakeDataclass
