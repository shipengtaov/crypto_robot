class ExchangeException(Exception):
    pass


class HuobiException(ExchangeException):
    pass


class SymbolPairNotExist(Exception):
    """火币的 symbol 不存在. 比如 cvntusdt"""
    pass


class InsufficientMarginAvailable(ExchangeException):
    """开仓时对应 volumn 所需的余额不足"""
    pass
