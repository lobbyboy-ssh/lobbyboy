from pathlib import Path
import logging
import time
import threading

from lobbyboy.utils import choose_option

logger = logging.getLogger(__name__)


class BaseProvider:
    def __init__(self, provider_name, config, provider_config, data_path):
        self.config = config
        self.provider_name = provider_name
        self.provider_config = provider_config
        self.data_path = Path(data_path)

    def new_server(self, channel):
        """
        Args:
            channel: paramiko channel

        Returns:
            created_server_id: unique id from provision
            created_server_host: server's ip or domain address
        """
        pass

    def destroy_server(self, server_id, server_ip, channel):
        """
        Args:
            channel: Note that the channel can be None.
                     If called from server_killer, channel will be None.
                     if called when user logout from server, channel is active.
        """
        pass

    def ssh_server_command(self, server_id, server_ip):
        """
        Args:
           server_id: the server ssh to, which is returned by you from ``new_server``
           server_ip: ip or domain name.
        Returns:
            list: a command in list format, for later to run exec.
        """
        pass

    def get_bill(self):
        pass

    def send_timepass(self, chan, stop_event):
        start = time.time()

        def _print_time_elaspe():
            while not stop_event.is_set():
                current = time.time()
                chan.send(
                    "\rCreating new server... ({:.1f}s)".format(
                        current - start
                    ).encode()
                )
            chan.send(b"\r\n")

        t = threading.Thread(target=_print_time_elaspe)
        t.start()

    def choose_option(self, ask_prompt, options, channel):
        """
        Utils function.
        Give the user a list of choices, and return the user choosed one.

        Args:
            ask_prompt: str, a prompt to tell user what they are choosing
            options: list, a list of string
            channel: the channel to send and read user input

        Returns:
            string: user choosed option (in options)
            int: user input number

        Raises:
            lobbyboy.exceptions.UserCancelException: User press Ctrl-C to cancel the input
        """
        logger.info(
            "ask user to choose from {}, propmpt: {}".format(options, ask_prompt)
        )
        result = choose_option(ask_prompt, options, channel)
        logger.info("user choose reuslt: {}".format(result))
        return result
