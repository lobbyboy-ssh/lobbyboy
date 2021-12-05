from lobbyboy.config import LBConfigProvider, LBServerMeta
import shutil
from lobbyboy.contrib.provider.footloose import FootlooseProvider
import pytest
from pathlib import Path


@pytest.fixture
def footloose_provider():
    workspace = Path("/tmp/footloose_test/")
    shutil.rmtree(workspace, ignore_errors=True)
    return FootlooseProvider(name="footloose", config=LBConfigProvider(), workspace=Path("/tmp/footloose_test/"))


@pytest.fixture
def footloose_servermeta():
    workspace = Path("/tmp/footloose_test/")
    shutil.rmtree(workspace, ignore_errors=True)
    return LBServerMeta(workspace=workspace, provider_name="footloose", server_name="2021-12-05-1405")
