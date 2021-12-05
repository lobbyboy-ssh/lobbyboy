from unittest import mock
from pathlib import Path


@mock.patch("subprocess.run")
def test_footloose_destroy(fake_subprocess_run, footloose_provider, footloose_servermeta):
    fake_complete_process = mock.MagicMock()
    fake_complete_process.return_value.returncode = 0
    fake_subprocess_run.side_effect = fake_complete_process

    destroy_command = footloose_provider.destroy_server(footloose_servermeta, None)
    fake_subprocess_run.assert_called_with(
        ["footloose", "delete", "-c", Path("/tmp/footloose_test/footloose.yaml")], capture_output=True
    )
    assert destroy_command == True
