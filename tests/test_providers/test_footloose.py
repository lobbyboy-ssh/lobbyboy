import re
from pathlib import Path
from unittest import mock
from unittest.mock import call

from freezegun import freeze_time

from lobbyboy.config import LBServerMeta


@mock.patch("subprocess.run")
def test_footloose_destroy(fake_subprocess_run, footloose_provider, footloose_server_meta):
    fake_complete_process = mock.MagicMock()
    fake_complete_process.return_value.returncode = 0
    fake_subprocess_run.side_effect = fake_complete_process

    destroy_command = footloose_provider.destroy_server(footloose_server_meta, None)
    fake_subprocess_run.assert_called_with(
        ["footloose", "delete", "-c", Path("/tmp/footloose_test/footloose.yaml")], capture_output=True
    )
    assert destroy_command is True


def test_ssh_server_commands(footloose_provider, footloose_server_meta):
    command = footloose_provider.ssh_server_command(footloose_server_meta, None)
    assert command == ["cd /tmp/footloose_test && footloose ssh root@2021-12-05-14050"]


@mock.patch("subprocess.Popen")
@freeze_time("2012-01-14 12:00:01")
def test_create_server(mock_popen, footloose_provider):
    mock_channel = mock.MagicMock()
    mock_process = mock.MagicMock()
    mock_process.poll.side_effect = [False, True]
    mock_process.returncode = 0
    mock_popen.return_value = mock_process

    server = footloose_provider.create_server(mock_channel)

    mock_popen.assert_called_with(["footloose", "create"], cwd="/tmp/footloose_test/2012-01-14-1200")
    assert mock_channel.sendall.mock_calls[:3] == [
        call(b"Generate server 2012-01-14-1200 workspace /tmp/footloose_test/2012-01-14-1200 done.\r\n"),
        call(b"Check footloose create done"),
        call(b"."),
    ]
    assert re.match(br"OK\(\d.\ds\).\r\n", mock_channel.sendall.mock_calls[-1][1][0]) is not None
    assert server == LBServerMeta(
        provider_name="footloose",
        workspace=Path("/tmp/footloose_test/2012-01-14-1200"),
        server_name="2012-01-14-1200",
        server_host="127.0.0.1",
        server_user="root",
        server_port=22,
        created_timestamp=1326542401,
        ssh_extra_args=[],
        manage=True,
    )
