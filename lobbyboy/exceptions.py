class LobbyBoyException(Exception):
    pass


class InvalidConfigException(LobbyBoyException):
    pass


class TimeStrParseTypeException(LobbyBoyException):
    pass


class UnsupportedPrivateKeyTypeException(LobbyBoyException):
    pass


class UserCancelException(LobbyBoyException):
    pass


class ProviderException(LobbyBoyException):
    pass


class NoAvailableNameException(ProviderException):
    pass


class NoProviderException(ProviderException):
    pass


class NoTTYException(ProviderException):
    pass


class VagrantProviderException(ProviderException):
    pass
