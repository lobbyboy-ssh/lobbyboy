class BaseProvider:
    def __init__(self, configs, ssh_command):
        self.configs = configs
        self.ssh_command = ssh_command

    def new_server(self):
        pass

    def destroy_server(self):
        pass

    def ssh_server_command(self, server_id):
        pass

    def get_bill(self):
        pass
