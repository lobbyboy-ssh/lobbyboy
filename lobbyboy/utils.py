import re
import os
import json
import logging


from . import exceptions


logger = logging.getLogger(__name__)


def parse_time_config(timestr: str):
    """
    Args:
        timestr: str, 10s, 10m, 10h, 10d
    Returns:
        seconds
    """
    matched = re.match(r"(\d+)s", timestr)
    if matched:
        return int(matched.group(1))

    matched = re.match(r"(\d+)m", timestr)
    if matched:
        return int(matched.group(1)) * 60

    matched = re.match(r"(\d+)h", timestr)
    if matched:
        return int(matched.group(1)) * 60 * 60

    matched = re.match(r"(\d+)d", timestr)
    if matched:
        return int(matched.group(1)) * 60 * 60 * 24

    raise Exception("Can not parse {}".format(timestr))


def load_server_db(db_path: str):
    """
    load from available_servers.json file, return result
    """
    try:
        server_json = json.load(open(db_path, "r+"))
    except Exception as e:
        logger.error("Error when reading available_servers.json, {}".format(str(e)))
        return []
    logger.debug(
        "open server_json, find {} available_servers: {}".format(
            len(server_json), server_json
        )
    )
    return server_json


def print_exmaple_config():
    with open(os.path.dirname(__file__) + "/conf/lobbyboy_config.toml", "r") as econf:
        print(econf.read())


def choose_option(ask_prompt: str, options, channel):
    """
    ask user to choose one option from channel
    """
    channel.send((ask_prompt + "\r\n").encode())
    for index, option in enumerate(options):
        channel.send("{:>3} - {}\r\n".format(index, option))
    channel.send("Please enter the number of choice: ".encode())
    user_input = int(read_user_input_line(channel))
    return options[user_input], user_input


def read_user_input_line(chan):
    # TODO do not support del
    logger.debug("reading from channel... {}".format(chan))
    chars = []
    while 1:
        content = chan.recv(1)
        logger.debug("channel recv: {}".format(content))
        if content == b"\r":
            chan.send(b"\r\n")
            break
        if content == b"\x04" or content == b"\x03":
            raise exceptions.UserCancelException()
        chan.send(content)
        chars.append(content)
    return b"".join(chars).decode()
