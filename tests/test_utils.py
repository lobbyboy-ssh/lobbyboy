from lobbyboy.utils import parse_time_config


def test_parse_time_config():
    assert 10 == parse_time_config("10s")
    assert 60 == parse_time_config("1m")
    assert 60 * 59 == parse_time_config("59m")
    assert 60 * 60 == parse_time_config("1h")
    assert 60 * 60 * 20 == parse_time_config("20h")
    assert 60 * 60 * 24 * 1 == parse_time_config("1d")
    assert 60 * 60 * 24 * 3 == parse_time_config("3d")
