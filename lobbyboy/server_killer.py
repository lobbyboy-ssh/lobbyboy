import time
import json
import pathlib
import logging


from .utils import parse_time_config, load_server_db

FIVE_MINUTES = 5 * 60
logger = logging.getLogger(__name__)


def killer(config, active_sessions, available_server_db_lock, providers):
    interval_seconds = parse_time_config(config["destroy_interval"])
    db_path = pathlib.Path(config["data_dir"]) / "available_servers.json"
    while 1:
        logger.info("killer start a new round...")
        check_all_live_servers(
            str(db_path), active_sessions, config, available_server_db_lock, providers
        )
        time.sleep(interval_seconds)


def check_all_live_servers(
    db_path: str,
    active_sessions: dict,
    config: dict,
    available_server_db_lock,
    providers,
):
    servers = load_server_db(db_path)
    for server in servers:
        serverid = server["server_id"]
        need_to_be_destroy, reason = server_need_destroy(
            active_sessions.get(serverid, []), server, config
        )
        logger.info(
            "{} need to be destroyed? {}, reson: {}".format(
                serverid, need_to_be_destroy, reason
            )
        )
        if need_to_be_destroy:
            provider_name = server["provider"]
            provider = providers[provider_name]
            destroy_server(provider, server, db_path, available_server_db_lock, None)


def server_need_destroy(active_sessions: list, serverinfo: dict, config: dict):
    """
    check if a server need to be destroyed.

    Args:
        active_session: list, track current active session on sever
        serverinfo: dict, example:
            {'server_id': 'lobbyboy-29',
             'server_host': '127.0.0.1',
             'provider': 'vagrant',
             'created_timestamp': 1635175057.377654}
    Returns:
        tuple, (need_to_be_destroy: bool, reason: str)
    """
    active_session_count = len(active_sessions)
    if active_session_count:
        return False, "still have {} active sessions".format(active_session_count)
    provider_name = serverinfo["provider"]
    born_time = serverinfo["created_timestamp"]
    provider_configs = config["provider"]
    pconfig = provider_configs[provider_name]

    lived_time = time.time() - born_time
    min_life_to_live_seconds = parse_time_config(pconfig["min_life_to_live"])
    if min_life_to_live_seconds == 0:
        return True, "min_life_to_live set to 0"

    bill_time_unit = parse_time_config(pconfig["bill_time_unit"])
    destroy_spare_seconds = max(
        [parse_time_config(config["destroy_interval"]), FIVE_MINUTES]
    )
    bill_unit_left_time = (
        bill_time_unit - destroy_spare_seconds - (lived_time % bill_time_unit)
    )

    min_live_left_seconds = min_life_to_live_seconds - lived_time
    if min_live_left_seconds > 0:
        return False, "still have {} to live(min_life_to_live={}).".format(
            humanize_seconds(min_live_left_seconds), pconfig["min_life_to_live"]
        )
    if bill_unit_left_time > 0:
        return False, "still have {} to live(bill_time_unit={}).".format(
            humanize_seconds(bill_unit_left_time),
            pconfig["bill_time_unit"],
        )
    return True, "is about to enter the next billing cycle"


def humanize_seconds(seconds: int):
    if seconds <= 60:
        return "{} seconds".format(str(seconds))

    minutes = seconds // 60
    if minutes <= 60:
        return "{} minutes".format(str(minutes))

    hours = minutes // 60
    if hours <= 24:
        return "{} hours".format(str(hours))

    days = hours // 24
    return "{} days".format(str(days))


def destroy_server(
    provider,
    serverinfo,
    available_server_db_path,
    available_server_db_lock,
    channel=None,
):
    """
    Args:
        provider: provider instance, object
        serverinfo: server data dict
    """
    provider.destroy_server(serverinfo["server_id"], serverinfo["server_host"], channel)
    delete_from_server_db(
        available_server_db_lock,
        available_server_db_path,
        serverinfo["server_id"],
    )


def delete_from_server_db(available_server_db_lock, available_server_db_path, serverid):
    with available_server_db_lock:
        servers = load_server_db(available_server_db_path)
        new_servers = [s for s in servers if s["server_id"] != serverid]
        json.dump(
            new_servers,
            open(available_server_db_path, "w+"),
        )
