import shutil
from pathlib import Path

import pytest

from lobbyboy.config import LBServerMeta
from lobbyboy.contrib.provider.footloose import FootlooseConfig, FootlooseProvider


@pytest.fixture
def footloose_provider():
    workspace = Path("/tmp/footloose_test/")
    yield FootlooseProvider(name="footloose", config=FootlooseConfig(), workspace=workspace)
    shutil.rmtree(workspace, ignore_errors=True)


@pytest.fixture
def footloose_server_meta():
    workspace = Path("/tmp/footloose_test/")
    yield LBServerMeta(workspace=workspace, provider_name="footloose", server_name="2021-12-05-1405")
    shutil.rmtree(workspace, ignore_errors=True)
