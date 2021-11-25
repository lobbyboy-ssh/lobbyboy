import os


def print_example_config():
    example_config_file = os.path.dirname(__file__) + "/conf/lobbyboy_config.tom/conf/lobbyboy_config.tomll"
    with open(example_config_file, "r") as conf:
        print(conf.read())
