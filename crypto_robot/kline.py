import asyncio
import datetime
import re
import time
import traceback
import uuid
from collections import deque
from functools import partial
from typing import Deque, List, Tuple, Union, Set

import attr
import numpy as np
import talib

from .common import (
    BaseCoin,
    BaseCoinSpot, Coin,
    BaseCoinSwap, CoinSwap,
    Tick, KLineDirection, KLinePeriod,
    get_logger,
    make_coin_enum_dynamicly_adding,
    convert_timestamp_to_minute_level,
    convert_timestamp_to_second_level,
)
from . import exchanges

logger = get_logger()


@attr.s
class MACD:
    dif: float = attr.ib(default=None)
    dea: float = attr.ib(default=None)
    hist: float = attr.ib(default=None)


@attr.s
class KLine:
    """K-Line"""
    open: float = attr.ib(default=None)
    close: float = attr.ib(default=None)
    high: float = attr.ib(default=None)
    low: float = attr.ib(default=None)
    vol: float = attr.ib(default=None)
    # k-line的时间
    period_date: datetime.datetime = attr.ib(default=None)

    # 此 kline 是否已到达最后一个. 对应币安的: "这根K线是否完结(是否已经开始下一根K线)"
    is_last_one: bool = attr.ib(default=bool)

    # 默认缓存 60 个 tick
    # tick_buffer: Deque[Tuple[datetime.datetime, Tick]] = attr.ib(factory=partial(deque, maxlen=60))

    # 最后更新时间
    last_update_datetime: datetime.datetime = attr.ib(default=None)
    period:str = KLinePeriod.MIN_1

    @property
    def direction(self) -> KLineDirection:
        """
        >>> obj = KLine()
        >>> obj.tick_price(price=10)
        >>> obj.tick_price(price=20)
        >>> obj.direction == KLineDirection.GOING_HIGH
        True
        """
        if self.open is None or self.close is None:
            return
        if self.open < self.close:
            return KLineDirection.GOING_HIGH
        if self.open == self.close:
            return KLineDirection.NO_CHANGE
        if self.open > self.close:
            return KLineDirection.GOING_LOW

    @property
    def direction_symbol(self) -> str:
        if self.direction == KLineDirection.GOING_HIGH:
            return '📈'
        elif self.direction == KLineDirection.NO_CHANGE:
            return '-'
        elif self.direction == KLineDirection.GOING_LOW:
            return '📉'

    @property
    def percent(self) -> float:
        """涨跌幅

        >>> KLine(open=1, close=2).percent
        100

        >>> KLine(open=3, close=1).percent
        -66.67
        """
        if self.open is None or self.close is None:
            return
        percent = 100*(self.close-self.open)/self.open
        # 保留 2 位小数
        percent = '{:.2f}'.format(percent)
        if re.search(r'\.0+$', percent):
            return int(float(percent))
        return float(percent)

    def auto_convert_timestamp(self, timestamp) -> datetime.datetime:
        """自动根据 kline 时间级别转换时间戳"""
        pass

    def tick_price(self, *, tick: Tick = None, price: float = None, now: int = None):
        """目前订阅的 realtime 为 1min 级别. open,close 等值只是 1min 的.

        >>> obj = KLine()
        >>> obj.tick_price(price=10)
        >>> obj.tick_price(price=20)
        >>> obj.tick_price(price=8)
        >>> obj.tick_price(price=15)
        >>> obj.tick_price(price=16)
        >>> obj.open, obj.close, obj.high, obj.low
        (10, 16, 20, 8)
        """
        if price is None and tick is None:
            return

        if tick is not None and tick.timestamp:
            now = tick.timestamp
        else:
            now = now or time.time()
        period_date = KLinePeriod.auto_convert_timestamp(timestamp=now, period=self.period)

        if self.period_date and self.period_date != period_date:
            logger.warning(f'period_date not equal: {self.period_date}≠{period_date}')
            return

        self.period_date = self.period_date or period_date
        self.last_update_datetime = datetime.datetime.now()

        if tick:
            self.open = self.open or tick.open
            self.close = tick.close
            self.high = tick.high
            self.low = tick.low
            self.vol = tick.vol

            self.is_last_one = tick.is_last_one

            # tick buffer
            # self.tick_buffer.append(tick)
        elif price:
            if self.open is None:
                self.open = price
            else:
                self.close = price
            self.high = max(self.high, price) if self.high is not None else price
            self.low = min(self.low, price) if self.low is not None else price

            # tick buffer
            # self.tick_buffer.append(Tick(timestamp=now, close=self.close))


@attr.s
class KLine1Min(KLine):
    period = KLinePeriod.MIN_1


@attr.s
class KLine3Min(KLine):
    period = KLinePeriod.MIN_3


@attr.s
class KLine5Min(KLine):
    period = KLinePeriod.MIN_5


@attr.s
class KLine15Min(KLine):
    period = KLinePeriod.MIN_15


@attr.s
class KLine30Min(KLine):
    period = KLinePeriod.MIN_30


@attr.s
class KLine1Hour(KLine):
    period = KLinePeriod.HOUR_1


class KLineQueue:
    """K-Line 队列"""
    def __init__(self, period:KLinePeriod=KLinePeriod.MIN_1, ma_list: List[int] = None, maxlen=60*24*30):
        """
        Args:
            kline_cls: KLine 类
            ma_list(moving average 移动平均线): 需要使用哪些移动平均线
            maxlen: 队列最大长度
        """
        self.period = period

        if period == KLinePeriod.MIN_1:
            kline_cls = KLine1Min
            buffer_maxlen = 60*1*5
        elif period == KLinePeriod.MIN_3:
            kline_cls = KLine3Min
            buffer_maxlen = 60*3*5
        elif period == KLinePeriod.MIN_5:
            kline_cls = KLine5Min
            buffer_maxlen = 60*5*5
        elif period == KLinePeriod.MIN_15:
            kline_cls = KLine15Min
            buffer_maxlen = 60*15*5
        elif period == KLinePeriod.MIN_30:
            kline_cls = KLine30Min
            buffer_maxlen = 60*30*5
        elif period == KLinePeriod.HOUR_1:
            kline_cls = KLine1Hour
            buffer_maxlen = 60*60*5
        else:
            raise Exception(f'not support period: {period}')
        self.kline_cls = kline_cls

        ma_list = list(map(int, ma_list or [20, 40, 60]))
        # 至少要有 20日线, 40日线, 60日线
        # self.ma_list = sorted(set(ma_list + [20, 40, 60]))
        self.ma_list = sorted(set(ma_list))

        # tick buffer
        self.tick_buffer: Deque[Tuple[datetime.datetime, Tick]] = deque(maxlen=buffer_maxlen)

        # right-in-left-out queue: <<<<<<<<<
        self.queue = deque(maxlen=maxlen)
        for ma in self.ma_list:
            setattr(self, f'ma_{ma}', deque(maxlen=maxlen))
            # 使用开仓价. 做空时使用
            # 反转 ma. reverse ma
            setattr(self, f'ma_r_{ma}', deque(maxlen=maxlen))

        # macd
        self.macd_fastperiod = 20
        self.macd_slowperiod = 40
        self.macd_signalperiod = 15
        self.macd: Deque[MACD] = deque(maxlen=maxlen)

    def clear(self):
        self.queue.clear()
        self.tick_buffer.clear()

    def tick(self, tick:Tick):
        """
        >>> obj = KLineQueue(period=KLinePeriod.MIN_1)
        >>> obj.tick(tick=Tick(timestamp=time.mktime(datetime.datetime(2021, 1, 25, 15, 43, 1).timetuple()), close=5))
        >>> obj.tick(tick=Tick(timestamp=time.mktime(datetime.datetime(2021, 1, 25, 15, 43, 10).timetuple()), close=9))
        >>> obj.tick(tick=Tick(timestamp=time.mktime(datetime.datetime(2021, 1, 25, 15, 50, 30).timetuple()), close=20))
        >>> len(obj.queue)
        2

        >>> len(obj.tick_buffer)
        3
        """
        new_created_kline = False
        if self.queue:
            last_period_date = self.queue[-1].period_date
        else:
            last_period_date = None
        if not self.queue or KLinePeriod.auto_convert_timestamp(tick.timestamp, period=self.period) > last_period_date:
            new_created_kline = True
            kline = self.kline_cls()
            kline.tick_price(tick=tick)
            self.queue.append(kline)
        elif KLinePeriod.auto_convert_timestamp(tick.timestamp, period=self.period) == last_period_date:
            self.queue[-1].tick_price(tick=tick)
        else:
            logger.warning(f"error tick timestamp:{datetime.datetime.fromtimestamp(tick.timestamp)}:{KLinePeriod.auto_convert_timestamp(tick.timestamp, period=self.period)} < {last_period_date}. is_last_one:{tick.is_last_one}. last_one:{self.queue[-1]}")
            return

        # tick buffer
        self.tick_buffer.append(tick)

        # moving average
        for ma in self.ma_list:
            self._update_ma(ma=ma, new_created_kline=new_created_kline)

        # macd
        self._update_macd(new_created_kline=new_created_kline)

    def seconds_fitting_condition(self, fn) -> int:
        """满足条件的价格持续的秒数. 时间不宜超过 tick_buffer 中 maxlen 的时间

        >>> obj = KLineQueue()
        >>> obj.tick(tick=Tick(timestamp=time.mktime(datetime.datetime(2021, 1, 25, 15, 43, 1).timetuple()), close=5))
        >>> obj.tick(tick=Tick(timestamp=time.mktime(datetime.datetime(2021, 1, 25, 15, 43, 10).timetuple()), close=9))
        >>> obj.tick(tick=Tick(timestamp=time.mktime(datetime.datetime(2021, 1, 25, 15, 43, 30).timetuple()), close=20))
        >>> obj.seconds_fitting_condition(lambda x:x<=20)
        29

        >>> obj.seconds_fitting_condition(lambda x:x>30)
        0
        """
        if self.tick_buffer.maxlen:
            index_range = range(-1, -self.tick_buffer.maxlen-1, -1)
        else:
            index_range = range(-1, -60, -1)
        start_datetime = None
        end_datetime = None
        for i in index_range:
            try:
                tick = self.tick_buffer[i]
                if not fn(tick.close):
                    break
                date = datetime.datetime.fromtimestamp(convert_timestamp_to_second_level(tick.timestamp))
                if i == -1:
                    end_datetime = date
                else:
                    start_datetime = date
            except IndexError:
                break
        if not start_datetime or not end_datetime:
            return 0
        timedelta = end_datetime - start_datetime
        return timedelta.seconds

    def seconds_greater_than_open(self) -> int:
        """最后一个kline价格大于开盘价的时长

        >>> obj = KLineQueue()
        >>> obj.tick(tick=Tick(timestamp=time.mktime(datetime.datetime(2021, 1, 25, 15, 43, 1).timetuple()), open=5, close=5))
        >>> obj.tick(tick=Tick(timestamp=time.mktime(datetime.datetime(2021, 1, 25, 15, 43, 10).timetuple()), open=5, close=9))
        >>> obj.tick(tick=Tick(timestamp=time.mktime(datetime.datetime(2021, 1, 25, 15, 43, 30).timetuple()), open=5, close=20))
        >>> obj.seconds_greater_than_open()
        20

        >>> obj.tick(tick=Tick(timestamp=time.mktime(datetime.datetime(2021, 1, 25, 15, 43, 30).timetuple()), open=5, close=3))
        >>> obj.seconds_greater_than_open()
        0

        >>> obj = KLineQueue(period=KLinePeriod.MIN_5)
        >>> obj.tick(tick=Tick(timestamp=time.mktime(datetime.datetime(2021, 1, 25, 15, 43, 1).timetuple()), open=5, close=5))
        >>> obj.tick(tick=Tick(timestamp=time.mktime(datetime.datetime(2021, 1, 25, 15, 43, 10).timetuple()), open=5, close=9))
        >>> obj.tick(tick=Tick(timestamp=time.mktime(datetime.datetime(2021, 1, 25, 15, 45, 30).timetuple()), open=6, close=20))
        >>> obj.seconds_greater_than_open()
        30
        """
        return self._seconds_greater_or_less_than_open('>')

    def seconds_less_than_open(self) -> int:
        """最后一个kline价格小于开盘价的时长

        >>> obj = KLineQueue()
        >>> obj.tick(tick=Tick(timestamp=time.mktime(datetime.datetime(2021, 1, 25, 15, 43, 1).timetuple()), open=5, close=3))
        >>> obj.tick(tick=Tick(timestamp=time.mktime(datetime.datetime(2021, 1, 25, 15, 43, 10).timetuple()), open=5, close=4))
        >>> obj.tick(tick=Tick(timestamp=time.mktime(datetime.datetime(2021, 1, 25, 15, 43, 30).timetuple()), open=5, close=4))
        >>> obj.seconds_less_than_open()
        29
        """
        return self._seconds_greater_or_less_than_open('<')

    def _seconds_greater_or_less_than_open(self, condition:str) -> int:
        """最后一个kline价格小于开盘价的时长"""
        assert condition in {'>', '<'}

        open_price = self.queue[-1].open
        last_period_date = self.queue[-1].period_date
        index = -1
        start_datetime = None
        end_datetime = None
        while True:
            try:
                tick = self.tick_buffer[index]
            except IndexError:
                break
            current_period = KLinePeriod.auto_convert_timestamp(tick.timestamp, period=self.period)
            current_date = datetime.datetime.fromtimestamp(convert_timestamp_to_second_level(tick.timestamp))
            if current_period != last_period_date:
                break
            if condition == '>' and tick.close <= open_price:
                break
            if condition == '<' and tick.close >= open_price:
                break
            if index == -1:
                end_datetime = current_date
            else:
                start_datetime = current_date
            index -= 1
        if not start_datetime and not end_datetime:
            return 0
        assert end_datetime
        if not start_datetime and end_datetime:
            timedelta = end_datetime - last_period_date
        else:
            timedelta = end_datetime - start_datetime
        return timedelta.seconds

    # @property
    # def auto_last_kline(self):
    #     """视情况返回不同的最后一个kline"""
    #     last = self.queue[-1]
    #     if last.period == KLinePeriod.MIN_1:
    #         second = last.last_update_datetime.second
    #         # 如果不是最后10秒, 返回倒数第二个
    #         if second <= 50:
    #             last = self.queue[-2]
    #     else:
    #         raise Exception(f'not support period yet! period: {last.period}')
    #     return last

    def ma(self, ma:int):
        return getattr(self, f'ma_{ma}')

    def ma_r(self, ma:int):
        return getattr(self, f'ma_r_{ma}')

    def get_ma_cross_point_count(self, back_search_kline_count:int, ma_list:List[int]) -> int:
        """获取 ma 交叉点的个数

        Args:
            back_search_kline_count: 向前找几个 kline. 也即向前找多少时间
            ma_list: 需要获取哪些 ma 的交点

        In [658]: df = pd.DataFrame([[1],[2],[3],[4],[5],[6],[7],[8],[9],[10],[-50]])
        In [659]: df['ma5'] = df[0].rolling(window=5).mean()
        In [660]: df['ma9'] = df[0].rolling(window=9).mean()
        In [661]: df
        Out[661]:
            0  ma5       ma9
        0    1  NaN       NaN
        1    2  NaN       NaN
        2    3  NaN       NaN
        3    4  NaN       NaN
        4    5  3.0       NaN
        5    6  4.0       NaN
        6    7  5.0       NaN
        7    8  6.0       NaN
        8    9  7.0  5.000000
        9   10  8.0  6.000000
        10 -50 -3.2  0.222222

        >>> obj = KLineQueue(ma_list=[5, 9])
        >>> obj.tick(tick=Tick(timestamp=time.mktime(datetime.datetime(2021, 1, 25, 18, 54).timetuple()), close=1))
        >>> obj.tick(tick=Tick(timestamp=time.mktime(datetime.datetime(2021, 1, 25, 18, 55).timetuple()), close=2))
        >>> obj.tick(tick=Tick(timestamp=time.mktime(datetime.datetime(2021, 1, 25, 18, 56).timetuple()), close=3))
        >>> obj.tick(tick=Tick(timestamp=time.mktime(datetime.datetime(2021, 1, 25, 18, 57).timetuple()), close=4))
        >>> obj.tick(tick=Tick(timestamp=time.mktime(datetime.datetime(2021, 1, 25, 18, 58).timetuple()), close=5))
        >>> obj.tick(tick=Tick(timestamp=time.mktime(datetime.datetime(2021, 1, 25, 18, 59).timetuple()), close=6))
        >>> obj.tick(tick=Tick(timestamp=time.mktime(datetime.datetime(2021, 1, 25, 19, 0).timetuple()), close=7))
        >>> obj.tick(tick=Tick(timestamp=time.mktime(datetime.datetime(2021, 1, 25, 19, 1).timetuple()), close=8))
        >>> obj.tick(tick=Tick(timestamp=time.mktime(datetime.datetime(2021, 1, 25, 19, 2).timetuple()), close=9))
        >>> obj.tick(tick=Tick(timestamp=time.mktime(datetime.datetime(2021, 1, 25, 19, 3).timetuple()), close=10))
        >>> obj.tick(tick=Tick(timestamp=time.mktime(datetime.datetime(2021, 1, 25, 19, 4).timetuple()), close=-50))
        >>> obj.get_ma_cross_point_count(back_search_kline_count=2, ma_list=[5,9])
        1

        >>> obj.get_ma_cross_point_count(back_search_kline_count=3, ma_list=[5,9])
        1

        >>> obj.get_ma_cross_point_count(back_search_kline_count=4, ma_list=[5,9])
        1
        """
        ma_list = set(ma_list)
        for ma in ma_list:
            assert hasattr(self, f'ma_{ma}')

        cross_point_set = set()
        index_range = zip(range(-back_search_kline_count, -1), range(-back_search_kline_count+1, 0))
        for ma_1 in ma_list:
            for ma_2 in ma_list - {ma_1}:
                for start, end in index_range:
                    try:
                        self.ma(ma_1)[start]
                        self.ma(ma_2)[start]
                    except IndexError:
                        break
                    # 多个 ma 交于一点时计算多次
                    key = '-'.join(sorted([str(ma_1), str(ma_2)]))
                    a = self.ma(ma_1)[start] - self.ma(ma_2)[start]
                    b = self.ma(ma_1)[end] - self.ma(ma_2)[end]
                    # 重合
                    if a == 0 and b == 0:
                        continue
                    # 交于起点
                    if a == 0:
                        val = '{}:{}'.format(key, self.ma(ma_1)[start])
                        cross_point_set.add(val)
                        continue
                    # 交于终点
                    if b == 0:
                        val = '{}:{}'.format(key, self.ma(ma_1)[end])
                        cross_point_set.add(val)
                        continue
                    # 交叉于中间
                    if a*b < 0:
                        # 随机值
                        val = '{}:{}'.format(key, uuid.uuid4())
                        cross_point_set.add(val)
        return len(cross_point_set)

    def has_ma_crossed(self, ma1:int, ma2:int, start_index:int, end_index:int=-1) -> bool:
        """检查两条 ma 是否交叉

        粗略版本
        """
        for ma in [ma1, ma2]:
            assert hasattr(self, f'ma_{ma}')
        ma1_start_value = self.ma(ma1)[start_index]
        ma1_end_value = self.ma(ma1)[end_index]
        ma2_start_value = self.ma(ma2)[start_index]
        ma1_end_value = self.ma(ma2)[end_index]

        a = self.ma(ma1)[start_index] - self.ma(ma2)[start_index]
        b = self.ma(ma1)[end_index] - self.ma(ma2)[end_index]
        # 重合
        if a == 0 and b == 0:
            return False
        # 交于起点
        if a == 0:
            return True
        # 交于终点
        if b == 0:
            return True
        # 交叉于中间
        if a*b < 0:
            return True
        return False

    def get_ma_crossed_by_kline(self, start_index:int, end_index:int=-1, ma_list:List[int]=None) -> Set[int]:
        """获取与指定 kline 相交的均线

        :param start_index: kline 的起始位置
        :param end_index: kline 的结束位置, 包括此值
        :param ma_list: 测试哪些均线
        """
        assert start_index < end_index
        ma_list = ma_list or self.ma_list
        crossed_ma = set()

        def get_crossed_ma(index:int, val1, val2):
            res = set()
            for ma in ma_list:
                if min(val1, val2) <= self.ma(ma)[index] <= max(val1, val2):
                    res.add(ma)
            return res

        for i in range(start_index, end_index+1):
            crossed_ma = crossed_ma.union(get_crossed_ma(index=i, val1=self.queue[i].open, val2=self.queue[i].close))
            # 当前 kline 与下一 kline 之间的空档
            if i == end_index:
                continue
            current_kline_max = max(self.queue[i].open, self.queue[i].close)
            current_kline_min = min(self.queue[i].open, self.queue[i].close)
            next_kline_max = max(self.queue[i+1].open, self.queue[i+1].close)
            next_kline_min = min(self.queue[i+1].open, self.queue[i+1].close)

            if current_kline_max < next_kline_min:
                val1 = current_kline_max
                val2 = next_kline_min
            elif current_kline_min > next_kline_max:
                val1 = current_kline_min
                val2 = next_kline_max
            else:
                continue
            crossed_ma = crossed_ma.union(get_crossed_ma(index=i, val1=val1, val2=val2))
        return crossed_ma

    def _update_ma(self, ma:int, new_created_kline:bool):
        """更新移动平均线"""
        if len(self.queue) < ma:
            return

        ma_queue = self.ma(ma)
        new_ma_value = sum([self.queue[i].close for i in range(-ma, 0)])/ma
        if new_created_kline:
            ma_queue.append(new_ma_value)
        else:
            ma_queue[-1] = new_ma_value

        ma_r_queue = self.ma_r(ma)
        new_ma_r_value = sum([self.queue[i].open for i in range(-ma, 0)])/ma
        if new_created_kline:
            ma_r_queue.append(new_ma_r_value)
        else:
            ma_r_queue[-1] = new_ma_r_value

    def _update_macd(self, new_created_kline:bool):
        """更新MACD"""
        check_price_count = max(self.macd_fastperiod, self.macd_slowperiod)
        check_price_count = round(check_price_count * 2)
        if len(self.queue) < check_price_count:
            return

        prices = np.array([self.queue[i].close for i in range(-check_price_count, 0)], dtype=float)
        # new_macd = talib.MACD(prices, fastperiod=12, slowperiod=26, signalperiod=9)
        # output: (numpy.ndarray, numpy.ndarray, numpy.ndarray)
        dif, dea, hist = talib.MACD(prices,
                                    fastperiod=self.macd_fastperiod,
                                    slowperiod=self.macd_slowperiod,
                                    signalperiod=self.macd_signalperiod)
        new_macd = MACD(dif=dif[-1], dea=dea[-1], hist=hist[-1])
        if any([np.isnan(i) for i in [dif[-1], dea[-1], hist[-1]]]):
            return
        macd_queue = self.macd
        if new_created_kline:
            macd_queue.append(new_macd)
        else:
            macd_queue[-1] = new_macd


class KLineQueueContainer:
    def __init__(self, coin:BaseCoin, periods:List[KLinePeriod]):
        assert isinstance(coin, BaseCoin)
        self.coin = coin
        self.periods = periods
        self.kline_queue_dict = {period:KLineQueue(period=period) for period in periods}

        if isinstance(coin, BaseCoinSpot):
            # self.coin_api = exchanges.HuobiSpot(coin=coin)
            self.coin_api = exchanges.BinanceSpot(coin=coin)
        elif isinstance(coin, BaseCoinSwap):
            # self.coin_api = exchanges.HuobiUsdtSwap(coin=coin)
            self.coin_api = exchanges.BinanceUsdtSwap(coin=coin)
        else:
            raise Exception(f'unknown coin:{coin}. type:{type(coin)}')

        self.called_history:bool = False

    @property
    def current_period(self):
        if len(self.periods) == 1:
            return self.periods[0]

    @property
    def current_price(self):
        kline_queue = self.get_by_period(self.periods[0])
        if kline_queue.queue:
            return kline_queue.queue[-1].close

    async def tick_history(self):
        """初始化历史数据"""
        if self.called_history:
            return

        try:
            for period in self.periods:
                history = await self.coin_api.get_history(period=period)
                for tick in history:
                    self.tick(tick, period=period)
            self.called_history = True
        except Exception as e:
            # 清空已获取的历史数据
            for period in self.periods:
                self.get_by_period(period).clear()
            raise e

    # async def tick_realtime(self):
    #     """实时交易数据"""
    #     async def loop(period):
    #         async for _ in self.tick_realtime_for_period(period):
    #             pass

    #     for period in self.periods[:-1]:
    #         asyncio.gather(loop(period))

    #     # 使用最后一个 period 作为实时价格提醒
    #     async for tick in self.tick_realtime_for_period(self.periods[-1], yield_tick=True):
    #         yield tick

    # async def tick_realtime_for_period(self, period:KLinePeriod, yield_tick:bool=False):
    #     kline_queue = self.get_by_period(period)
    #     async for tick in self.coin_api.realtime(period=period):
    #         if not isinstance(tick, Tick):
    #             continue
    #         kline_queue.tick(tick)
    #         if yield_tick:
    #             yield tick

    def tick(self, tick:Tick, period:KLinePeriod=None):
        if period:
            periods = [period]
        else:
            periods = self.periods
        for period in periods:
            kline_queue = self.get_by_period(period)
            kline_queue.tick(tick)

    def get_by_period(self, period:KLinePeriod) -> KLineQueue:
        return self.kline_queue_dict.get(period)

    def __getattr__(self, name):
        """
        >>> queue = KLineQueueContainer(coin=Coin.BTC, periods=[KLinePeriod.MIN_15])
        >>> queue.ma_list
        [20, 40, 60]
        """
        if not self.current_period:
            raise Exception(f'must set current_period while calling {name}')
        return getattr(self.get_by_period(self.current_period), name)
