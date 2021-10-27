import logging
import toml

logger = logging.getLogger(__name__)


def load_config(config_path):
    config = toml.load(config_path)
    logger.info("loading configs... config: {}".format(config))
    return config
