from lobbyboy.config import LBConfigProvider, LBServerMeta
from lobbyboy.contrib.provider.footloose import FootlooseProvider
import pytest
from pathlib import Path


@pytest.fixture
def footloose_provider():
    return FootlooseProvider(name="footloose", config=LBConfigProvider(), workspace=Path("/tmp/footloose_test/"))


@pytest.fixture
def footloose_servermeta():
    return LBServerMeta(
        provider_name="footloose", workspace=Path("/tmp/footloose_test/"), server_name="2021-12-05-1405"
    )
