import asyncio
import datetime
import random
import re
import string
import time
import traceback
from collections import deque
from enum import Enum
from functools import lru_cache
from os import path
from typing import List

import attr
import emoji
import loguru

from . import settings


class BaseEnum(Enum):
    @classmethod
    def from_string(cls, val:str):
        enum_map = {i.value.upper():i for i in cls}
        return enum_map.get(val.upper())


class BaseCoin(BaseEnum):
    pass


class BaseCoinSpot(BaseCoin):
    pass


class BaseCoinSwap(BaseCoin):
    pass


class Coin(BaseCoinSpot):
    """
    火币支持的所有现货币种(2021.02.18):
    ['hb10', 'usdt', 'btc', 'bch', 'eth', 'xrp', 'ltc', 'ht', 'ada', 'eos', 'iota', 'xem', 'xmr',
    'dash', 'neo', 'trx', 'icx', 'lsk', 'qtum', 'etc', 'btg', 'omg', 'hc', 'zec', 'dcr', 'steem',
    'bts', 'waves', 'snt', 'salt', 'glm', 'cmt', 'btm', 'pay', 'knc', 'powr', 'bat', 'dgd', 'ven',
    'qash', 'zrx', 'gas', 'mana', 'eng', 'cvc', 'mco', 'mtl', 'rdn', 'storj', 'chat', 'srn', 'link',
    'act', 'tnb', 'qsp', 'req', 'phx', 'appc', 'rcn', 'smt', 'adx', 'tnt', 'ost', 'itc', 'lun',
    'gnx', 'ast', 'evx', 'mds', 'snc', 'propy', 'eko', 'nas', 'bcd', 'waxp', 'wicc', 'topc',
    'swftc', 'dbc', 'elf', 'aidoc', 'qun', 'iost', 'yee', 'dat', 'theta', 'let', 'dta', 'utk',
    'meet', 'zil', 'soc', 'ruff', 'ocn', 'ela', 'bcx', 'sbtc', 'etf', 'bifi', 'zla', 'stk', 'wpr',
    'mtn', 'mtx', 'edu', 'blz', 'abt', 'ont', 'ctxc', 'bft', 'wan', 'kan', 'lba', 'poly', 'pai',
    'wtc', 'box', 'dgb', 'gxc', 'bix', 'xlm', 'xvg', 'hit', 'ong', 'bt1', 'bt2', 'firo', 'vet',
    'ncash', 'grs', 'egcc', 'she', 'mex', 'iic', 'gsc', 'uc', 'uip', 'cnn', 'aac', 'uuu', 'cdc',
    'lxt', 'but', '18c', 'datx', 'portal', 'gtc', 'hot', 'man', 'get', 'pc', 'ren', 'eosdac',
    'ae', 'bkbt', 'gve', 'seele', 'fti', 'ekt', 'xmx', 'ycc', 'fair', 'ssp', 'eon', 'eop', 'lym',
    'zjlt', 'meetone', 'pnt', 'idt', 'dac', 'bcv', 'sexc', 'tos', 'musk', 'add', 'mt', 'kcash',
    'iq', 'ncc', 'rccc', 'hpt', 'cvcoin', 'rte', 'trio', 'ardr', 'nano', 'usdc', 'gusd', 'tusd',
    'pax', 'husd', 'zen', 'rbtc', 'bsv', 'dock', 'mxc', 'xtz', 'wgp', 'nuls', 'cova', 'lamb',
    'cvnt', 'btt', 'doge', 'sc', 'kmd', 'mgo', 'abl', 'loom', 'nexo', 'mzk', 'etn', 'npxs', 'top',
    'adt', 'mvl', 'iris', 'hvt', 'tfuel', 'ugas', 'new', 'atom', 'inc', 'tt', 'rsr', 'cro', 'ogo',
    'nkn', 'fsn', 'atp', 'skm', 'algo', 'egt', 'ankr', 'akro', 'pvt', 'cnns', 'hbc', 'gt', 'pizza',
    'vsys', 'cre', 'ftt', 'lol', 'arpa', 'wxt', 'for', 'vidy', 'node', 'bhd', 'one', 'mx', 'em',
    'ckb', 'eoss', 'hive', 'ogn', 'jst', 'btc3l', 'btc3s', 'btc1s', 'nest', 'rvn', 'dot', 'usd01',
    'chr', 'luna', 'ksm', 'eth3l', 'eth3s', 'eth1s', 'bal', 'band', 'nvt', 'ant', 'mkr', 'dai',
    'crv', 'trb', 'dka', 'comp', 'snx', 'lend', 'stpt', 'wnxm', 'yfi', 'yfii', 'bnt', 'df', 'mln',
    'ring', 'mta', 'ach', 'value', 'yamv2', 'sushi', 'xrt', 'pearl', 'pha', 'sand', 'cvp', 'swrv',
    'bot', 'sun', 'gof', 'wbtc', 'renbtc', 'lrc', 'uma', 'dht', 'front', 'titan', 'wing', 'link3l',
    'link3s', 'uni', 'cru', 'nbs', 'dot2l', 'dot2s', 'uni2l', 'uni2s', 'avax', 'fis', 'bel', 'perp',
    'ar', 'bsv3l', 'bsv3s', 'bch3l', 'bch3s', 'chz', 'aave', 'hbar', 'near', 'fil', 'inj', 'eos3l',
    'eos3s', 'woo', 'mass', 'ltc3l', 'ltc3s', 'xrp3l', 'xrp3s', 'oxt', 'sol', 'kava', 'bcha', 'iotx',
    'zec3l', 'zec3s', 'beth', 'skl', 'rub', 'nsure', 'fil3l', 'fil3s', 'nhbtc', 'grt', 'api3', 'pond',
    'onx', 'eur', '1inch', 'lina', 'matic', 'bor', 'pols', 'bag', 'bags', 'badger', 'reef', 'mdx',
    'flow', 'auction', 'yam', 'zks']

    >>> Coin.from_string('btc') is Coin.BTC
    True
    """
    BTC = 'BTC'
    ETH = 'ETH'
    UNI = 'UNI'
    SUSHI = 'SUSHI'
    ADA = 'ADA'
    LTC = 'LTC'
    DOT = 'DOT'
    BCH = 'BCH'
    LINK = 'LINK'
    DASH = 'DASH'
    CRV = 'CRV'
    YFI = 'YFI'
    KSM = 'KSM'
    # 门罗币
    XMR = 'XMR'
    # Ripple 瑞波币
    XRP = 'XRP'
    EOS = 'EOS'
    AAVE = 'AAVE'
    LUNA = 'LUNA'
    SOL = 'SOL'
    AVAX = 'AVAX'
    MANA = 'MANA'
    SAND = 'SAND'
    ALICE = 'ALICE'
    SLP = 'SLP'
    AXS = 'AXS'

    # 币安交易所
    BNB = 'BNB'
    CAKE = 'CAKE'

    # 火币交易所
    HT = 'HT'

    # 波场
    TRX = 'TRX'

    DOGE = 'DOGE'
    SHIB = 'SHIB'

    MATIC = 'MATIC'

    NU = 'NU'
    NEAR = 'NEAR'
    GRT = 'GRT'
    ATOM = 'ATOM'
    FTM = 'FTM'
    ROSE = 'ROSE'
    MINA = 'MINA'
    ANT = 'ANT'
    # 币安为 scrt/busd, 没有 scrt/usdt
    SCRT = 'SCRT'
    VOXEL = 'VOXEL'
    PEOPLE = 'PEOPLE'
    ONE = 'ONE'

    ZEC = 'ZEC'
    BNT = 'BNT'
    FLOW = 'FLOW'
    HBAR = 'HBAR'

    ZKS = 'ZKS'
    XEM = 'XEM'
    # FileCoin
    FIL = 'FIL'
    # StaFi
    FIS = 'FIS'
    FRONT = 'FRONT'
    TITAN = 'TITAN'


class CoinSwap(BaseCoinSwap):
    """合约币"""
    BTC = 'BTC'
    ETH = 'ETH'
    BCH = 'BCH'
    LTC = 'LTC'
    DASH = 'DASH'
    LINK = 'LINK'
    YFI = 'YFI'
    DOT = 'DOT'
    ADA = 'ADA'
    UNI = 'UNI'
    SUSHI = 'SUSHI'
    CRV = 'CRV'
    # 门罗币
    XMR = 'XMR'
    # Ripple 瑞波币
    XRP = 'XRP'
    EOS = 'EOS'
    # 火币TOken
    HT = 'HT'
    DOGE = 'DOGE'


def make_coin_enum_dynamicly_adding(coins: List[str]=None, store_cache:bool=False) -> Enum:
    """动态添加成员到 Enum，返回新创建的 Enum 类

    # 来自: https://stackoverflow.com/questions/28126314/adding-members-to-python-enums
        from enum import Enum
        names = [m.name for m in ExistingEnum] + ['newname1', 'newname2']
        ExistingEnum = Enum('ExistingEnum', names)

    Args:
        store_cache: 是否将结果存入内存

    >>> obj = make_coin_enum_dynamicly_adding(['btc', 'eth', '1x'], store_cache=True)
    >>> obj.BTC.name, obj.BTC.value
    ('BTC', 'BTC')
    >>> obj.LTC.value
    'LTC'
    >>> getattr(obj, '1X').value
    '1X'

    >>> obj2 = make_coin_enum_dynamicly_adding()
    >>> obj2.BTC.name, obj2.BTC.value
    ('BTC', 'BTC')

    >>> obj.BTC is obj2.BTC
    True
    """
    if not hasattr(make_coin_enum_dynamicly_adding, 'coin_cache'):
        setattr(make_coin_enum_dynamicly_adding, 'coin_cache', deque(maxlen=1))

    if coins:
        coins = {(i.upper(), i.upper()) for i in coins}.union({(i.name, i.value) for i in Coin})
        res = BaseCoinSpot('NewCoin', coins)

        if store_cache:
            getattr(make_coin_enum_dynamicly_adding, 'coin_cache').append(res)
    queue = getattr(make_coin_enum_dynamicly_adding, 'coin_cache')
    res = queue[-1] if queue else None
    if not res:
        return Coin
    return res


def get_coin_lever(coin):
    """各个币种对应的杠杆
    hardcode 到程序中防止使用 settings 读取 env 时，万一杠杆特别高直接爆仓
    """
    if coin == Coin.BTC:
        return 5
    elif coin == Coin.ETH:
        return 5
    elif coin == Coin.UNI:
        return 5
    elif coin == Coin.ADA:
        return 5
    elif coin == Coin.BCH:
        return 5
    elif coin == Coin.LTC:
        return 5
    elif coin == Coin.LINK:
        return 5
    elif coin == Coin.BNB:
        return 5
    raise Exception(f'币种未设置杠杆率: {coin.value}')


class LongOrShort(BaseEnum):
    """做多还是做空"""
    LONG = 'LONG'
    SHORT = 'SHORT'


@attr.s
class Tick:
    # 属于 kline 的时间
    timestamp = attr.ib(default=None)
    # 以上时间的 datetime 格式
    date = attr.ib(default=None)
    # 事件事件. 滞后于上面的时间
    event_timestamp = attr.ib(default=None)

    open = attr.ib(factory=float)
    close = attr.ib(factory=float)
    high = attr.ib(factory=float)
    low = attr.ib(factory=float)
    vol = attr.ib(factory=float)
    amount = attr.ib(factory=float)

    # 是否是最后一个
    is_last_one = attr.ib(default=False)
    # 原始值
    raw_data = attr.ib(default=None)


class KLineDirection(BaseEnum):
    GOING_HIGH = 'GOING_HIGH'
    GOING_LOW = 'GOING_LOW'
    NO_CHANGE = 'NO_CHANGE'


class KLinePeriod(BaseEnum):
    """kline的时间类型

    暂不支持超过1小时的分钟, 比如 120min
    """
    MIN_1 = '1min'
    MIN_3 = '3min'
    MIN_5 = '5min'
    MIN_15 = '15min'
    MIN_30 = '30min'
    # MIN_60 = '60min'
    HOUR_1 = '1h'

    @classmethod
    def from_string(cls, val:str):
        """
        >>> f = KLinePeriod.from_string
        >>> f('1min')
        <KLinePeriod.MIN_1: '1min'>

        >>> f('1m')
        <KLinePeriod.MIN_1: '1min'>
        """
        val = re.sub(r'^(\d+)m$', '\\1min', val, flags=re.I)
        enum_map = {i.value.upper():i for i in cls}
        return enum_map.get(val.upper())

    @classmethod
    def auto_convert_timestamp(cls, timestamp, period:'KLinePeriod') -> datetime.datetime:
        """
        >>> cls = KLinePeriod
        >>> f = cls.auto_convert_timestamp

        >>> f(time.mktime(datetime.datetime(2021, 1, 25, 14, 29, 50).timetuple()), period=cls.MIN_1)
        datetime.datetime(2021, 1, 25, 14, 29)

        >>> f(time.mktime(datetime.datetime(2021, 7, 13, 21, 12, 0).timetuple()), period=cls.MIN_3)
        datetime.datetime(2021, 7, 13, 21, 12)

        >>> f(time.mktime(datetime.datetime(2021, 7, 13, 21, 14, 0).timetuple()), period=cls.MIN_3)
        datetime.datetime(2021, 7, 13, 21, 12)

        >>> f(time.mktime(datetime.datetime(2021, 7, 13, 21, 16, 20).timetuple()), period=cls.MIN_3)
        datetime.datetime(2021, 7, 13, 21, 15)

        >>> f(time.mktime(datetime.datetime(2021, 1, 25, 14, 29, 0).timetuple()), period=cls.MIN_5)
        datetime.datetime(2021, 1, 25, 14, 25)

        >>> f(time.mktime(datetime.datetime(2021, 1, 25, 14, 29, 0).timetuple()), period=cls.MIN_15)
        datetime.datetime(2021, 1, 25, 14, 15)

        >>> f(time.mktime(datetime.datetime(2021, 1, 25, 14, 9, 0).timetuple()), period=cls.HOUR_1)
        datetime.datetime(2021, 1, 25, 14, 0)
        """
        if period == cls.MIN_1:
            return convert_timestamp_to_minute_level(timestamp)

        date = datetime.datetime.fromtimestamp(timestamp)
        period_value = period.value

        pattern = re.compile(r'^(?P<min>\d+)m(in)?$', re.I)
        match_min = pattern.match(period_value)
        if match_min and int(match_min.group('min')) < 60:
            period_min = int(match_min.group('min'))
            new_minute = date.minute - date.minute % period_min
            return datetime.datetime(date.year, date.month, date.day, date.hour, new_minute)
        if match_min and int(match_min.group('min')) == 60:
            return datetime.datetime(date.year, date.month, date.day, date.hour)

        pattern = re.compile(r'^(?P<hour>\d+)h(our)?$', re.I)
        match_hour = pattern.match(period_value)
        if match_hour:
            period_hour = int(match_hour.group('hour'))
            new_hour = date.hour - date.minute % period_hour
            return datetime.datetime(date.year, date.month, date.day, new_hour)

    @classmethod
    def to_binance_value(cls, period:'KLinePeriod') -> str:
        """
        >>> cls = KLinePeriod
        >>> f = cls.to_binance_value
        >>> f(cls.MIN_1)
        '1m'

        >>> f(cls.MIN_15)
        '15m'

        >>> f(cls.HOUR_1)
        '1h'
        """
        patterns = [
            (re.compile(r'^(\d+)min$', re.I), lambda x:f'{x.group(1)}m'),
            (re.compile(r'^(\d+)hour$', re.I), lambda x:f'{x.group(1)}h'),
            (re.compile(r'^(\d+)h$', re.I), lambda x:f'{x.group(1)}h'),
        ]
        value = period.value
        for pattern, callback in patterns:
            match = pattern.match(value)
            if match:
                return callback(match)
        raise Exception(f'no binance period value for: {period}')


@attr.s
class OrderInExchange:
    """交易所的订单"""
    order_id:str = attr.ib(default=None)
    # 委托数量
    volume = attr.ib(factory=float)
    # 委托价格
    price = attr.ib(factory=float)
    # 杠杆倍数
    lever_rate = attr.ib(factory=int)
    # 成交数量
    trade_volume = attr.ib(factory=float)
    # 成交均价
    trade_avg_price = attr.ib(factory=float)
    # 成交总金额
    trade_turnover = attr.ib(factory=float)
    # 手续费
    fee = attr.ib(factory=float)
    # 订单状态	(1准备提交 2准备提交 3已提交 4部分成交 5部分成交已撤单 6全部成交 7已撤单 11撤单中)
    status = attr.ib(default=None)


class LoggerName(Enum):
    MAIN = 'MAIN'


@lru_cache()
def get_logger(name:LoggerName=LoggerName.MAIN):
    if name == LoggerName.MAIN:
        logger = loguru.logger
        log_file = path.join(settings.logs_dir, 'main.log')
        logger.add(log_file)
        return logger


def obscurity_coin(coin: str):
    """防止消息软件过滤，比如钉钉"""
    def get_random():
        char_count = random.randint(2, 3)
        return ''.join([i.lower() for i in random.sample(string.ascii_letters, char_count)])

    res = []
    for i in coin:
        res.append(get_random())
        res.append(i)
    res.append(get_random())
    return ''.join(res)


def convert_timestamp_to_minute_level(timestamp) -> datetime.datetime:
    """转换为分钟级的日期

    >>> f = convert_timestamp_to_minute_level
    >>> f(1606903624.335049)
    datetime.datetime(2020, 12, 2, 18, 7)
    """
    time_fmt = '%Y-%m-%d %H:%M'
    return datetime.datetime.strptime(datetime.datetime.fromtimestamp(timestamp).strftime(time_fmt), time_fmt)


def convert_timestamp_to_second_level(timestamp) -> float:
    """转换时间戳为以秒为单位

    Args:
        timestamp: 有时为 time.time() 整数，有时会 乘以 1000

    >>> f = convert_timestamp_to_second_level
    >>> f(1610678862.078273)
    1610678862.078273

    >>> f(1610678862078)
    1610678862.078
    """
    try:
        datetime.datetime.fromtimestamp(timestamp)
        return timestamp
    except:
        return timestamp/1000


def get_random_emoji():
    while True:
        emoji_and_words = random.choice(list(emoji.unicode_codes.UNICODE_EMOJI_ENGLISH.items()))
        if 'down' in emoji_and_words[1]:
            continue
        return emoji_and_words[0]


async def auto_retry(future_fn, infinite:bool=False, retry_count:int=5, sleep:int=2, retry_msg:str=None, logger=None):
    """自动重试"""
    logger = logger or get_logger()
    current_retry = 0
    last_exception = None
    while True:
        current_retry += 1
        if not infinite and current_retry > retry_count:
            break
        try:
            future = future_fn()
            return await future
        except Exception as e:
            last_exception = e
            retry_msg = retry_msg or 'retrying future'
            retry_msg = f'{retry_msg}.{e}\n{traceback.format_exc()}'
            logger.warning(retry_msg)
            await asyncio.sleep(sleep)
    raise last_exception


def human_time_delta(seconds:int) -> str:
    """
    >>> f = human_time_delta
    >>> f(10)
    '10s'
    """
    res = []
    if seconds >= 60*60*24:
        days = seconds // (60*60*24)
        seconds %= 60*60*24
        res.append(f'{days}d')

    if seconds >= 60*60:
        hours = seconds // (60*60)
        seconds %= 60*60
        res.append(f'{hours}h')

    if seconds >= 60:
        minutes = seconds // 60
        seconds %= 60
        res.append(f'{minutes}m')

    if seconds > 0:
        res.append(f'{seconds}s')
    return ''.join(res)


def readable_number(number:float, keep_count:int=3):
    """发送消息时，使 float 数字的小数位不至于过长

    >>> readable_number(1.000333)
    1.0

    >>> readable_number(1.001333)
    1.001

    >>> readable_number(0.000333)
    0.000333

    >>> readable_number(0.00000333666)  # str ==> 3.33666e-06
    3.34e-06
    """
    if number >= 1:
        return round(number, keep_count)
    match = re.search(r'^.+?e-(?P<exp>\d+)$', str(number))
    if match:
        ndigits = keep_count + int(match.group('exp')) -1
    else:
        ndigits = keep_count
        for i in str(number).split('.')[1]:
            if number == 0.00000333666:
                print(str(number).split('.')[1])
            if i != '0':
                break
            ndigits += 1
    return round(number, ndigits)


def exec_with_time_window(key, time_window:int, callback):
    """每隔 time_window 秒执行一次 callback
    """
    if not hasattr(exec_with_time_window, 'execute_time_cache'):
        setattr(exec_with_time_window, 'execute_time_cache', dict())
    last_execution_time = exec_with_time_window.execute_time_cache.get(key)
    now = time.time()

    if last_execution_time and now - last_execution_time < time_window:
        return

    exec_with_time_window.execute_time_cache[key] = now
    return callback()


def compare_with_tolerance(a:float, b:float, operator:str, tolerance_percent:float=0, base:float=None) -> bool:
    """
    >>> f = compare_with_tolerance
    >>> f(1, 2, '>')
    False

    >>> f(1, 2, '>', tolerance_percent=20)
    False

    >>> f(1, 2, '>', 50)
    True

    >>> f(1, 2, '>', 70)
    True
    """
    assert a > 0
    assert b > 0
    assert tolerance_percent >= 0
    if base:
        assert base == a or base == b
    base = base if base is not None else b

    operator_fns = {
        '>': lambda: a > b,
        '>=': lambda: a >= b,
        '==': lambda: a == b,
        '<': lambda: a < b,
        '<=': lambda: a <= b,
    }
    assert operator in operator_fns
    if operator_fns[operator]():
        return True
    if tolerance_percent <= 0:
        return False
    if 100*abs(a-b)/base <= tolerance_percent:
        return True
    return False
