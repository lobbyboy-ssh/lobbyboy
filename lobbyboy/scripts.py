import os


def print_example_config():
    example_config_file = os.path.dirname(__file__) + "/conf/lobbyboy_config.toml"
    with open(example_config_file, "r") as conf:
        print(conf.read())
