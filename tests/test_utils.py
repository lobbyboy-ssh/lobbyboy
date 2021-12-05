from lobbyboy.utils import to_seconds


def test_to_seconds():
    assert 10 == to_seconds("10s")
    assert 60 == to_seconds("1m")
    assert 60 * 59 == to_seconds("59m")
    assert 60 * 60 == to_seconds("1h")
    assert 60 * 60 * 20 == to_seconds("20h")
    assert 60 * 60 * 24 * 1 == to_seconds("1d")
    assert 60 * 60 * 24 * 3 == to_seconds("3d")
    assert 0 == to_seconds("0")
