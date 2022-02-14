import datetime
import math
from decimal import Decimal
from functools import total_ordering
from typing import Any, Dict, List, Optional, Tuple

from .common import (
    compare_with_tolerance,
    convert_timestamp_to_second_level,
    human_time_delta,
    readable_number,
    KLineDirection,
    KLinePeriod,
    LongOrShort,
)
from .kline import KLine, KLineQueue, KLineQueueContainer
from .trader import Trader
from .scorer import Scorer
from .stop_loss import StopLoss


class BaseStrategy:
    nickname = None

    def __init__(self,
                 kline_queue_container:KLineQueueContainer,
                 default_period:KLinePeriod,
                 check_direction_of_shorter_period:KLinePeriod=None,
                 shorter_period_continuous_count:int=None,
                 check_cross_ma_by_bigger_period:KLinePeriod=None,
                 trader:Trader=None,
                 stop_loss:StopLoss=None):
        """
        Args:
            check_direction_of_shorter_period: 检查更小粒度的 period
            shorter_period_continuous_count: 检查更小力度的 period 时至少需要连续几个符合方向
        """
        self.kline_queue_container = kline_queue_container
        self.default_period = default_period
        self.check_direction_of_shorter_period = check_direction_of_shorter_period
        self.shorter_period_continuous_count = shorter_period_continuous_count if shorter_period_continuous_count is not None else 1
        self.check_cross_ma_by_bigger_period = check_cross_ma_by_bigger_period
        self.trader = trader
        self.stop_loss = stop_loss
        # 开仓的原因描述
        self.desc = None
        self.score = None

        # 未开仓的原因
        self.desc_if_not_open = None
        self.desc_if_not_open_long = None
        self.desc_if_not_open_short = None

        # 未平仓的原因
        self.desc_if_not_close = None

    @classmethod
    def format_init_kwargs(cls, **kwargs:Dict[str, Any]) -> Dict[str, Any]:
        """
        >>> f = BaseStrategy.format_init_kwargs
        >>> f(default_period='3min', check_direction_of_shorter_period='5min')
        {'default_period': <KLinePeriod.MIN_3: '3min'>, 'check_direction_of_shorter_period': <KLinePeriod.MIN_5: '5min'>}
        """
        res = dict()
        for k, v in kwargs.items():
            if k in {'default_period', 'check_direction_of_shorter_period', 'check_cross_ma_by_bigger_period'}:
                v = KLinePeriod.from_string(v)
            # else:
            #     raise Exception(f'unsupport format_init_kwargs: {k}')
            res[k] = v
        return res

    @classmethod
    def get_strategy_cls_by_name(cls, cls_name:str):
        res_cls = globals().get(cls_name)
        assert res_cls
        return res_cls

    def should_open(self) -> bool:
        return self.should_open_long()

    def should_open_long(self) -> bool:
        raise NotImplementedError

    def should_open_short(self) -> bool:
        raise NotImplementedError

    def should_close(self) -> bool:
        return self.should_close_long()

    def should_close_long(self) -> bool:
        raise NotImplementedError

    def should_close_short(self) -> bool:
        raise NotImplementedError

    @classmethod
    def get_overlap(cls, a_min, a_max, b_min, b_max):
        """
        >>> f = BaseStrategy.get_overlap
        >>> f(1, 3, 4, 5)
        0

        >>> f(1, 3, 3, 5)
        0

        >>> f(1, 5, 4, 4.5)
        0.5

        >>> f(1, 5, 4, 7)
        1

        >>> f(5, 10, 3, 8)
        3
        """
        if a_min > b_max or b_min > a_max:
            return 0
        overlap = 0
        if a_min <= b_min:
            overlap = min(a_max - b_min, b_max - b_min)
        else:
            overlap = min(a_max - a_min, b_max - a_min)
        return max(overlap, 0)

    def get_shorter_period_count(self, minute:int) -> int:
        """
        获取基于更大 period 的更小粒度的 kline 的数量
        """
        shorter = self.check_direction_of_shorter_period
        longer = self.default_period
        if longer == KLinePeriod.MIN_5 and shorter == KLinePeriod.MIN_1:
            return minute % 5
        if longer == KLinePeriod.MIN_3 and shorter == KLinePeriod.MIN_1:
            return minute % 3
        if longer == KLinePeriod.MIN_15 and shorter == KLinePeriod.MIN_5:
            return minute % 15 // 5
        if longer == KLinePeriod.MIN_15 and shorter == KLinePeriod.MIN_3:
            # very important! treat min3 as min5
            return minute % 15 // 3
        if longer == KLinePeriod.MIN_30 and shorter == KLinePeriod.MIN_3:
            return minute % 30 // 3
        if longer == KLinePeriod.MIN_30 and shorter == KLinePeriod.MIN_5:
            return minute % 30 // 5
        if longer == KLinePeriod.HOUR_1 and shorter == KLinePeriod.MIN_5:
            return minute % 60 // 5
        if shorter:
            raise Exception(f"unsuport periods: {self.default_period}, {self.check_direction_of_shorter_period}")


class FiveStepV2(BaseStrategy):
    """5 步策略
    """
    nickname = "👋"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        # 测试是否支持 period 组合
        self.get_shorter_period_count(1)

        if self.default_period == KLinePeriod.MIN_3:
            self.PERIOD_MODULO = 3
        elif self.default_period == KLinePeriod.MIN_5:
            self.PERIOD_MODULO = 5
        elif self.default_period == KLinePeriod.MIN_15:
            self.PERIOD_MODULO = 15

        raise DeprecationWarning("暂时不用这个class了")

    def should_open_long(self) -> bool:
        """开仓做多
        """
        res = self._check_should_open(long_or_short=LongOrShort.LONG)
        self.desc_if_not_open_long = self.desc_if_not_open
        return res

    def should_open_short(self) -> bool:
        """开仓做空"""
        res = self._check_should_open(long_or_short=LongOrShort.SHORT)
        self.desc_if_not_open_short = self.desc_if_not_open
        return res

    def _check_should_open(self, long_or_short:LongOrShort) -> bool:
        """
        • min5 当前的需要是涨/跌
        • min5 前5个的规则:
            - 倒数第5,1个必须是涨/跌;
            - 倒数第 5 个必须是涨/跌;
            - 至少 4 个是涨/跌;
            - 其中的 4 或 5 个价格递增/递减;
            - 【暂时忽略】如果有 1 个不是涨/跌，则不能大于多少百分比;
            - 当前价格与倒数第1个的最少涨/跌百分比;
        • min1 连续2个涨/跌. 都需要 is_last_one
        """
        # 首先重置状态
        self.desc = None
        self.desc_if_not_open = None

        kline_queue = self.kline_queue_container.get_by_period(self.default_period)
        assert kline_queue is not None

        if len(kline_queue.queue) < 12:
            return False

        # ================================ 最后一个 KLine ================================ #

        # 做多时：最后一个必须是涨
        # 做空时：最后一个必须是跌
        if long_or_short == LongOrShort.LONG:
            if kline_queue.queue[-1].direction != KLineDirection.GOING_HIGH:
                self.desc_if_not_open = '最后一个不是涨'
                return False
        else:
            if kline_queue.queue[-1].direction != KLineDirection.GOING_LOW:
                self.desc_if_not_open = '最后一个不是跌'
                return False

        # ================================ 前 5 个 KLine: 索引 -6~-2 ================================ #

        # 做多时：倒数第5个必须是涨
        # 做空时：倒数第5个必须是跌
        desc_template = '倒数第6个不是涨/跌'
        if long_or_short == LongOrShort.LONG:
            self.desc_if_not_open = desc_template
            if kline_queue.queue[-6].direction != KLineDirection.GOING_HIGH:
                return False
        else:
            self.desc_if_not_open = desc_template
            if kline_queue.queue[-6].direction != KLineDirection.GOING_LOW:
                return False

        desc_template = '倒数第2个不是涨/跌'
        if long_or_short == LongOrShort.LONG:
            self.desc_if_not_open = desc_template
            if kline_queue.queue[-2].direction != KLineDirection.GOING_HIGH:
                return False
        else:
            self.desc_if_not_open = desc_template
            if kline_queue.queue[-2].direction != KLineDirection.GOING_LOW:
                return False

        # 5 条 Kline 的红绿的数量
        min_expect_count = 4
        directions = [kline_queue.queue[i].direction for i in range(-6, -1)]
        if long_or_short == LongOrShort.LONG:
            satisfied_direction = directions.count(KLineDirection.GOING_HIGH)
        else:
            satisfied_direction = directions.count(KLineDirection.GOING_LOW)
        if satisfied_direction < min_expect_count:
            self.desc_if_not_open = f"红绿数量不符合. {satisfied_direction}<{min_expect_count}"
            return False

        # 逐步升高/降低
        candidates = [kline_queue.queue[i] for i in range(-6, -1)]
        long_conditions = [
            (-1, lambda x: x.close > max(candidates[-5].open, candidates[-5].close)),
            (-1, lambda x: x.close > max(candidates[-4].open, candidates[-4].close)),
            # (-1, lambda x: x.close > max(candidates[-3].open, candidates[-3].close)),
            # (-1, lambda x: x.close > max(candidates[-2].open, candidates[-2].close)),

            (-2, lambda x: x.close > max(candidates[-5].open, candidates[-5].close)),
            # (-2, lambda x: x.close > max(candidates[-4].open, candidates[-4].close)),

            # (-3, lambda x: max(x.open, x.close) > max(candidates[-5].open, candidates[-5].close)),
        ]
        short_conditions = [
            (-1, lambda x: x.close < min(candidates[-5].open, candidates[-5].close)),
            (-1, lambda x: x.close < min(candidates[-4].open, candidates[-4].close)),
            # (-1, lambda x: x.close < min(candidates[-3].open, candidates[-3].close)),
            # (-1, lambda x: x.close < min(candidates[-2].open, candidates[-2].close)),

            (-2, lambda x: x.close < min(candidates[-5].open, candidates[-5].close)),
            # (-2, lambda x: x.close < min(candidates[-4].open, candidates[-4].close)),

            # (-3, lambda x: min(x.open, x.close) < min(candidates[-5].open, candidates[-5].close)),
        ]
        if long_or_short == LongOrShort.LONG:
            conditions = long_conditions
        else:
            conditions = short_conditions
        for compare_idx, fn in conditions:
            if not fn(candidates[compare_idx]):
                self.desc_if_not_open = f"{compare_idx}的价格高低不符合"
                return False

        # 阶梯价格
        step_prices = []
        max_tolerant_step_percent = 0.3
        for kline in candidates:
            if long_or_short == LongOrShort.LONG and kline.direction == KLineDirection.GOING_HIGH:
                # step_prices.append(kline.close)
                step_prices.append(max(kline.open, kline.close))
            elif long_or_short == LongOrShort.SHORT and kline.direction == KLineDirection.GOING_LOW:
                # step_prices.append(kline.close)
                step_prices.append(min(kline.open, kline.close))
        assert step_prices
        # 价格相差很少则忽略
        filtered_step_prices = []
        for i in step_prices:
            if not filtered_step_prices:
                filtered_step_prices.append(i)
                continue
            # 与上一个比较
            last_price = filtered_step_prices[-1]
            # 相差小于%: max_tolerant_step_percent
            if (abs(i - last_price)/last_price)*100 <= max_tolerant_step_percent:
                continue
            filtered_step_prices.append(i)
        tmp_desc_if_not_open = None
        if long_or_short == LongOrShort.LONG:
            compare_sorted = sorted(filtered_step_prices, reverse=False)
            tmp_desc_if_not_open = f"close价格不是递增. {filtered_step_prices}"
        else:
            compare_sorted = sorted(filtered_step_prices, reverse=True)
            tmp_desc_if_not_open = f"close价格不是递减. {filtered_step_prices}"
        if filtered_step_prices != compare_sorted:
            self.desc_if_not_open = tmp_desc_if_not_open
            return False

        # ================================ 忽略价格震荡的情况 ================================ #

        previous_range = [kline_queue.queue[i] for i in range(-11, -6)]
        previous_min = min([min(i.open, i.close) for i in previous_range])
        previous_max = max([max(i.open, i.close) for i in previous_range])
        current_range = [kline_queue.queue[i] for i in range(-6, -1)]
        current_min = min([min(i.open, i.close) for i in current_range])
        current_max = max([max(i.open, i.close) for i in current_range])
        # 允许的最大重叠百分比
        max_overlap_percent = 90
        overlap = self.get_overlap(previous_min, previous_max, current_min, current_max)
        overlap_percent1 = round(100 * overlap / abs(previous_max - previous_min), 2)
        overlap_percent2 = round(100 * overlap / abs(current_max - current_min), 2)
        if overlap_percent1 > max_overlap_percent and overlap_percent2 > max_overlap_percent:
            self.desc_if_not_open = f"监测到震荡(最大重叠:{max_overlap_percent}%): {overlap_percent1}%, {overlap_percent2}%"
            return False

        # ================================ 更小 period 的 direction ================================ #

        # 如果当前 min5 是最后一个则不检查更小的 period
        kline_closed = kline_queue.queue[-1].is_last_one

        # 做多时：最后一个必须是涨
        # 做空时：最后一个必须是跌
        if not kline_closed and self.check_direction_of_shorter_period:
            # 至少需要过去 2min
            shorter_kline_queue = self.kline_queue_container.get_by_period(self.check_direction_of_shorter_period)
            if self.get_shorter_period_count(shorter_kline_queue.queue[-1].period_date.minute) <= 0:
                self.desc_if_not_open = f"shorter period {self.check_direction_of_shorter_period.value}数量不足"
                return False

            if not shorter_kline_queue.queue[-1].is_last_one:
                self.desc_if_not_open = f"shorter period {self.check_direction_of_shorter_period.value}最后一个还未结束"
                return False

            desc = f'shorter period {self.check_direction_of_shorter_period.value}最后2个方向不符合'
            current_directions = [shorter_kline_queue.queue[i].direction for i in range(-2, 0)]
            if long_or_short == LongOrShort.LONG:
                expect_directions = [KLineDirection.GOING_HIGH] * 2
            else:
                expect_directions = [KLineDirection.GOING_LOW] * 2
            if set(current_directions) != set(expect_directions):
                self.desc_if_not_open = desc
                return False

        # ================================ 当前价格与倒数第 6 个涨跌百分比 ================================ #

        min_diff_percent = 0.2
        current_price = kline_queue.queue[-1].close
        price2 = kline_queue.queue[-6].close
        percent = 100 * (current_price - price2) / price2
        desc_template = "当前价格与第一个kline涨跌百分比不符(min_diff_percent%): {}%"
        if long_or_short == LongOrShort.LONG:
            if percent < min_diff_percent:
                self.desc_if_not_open = desc_template.format('{:.3f}'.format(percent))
                return False
        else:
            if percent > -min_diff_percent:
                self.desc_if_not_open = desc_template.format('{:.3f}'.format(percent))
                return False

        # ================================ Done ================================ #

        scorer = Scorer(kline_queue, start_index=-6, end_index=-1)
        self.score = scorer.get_score()

        self.desc_if_not_open = None
        # 开仓原因描述
        desc_list = [
            '{}{}%'.format(
                kline_queue.queue[-6].direction_symbol,
                kline_queue.queue[-6].percent,
            ),
            '{}{}%'.format(
                kline_queue.queue[-5].direction_symbol,
                kline_queue.queue[-5].percent,
            ),
            '{}{}%'.format(
                kline_queue.queue[-4].direction_symbol,
                kline_queue.queue[-4].percent,
            ),
            '{}{}%'.format(
                kline_queue.queue[-3].direction_symbol,
                kline_queue.queue[-3].percent,
            ),
            '{}{}%'.format(
                kline_queue.queue[-2].direction_symbol,
                kline_queue.queue[-2].percent,
            ),
            '{}{}%,{}'.format(
                kline_queue.queue[-1].direction_symbol,
                kline_queue.queue[-1].percent,
                kline_queue.queue[-1].close,
            ),
        ]
        self.desc = ' | '.join(desc_list)
        return True

    def should_close_long(self, open_time:datetime.datetime=None) -> bool:
        """做多平仓"""
        return self._check_should_close(long_or_short=LongOrShort.LONG, open_time=open_time)

    def should_close_short(self, open_time:datetime.datetime=None) -> bool:
        """做空平仓"""
        return self._check_should_close(long_or_short=LongOrShort.SHORT, open_time=open_time)

    def _check_should_close(self, long_or_short:LongOrShort, open_time:datetime.datetime=None) -> bool:
        """
        • min5 当前的kline是跌(做多时)/涨(做空时);
        • min5: 前面(紧邻前面或前3个之中)有一个跌(做多时)/涨(做空时);
        • min5-最后一个时(kline.is_last_one): 当前为跌(做多时)/涨(做空时)
        • min5-非最后一个时: min1 连续2个跌(做多时)/涨(做空时)
        """
        kline_queue = self.kline_queue_container.get_by_period(self.default_period)
        assert kline_queue is not None

        if len(kline_queue.queue) < 6:
            return False

        if open_time is None and self.trader and self.trader.open_time:
            open_time = self.trader.open_time

        # ================================ 最后一个 KLine ================================ #

        # 做多时：最后一个必须是跌
        # 做多时：最后一个必须是涨
        if long_or_short == LongOrShort.LONG:
            self.desc_if_not_close = '最后一个不是跌'
            check_direction = KLineDirection.GOING_LOW
        else:
            self.desc_if_not_close = '最后一个不是涨'
            check_direction = KLineDirection.GOING_HIGH
        if kline_queue.queue[-1].direction != check_direction:
            return False

        # ================================ 前一个/前若干个中的反方向的 KLine ================================ #

        # 前一个
        fit_previous: bool = False
        previous_kline = None
        if long_or_short == LongOrShort.LONG:
            expect_direction = KLineDirection.GOING_LOW
        else:
            expect_direction = KLineDirection.GOING_HIGH
        # 检查前一个
        if kline_queue.queue[-2].direction == expect_direction:
            fit_previous = True
            previous_kline = kline_queue.queue[-2]
        # 前若干个
        check_previous_count = 3
        # 与价格最高/低的比较，允许价格差距在 0.02% 以内
        tolerance_percent = 0.02
        if not fit_previous:
            candidates = [kline_queue.queue[i] for i in range(-check_previous_count-1, -1)]
            avg_price = sum([kline.close for kline in candidates]) / len(candidates)
            candidate = None
            for c in reversed(candidates):
                if c.direction == expect_direction:
                    candidate = c
                    break
            if candidate is not None:
                # 与价格最高的比较，允许价格差距在 tolerance_percent 以内
                if long_or_short == LongOrShort.LONG:
                    min_or_max_candidate = sorted([(c, max(c.open, c.close)) for c in candidates], key=lambda x:x[1], reverse=True)[0][0]
                    a = max(candidate.open, candidate.close)
                    b = max(min_or_max_candidate.open, min_or_max_candidate.close)
                    if a > b or 100 * abs(a-b)/b < tolerance_percent:
                        fit_previous = True
                        previous_kline = candidate
                # 与价格最低的比较，允许价格差距在 tolerance_percent 以内
                else:
                    min_or_max_candidate = sorted([(c, min(c.open, c.close)) for c in candidates], key=lambda x:x[1], reverse=False)[0][0]
                    a = min(candidate.open, candidate.close)
                    b = max(min_or_max_candidate.open, min_or_max_candidate.close)
                    if a < b or 100 * abs(a-b)/b < tolerance_percent:
                        fit_previous = True
                        previous_kline = candidate
        if not fit_previous:
            self.desc_if_not_close = "前一个/前若干个的方向不符合"
            return False

        # ================================ 更小 period 的 direction ================================ #

        # 如果当前 min5 是最后一个则不检查更小的 period
        kline_closed =  kline_queue.queue[-1].is_last_one

        # 做多时：最后一个必须是涨
        # 做空时：最后一个必须是跌
        if not kline_closed and self.check_direction_of_shorter_period:
            # 至少需要过去 2min
            shorter_kline_queue = self.kline_queue_container.get_by_period(self.check_direction_of_shorter_period)
            if self.get_shorter_period_count(shorter_kline_queue.queue[-1].period_date.minute) <= 0:
                self.desc_if_not_open = f"shorter period {self.check_direction_of_shorter_period.value}数量不足"
                return False

            if not shorter_kline_queue.queue[-1].is_last_one:
                self.desc_if_not_open = f"shorter period {self.check_direction_of_shorter_period.value}最后一个还未结束"
                return False

            desc = f'shorter period {self.check_direction_of_shorter_period.value}最后2个方向不符合'
            current_directions = [shorter_kline_queue.queue[i].direction for i in range(-2, 0)]
            # current_directions = [shorter_kline_queue.queue[i].direction for i in range(-1, 0)]
            if long_or_short == LongOrShort.LONG:
                expect_directions = [KLineDirection.GOING_LOW] * 2
                # expect_directions = [KLineDirection.GOING_LOW] * 1
            else:
                expect_directions = [KLineDirection.GOING_HIGH] * 2
                # expect_directions = [KLineDirection.GOING_HIGH] * 1
            if set(current_directions) != set(expect_directions):
                self.desc_if_not_open = desc
                return False

        return True


class FiveStepV2_1(BaseStrategy):
    """5 步策略
    """
    _nickname = "👋"

    @property
    def nickname(self):
        return f"{self._nickname}{self.default_period.value}"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        # 测试是否支持 period 组合
        self.get_shorter_period_count(1)

        if self.default_period == KLinePeriod.MIN_3:
            self.PERIOD_MODULO = 3
        elif self.default_period == KLinePeriod.MIN_5:
            self.PERIOD_MODULO = 5
        elif self.default_period == KLinePeriod.MIN_15:
            self.PERIOD_MODULO = 15
        elif self.default_period == KLinePeriod.MIN_30:
            self.PERIOD_MODULO = 30

    def should_open_long(self) -> bool:
        """开仓做多
        """
        res = self._check_should_open(long_or_short=LongOrShort.LONG)
        self.desc_if_not_open_long = self.desc_if_not_open
        return res

    def should_open_short(self) -> bool:
        """开仓做空"""
        res = self._check_should_open(long_or_short=LongOrShort.SHORT)
        self.desc_if_not_open_short = self.desc_if_not_open
        return res

    def _check_should_open(self, long_or_short:LongOrShort) -> bool:
        """
        • min5 当前的需要是涨/跌
        • min5 前5个的规则:
            - 倒数第5,1个必须是涨/跌;
            - 倒数第 5 个必须是涨/跌;
            - 至少 4 个是涨/跌;
            - 其中的 4 或 5 个价格递增/递减;
            - 【暂时忽略】如果有 1 个不是涨/跌，则不能大于多少百分比;
            - 当前价格与倒数第1个的最少涨/跌百分比;
        • min1 连续2个涨/跌. 都需要 is_last_one
        """
        # 首先重置状态
        self.desc = None
        self.desc_if_not_open = None

        kline_queue = self.kline_queue_container.get_by_period(self.default_period)
        assert kline_queue is not None

        if len(kline_queue.queue) < 12:
            return False

        # ================================ 最后一个 KLine ================================ #

        # 做多时：最后一个必须是涨
        # 做空时：最后一个必须是跌
        if long_or_short == LongOrShort.LONG:
            if kline_queue.queue[-1].direction != KLineDirection.GOING_HIGH:
                self.desc_if_not_open = '最后一个不是涨'
                return False
        else:
            if kline_queue.queue[-1].direction != KLineDirection.GOING_LOW:
                self.desc_if_not_open = '最后一个不是跌'
                return False

        # ================================ 前 5 个 KLine: 索引 -6~-2 ================================ #

        # 做多时：倒数第5个必须是涨
        # 做空时：倒数第5个必须是跌
        desc_template = '倒数第6个不是涨/跌'
        if long_or_short == LongOrShort.LONG:
            self.desc_if_not_open = desc_template
            if kline_queue.queue[-6].direction != KLineDirection.GOING_HIGH:
                return False
        else:
            self.desc_if_not_open = desc_template
            if kline_queue.queue[-6].direction != KLineDirection.GOING_LOW:
                return False

        # TODO(2021.11.08): 这里待定忽略判断
        desc_template = '倒数第2个不是涨/跌'
        if long_or_short == LongOrShort.LONG:
            self.desc_if_not_open = desc_template
            if kline_queue.queue[-2].direction != KLineDirection.GOING_HIGH:
                return False
        else:
            self.desc_if_not_open = desc_template
            if kline_queue.queue[-2].direction != KLineDirection.GOING_LOW:
                return False

        # 5 条 Kline 的红绿的数量
        min_expect_count = 4
        directions = [kline_queue.queue[i].direction for i in range(-6, -1)]
        if long_or_short == LongOrShort.LONG:
            satisfied_direction = directions.count(KLineDirection.GOING_HIGH)
        else:
            satisfied_direction = directions.count(KLineDirection.GOING_LOW)
        if satisfied_direction < min_expect_count:
            self.desc_if_not_open = f"红绿数量不符合. {satisfied_direction}<{min_expect_count}"
            return False

        # 与前几个比较
        # tolerance_percent = 0.2
        tolerance_percent = 1
        candidates = [kline_queue.queue[i] for i in range(-6, -1)]
        long_conditions = [
            # (-1, lambda x: x.close > max(candidates[-5].open, candidates[-5].close)),
            (-1, lambda x:compare_with_tolerance(x.close, max(candidates[-5].open, candidates[-5].close), '>', tolerance_percent=tolerance_percent)),

            # (-1, lambda x: x.close > max(candidates[-4].open, candidates[-4].close)),
            (-1, lambda x:compare_with_tolerance(x.close, max(candidates[-4].open, candidates[-4].close), '>', tolerance_percent=tolerance_percent)),

            # (-1, lambda x: x.close > max(candidates[-3].open, candidates[-3].close)),
            # (-1, lambda x: x.close > max(candidates[-2].open, candidates[-2].close)),

            # (-2, lambda x: x.close > max(candidates[-5].open, candidates[-5].close)),
            (-2, lambda x:compare_with_tolerance(x.close, max(candidates[-5].open, candidates[-5].close), '>', tolerance_percent=tolerance_percent)),

            # (-2, lambda x: x.close > max(candidates[-4].open, candidates[-4].close)),

            # (-3, lambda x: max(x.open, x.close) > max(candidates[-5].open, candidates[-5].close)),
        ]
        short_conditions = [
            # (-1, lambda x: x.close < min(candidates[-5].open, candidates[-5].close)),
            (-1, lambda x:compare_with_tolerance(x.close, min(candidates[-5].open, candidates[-5].close), '<', tolerance_percent=tolerance_percent)),

            # (-1, lambda x: x.close < min(candidates[-4].open, candidates[-4].close)),
            (-1, lambda x:compare_with_tolerance(x.close, min(candidates[-4].open, candidates[-4].close), '<', tolerance_percent=tolerance_percent)),

            # (-1, lambda x: x.close < min(candidates[-3].open, candidates[-3].close)),
            # (-1, lambda x: x.close < min(candidates[-2].open, candidates[-2].close)),

            # (-2, lambda x: x.close < min(candidates[-5].open, candidates[-5].close)),
            (-2, lambda x:compare_with_tolerance(x.close, min(candidates[-5].open, candidates[-5].close), '<', tolerance_percent=tolerance_percent)),

            # (-2, lambda x: x.close < min(candidates[-4].open, candidates[-4].close)),

            # (-3, lambda x: min(x.open, x.close) < min(candidates[-5].open, candidates[-5].close)),
        ]
        if long_or_short == LongOrShort.LONG:
            conditions = long_conditions
        else:
            conditions = short_conditions
        for compare_idx, fn in conditions:
            if not fn(candidates[compare_idx]):
                self.desc_if_not_open = f"{compare_idx}的价格高低不符合"
                return False

        # 阶梯价格
        # 逐步升高/降低
        step_klines = []
        # step_prices = []
        # %1
        # max_tolerant_step_percent = 1
        max_tolerant_step_percent = 1.5
        for kline in candidates:
            if long_or_short == LongOrShort.LONG and kline.direction == KLineDirection.GOING_HIGH:
                step_klines.append(kline)
                # step_prices.append(kline.close)
                # step_prices.append(max(kline.open, kline.close))
            elif long_or_short == LongOrShort.SHORT and kline.direction == KLineDirection.GOING_LOW:
                step_klines.append(kline)
                # step_prices.append(kline.close)
                # step_prices.append(min(kline.open, kline.close))
        assert step_klines

        # 排除当前 kline 价格在上一个 kline 之间的情况
        step_prices = []
        for i, kline in enumerate(step_klines):
            if i == 0:
                step_prices.append(kline.close)
            else:
                last_kline = step_klines[i-1]
                if min(last_kline.open, last_kline.close) <= kline.close <= max(last_kline.open, last_kline.close):
                    continue
                step_prices.append(kline.close)
        assert step_prices
        # 价格相差很少则忽略
        filtered_step_prices = []
        for i in step_prices:
            if not filtered_step_prices:
                filtered_step_prices.append(i)
                continue
            # 与上一个比较
            last_price = filtered_step_prices[-1]
            # 相差小于%: max_tolerant_step_percent
            if (abs(i - last_price)/last_price)*100 <= max_tolerant_step_percent:
                continue
            filtered_step_prices.append(i)
        tmp_desc_if_not_open = None
        if long_or_short == LongOrShort.LONG:
            compare_sorted = sorted(filtered_step_prices, reverse=False)
            tmp_desc_if_not_open = f"close价格不是递增. {filtered_step_prices}"
        else:
            compare_sorted = sorted(filtered_step_prices, reverse=True)
            tmp_desc_if_not_open = f"close价格不是递减. {filtered_step_prices}"
        if filtered_step_prices != compare_sorted:
            self.desc_if_not_open = tmp_desc_if_not_open
            return False

        # ================================ 忽略价格震荡被前面包含的情况 ================================ #

        # previous_range = [kline_queue.queue[i] for i in range(-15, -6)]
        # previous_min = min([min(i.open, i.close) for i in previous_range])
        # previous_max = max([max(i.open, i.close) for i in previous_range])
        # current_range = [kline_queue.queue[i] for i in range(-6, -1)]
        # current_min = min([min(i.open, i.close) for i in current_range])
        # current_max = max([max(i.open, i.close) for i in current_range])
        # if previous_min <= current_min and previous_max >= current_max:
        #     self.desc_if_not_open = f"监测到震荡包含的情况"
        #     return False

        # ================================ 忽略价格震荡的情况 ================================ #

        # previous_range = [kline_queue.queue[i] for i in range(-11, -6)]
        # previous_min = min([min(i.open, i.close) for i in previous_range])
        # previous_max = max([max(i.open, i.close) for i in previous_range])
        # current_range = [kline_queue.queue[i] for i in range(-6, -1)]
        # current_min = min([min(i.open, i.close) for i in current_range])
        # current_max = max([max(i.open, i.close) for i in current_range])
        # # 允许的最大重叠百分比
        # max_overlap_percent = 95
        # overlap = self.get_overlap(previous_min, previous_max, current_min, current_max)
        # overlap_percent1 = round(100 * overlap / abs(previous_max - previous_min), 2)
        # overlap_percent2 = round(100 * overlap / abs(current_max - current_min), 2)
        # if overlap_percent1 > max_overlap_percent and overlap_percent2 > max_overlap_percent:
        #     self.desc_if_not_open = f"监测到震荡(最大重叠:{max_overlap_percent}%): {overlap_percent1}%, {overlap_percent2}%"
        #     return False

        # ================================ 更小 period 的 direction ================================ #

        # 如果当前 min5 是最后一个则不检查更小的 period
        kline_closed = kline_queue.queue[-1].is_last_one

        # 做多时：最后一个必须是涨
        # 做空时：最后一个必须是跌
        if not kline_closed and self.check_direction_of_shorter_period:
            # 至少需要过去 2min
            shorter_kline_queue = self.kline_queue_container.get_by_period(self.check_direction_of_shorter_period)
            if self.get_shorter_period_count(shorter_kline_queue.queue[-1].period_date.minute) <= 0:
                self.desc_if_not_open = f"shorter period {self.check_direction_of_shorter_period.value}数量不足"
                return False

            if not shorter_kline_queue.queue[-1].is_last_one:
                self.desc_if_not_open = f"shorter period {self.check_direction_of_shorter_period.value}最后一个还未结束"
                return False

            if self.shorter_period_continuous_count:
                desc = f'shorter period {self.check_direction_of_shorter_period.value}最后{self.shorter_period_continuous_count}个方向不符合'
                current_directions = [shorter_kline_queue.queue[i].direction for i in range(-self.shorter_period_continuous_count, 0)]
                if long_or_short == LongOrShort.LONG:
                    expect_directions = [KLineDirection.GOING_HIGH] * self.shorter_period_continuous_count
                else:
                    expect_directions = [KLineDirection.GOING_LOW] * self.shorter_period_continuous_count
                if set(current_directions) != set(expect_directions):
                    self.desc_if_not_open = desc
                    return False

        # ================================ 当前价格与倒数第 6 个涨跌百分比 ================================ #

        current_price = kline_queue.queue[-1].close

        min_diff_percent = 0.2
        # price2 = kline_queue.queue[-6].close
        price2 = kline_queue.queue[-6].open

        # min_diff_percent = 0.4
        # price2 = kline_queue.queue[-6].open

        percent = 100 * (current_price - price2) / price2
        desc_template = "当前价格与第一个kline涨跌百分比不符(min_diff_percent%): {}%"
        if long_or_short == LongOrShort.LONG:
            if percent < min_diff_percent:
                self.desc_if_not_open = desc_template.format('{:.3f}'.format(percent))
                return False
        else:
            if percent > -min_diff_percent:
                self.desc_if_not_open = desc_template.format('{:.3f}'.format(percent))
                return False

        # ================================ Done ================================ #

        scorer = Scorer(kline_queue, start_index=-6, end_index=-1)
        self.score = scorer.get_score()

        self.desc_if_not_open = None
        # 开仓原因描述
        desc_list = [
            '{}{}%'.format(
                kline_queue.queue[-6].direction_symbol,
                kline_queue.queue[-6].percent,
            ),
            '{}{}%'.format(
                kline_queue.queue[-5].direction_symbol,
                kline_queue.queue[-5].percent,
            ),
            '{}{}%'.format(
                kline_queue.queue[-4].direction_symbol,
                kline_queue.queue[-4].percent,
            ),
            '{}{}%'.format(
                kline_queue.queue[-3].direction_symbol,
                kline_queue.queue[-3].percent,
            ),
            '{}{}%'.format(
                kline_queue.queue[-2].direction_symbol,
                kline_queue.queue[-2].percent,
            ),
            '{}{}%,{}'.format(
                kline_queue.queue[-1].direction_symbol,
                kline_queue.queue[-1].percent,
                kline_queue.queue[-1].close,
            ),
        ]
        self.desc = ' | '.join(desc_list)
        return True

    def should_close_long(self, open_time:datetime.datetime=None, now:datetime.datetime=None) -> bool:
        """做多平仓"""
        return self._check_should_close(long_or_short=LongOrShort.LONG, open_time=open_time, now=now)

    def should_close_short(self, open_time:datetime.datetime=None, now:datetime.datetime=None) -> bool:
        """做空平仓"""
        return self._check_should_close(long_or_short=LongOrShort.SHORT, open_time=open_time, now=now)

    def _check_should_close(self, long_or_short:LongOrShort, open_time:datetime.datetime=None, now:datetime.datetime=None) -> bool:
        """
        • min5 当前的kline是跌(做多时)/涨(做空时);
        • min5: 前面(紧邻前面或前3个之中)有一个跌(做多时)/涨(做空时);
        • min5-最后一个时(kline.is_last_one): 当前为跌(做多时)/涨(做空时)
        • min5-非最后一个时: min1 连续2个跌(做多时)/涨(做空时)
        """
        kline_queue = self.kline_queue_container.get_by_period(self.default_period)
        assert kline_queue is not None

        if len(kline_queue.queue) < 6:
            return False

        # open_time
        if open_time is None and self.trader and self.trader.open_time:
            open_time = self.trader.open_time

        # now
        # now = now or datetime.datetime.now()
        # if True:
        # if not now:
        if self.check_cross_ma_by_bigger_period:
            now1 = self.kline_queue_container.get_by_period(self.check_cross_ma_by_bigger_period).queue[-1].period_date
        else:
            now1 = kline_queue.queue[-2].period_date
        now2 = kline_queue.queue[-1].period_date
        now = max(now1, now2)

        # ================================ 最后一个 KLine ================================ #

        # 做多时：最后一个必须是跌
        # 做多时：最后一个必须是涨
        if long_or_short == LongOrShort.LONG:
            self.desc_if_not_close = '最后一个不是跌'
            check_direction = KLineDirection.GOING_LOW
        else:
            self.desc_if_not_close = '最后一个不是涨'
            check_direction = KLineDirection.GOING_HIGH
        if kline_queue.queue[-1].direction != check_direction:
            return False

        # ================================ 检查 KLine 是否提前平仓 ================================ #

        # 前几个 kline 只要有一个 kline 方向不符就平仓
        tolerant_kline_forward_count = 3
        if kline_queue.queue[-1].is_last_one and open_time and abs(kline_queue.queue[-1].percent) >= 0.02:
            total_minutes = (now - open_time).total_seconds()/60
            kline_forward_count = math.ceil(total_minutes / self.PERIOD_MODULO)
            if kline_forward_count <= tolerant_kline_forward_count:
                return True

        # ================================ 前一个/前若干个中的反方向的 KLine ================================ #

        # 前一个
        fit_previous: bool = False
        previous_kline = None
        if long_or_short == LongOrShort.LONG:
            expect_direction = KLineDirection.GOING_LOW
        else:
            expect_direction = KLineDirection.GOING_HIGH
        # 检查前一个
        check_open_time = kline_queue.queue[-2].period_date > open_time if open_time else True
        if kline_queue.queue[-2].direction == expect_direction and check_open_time:
            fit_previous = True
            previous_kline = kline_queue.queue[-2]
        # 前若干个
        check_previous_count = 3
        # 与价格最高/低的比较，允许价格差距在 0.02% 以内
        tolerance_percent = 0.05
        if not fit_previous:
            if open_time:
                candidates = [kline_queue.queue[i] for i in range(-check_previous_count-1, -1) if kline_queue.queue[i].period_date > open_time]
            else:
                candidates = [kline_queue.queue[i] for i in range(-check_previous_count-1, -1)]
            if candidates:
                avg_price = sum([kline.close for kline in candidates]) / len(candidates)
                candidate = None
                for c in reversed(candidates):
                    if c.direction == expect_direction:
                        candidate = c
                        break
                if candidate is not None:
                    # 与价格最高的比较，允许价格差距在 tolerance_percent 以内
                    if long_or_short == LongOrShort.LONG:
                        min_or_max_candidate = sorted([(c, max(c.open, c.close)) for c in candidates], key=lambda x:x[1], reverse=True)[0][0]
                        a = max(candidate.open, candidate.close)
                        b = max(min_or_max_candidate.open, min_or_max_candidate.close)
                        if a > b or 100 * abs(a-b)/b < tolerance_percent:
                            fit_previous = True
                            previous_kline = candidate
                    # 与价格最低的比较，允许价格差距在 tolerance_percent 以内
                    else:
                        min_or_max_candidate = sorted([(c, min(c.open, c.close)) for c in candidates], key=lambda x:x[1], reverse=False)[0][0]
                        a = min(candidate.open, candidate.close)
                        b = max(min_or_max_candidate.open, min_or_max_candidate.close)
                        if a < b or 100 * abs(a-b)/b < tolerance_percent:
                            fit_previous = True
                            previous_kline = candidate
        if not fit_previous:
            self.desc_if_not_close = "前一个/前若干个的方向不符合"
            return False

        # ================================ 更小 period 的 direction ================================ #

        # 如果当前 min5 是最后一个则不检查更小的 period
        kline_closed =  kline_queue.queue[-1].is_last_one

        # 做多时：最后一个必须是涨
        # 做空时：最后一个必须是跌
        if not kline_closed and self.check_direction_of_shorter_period:
            # 至少需要过去 2min
            shorter_kline_queue = self.kline_queue_container.get_by_period(self.check_direction_of_shorter_period)
            if self.get_shorter_period_count(shorter_kline_queue.queue[-1].period_date.minute) <= 0:
                self.desc_if_not_open = f"shorter period {self.check_direction_of_shorter_period.value}数量不足"
                return False

            if not shorter_kline_queue.queue[-1].is_last_one:
                self.desc_if_not_open = f"shorter period {self.check_direction_of_shorter_period.value}最后一个还未结束"
                return False

            if self.shorter_period_continuous_count:
                desc = f'shorter period {self.check_direction_of_shorter_period.value}最后{self.shorter_period_continuous_count}个方向不符合'
                current_directions = [shorter_kline_queue.queue[i].direction for i in range(-self.shorter_period_continuous_count, 0)]
                # current_directions = [shorter_kline_queue.queue[i].direction for i in range(-1, 0)]
                if long_or_short == LongOrShort.LONG:
                    expect_directions = [KLineDirection.GOING_LOW] * self.shorter_period_continuous_count
                    # expect_directions = [KLineDirection.GOING_LOW] * 1
                else:
                    expect_directions = [KLineDirection.GOING_HIGH] * self.shorter_period_continuous_count
                    # expect_directions = [KLineDirection.GOING_HIGH] * 1
                if set(current_directions) != set(expect_directions):
                    self.desc_if_not_open = desc
                    return False

        return True


class MovingAverageV2(BaseStrategy):
    """均线策略

    均线的价格介于当前kline之间
    """
    _nickname = "🦶ma"

    @property
    def nickname(self):
        return f"{self._nickname}-{self.default_period.value}"

    def __init__(self, ma_list:List[int]=None, tolerante_ma_price_diff=None, **kwargs):
        super().__init__(**kwargs)
        self.ma_list = list(map(int, ma_list)) if ma_list else [20, 40]
        # 允许 kline 与移动平均线交叉时的误差; 所占 kline 的占比
        default_tolerante_ma_price_diff = Decimal('1')/Decimal('8')
        self.tolerant_ma_price_diff:float = tolerante_ma_price_diff if tolerante_ma_price_diff is not None else default_tolerante_ma_price_diff

    def should_open_long(self) -> bool:
        """开仓做多
        """
        res = self._check_should_open(long_or_short=LongOrShort.LONG)
        self.desc_if_not_open_long = self.desc_if_not_open
        return res

    def should_open_short(self) -> bool:
        """开仓做空"""
        res = self._check_should_open(long_or_short=LongOrShort.SHORT)
        self.desc_if_not_open_short = self.desc_if_not_open
        return res

    def _check_should_open(self, long_or_short:LongOrShort) -> bool:
        # 首先重置状态
        self.desc = None
        self.desc_if_not_open = None

        kline_queue = self.kline_queue_container.get_by_period(self.default_period)
        assert kline_queue is not None

        if len(kline_queue.queue) < max(self.ma_list):
            return False

        # ================================ KLine 必须已结束 ================================ #
        if not kline_queue.queue[-1].is_last_one:
            self.desc_if_not_open = 'kline还未结束'
            return False

        # ================================ 最后一个 KLine ================================ #

        # 做多时：最后一个必须是涨
        # 做空时：最后一个必须是跌
        if long_or_short == LongOrShort.LONG:
            if kline_queue.queue[-1].direction != KLineDirection.GOING_HIGH:
                self.desc_if_not_open = '最后一个不是涨'
                return False
        else:
            if kline_queue.queue[-1].direction != KLineDirection.GOING_LOW:
                self.desc_if_not_open = '最后一个不是跌'
                return False

        # ================================ 2 个条件满足任何一个即可 ================================ #

        # ================================ 1/2. ma_list 的价格介于 kline 之间 ================================ #
        def condition_cross_all_ma():
            last_kline = kline_queue.queue[-1]
            min_price = min(last_kline.open, last_kline.close)
            max_price = max(last_kline.open, last_kline.close)
            diff = (max_price - min_price) * float(self.tolerant_ma_price_diff)
            min_price -= diff
            max_price += diff

            for ma in self.ma_list:
                ma_price = kline_queue.ma(ma)[-1]
                if not (min_price <= ma_price <= max_price):
                    self.desc_if_not_open = f'ma({ma})价格不介于kline中. {ma_price}({min_price}~{max_price})'
                    return False
            return True

        # ================================ 2/2. 最大的ma价格介于kline之间，且最大的ma的价格大于其余的 ================================ #
        def condition_cross_max_ma():
            """需要修改做空的情况
            """
            last_kline = kline_queue.queue[-1]
            min_price = min(last_kline.open, last_kline.close)
            max_price = max(last_kline.open, last_kline.close)
            diff = (max_price - min_price) * float(self.tolerant_ma_price_diff)
            min_price -= diff
            max_price += diff

            max_ma = max(self.ma_list)
            max_ma_price = kline_queue.ma(max_ma)[-1]
            if not (min_price <= max_ma_price <= max_price):
                self.desc_if_not_open = f'ma({max_ma})价格不介于kline中. {max_ma_price}({min_price}~{max_price})'
                return False
            ma_prices = [kline_queue.ma(i)[-1] for i in self.ma_list]
            if max(ma_prices) != max_ma_price:
                self.desc_if_not_open = f'ma({max_ma})价格不是所有ma中最大的'
                return False
            return True

        # 2 个条件满足任何一个即可
        # if not condition_cross_all_ma() and not condition_cross_max_ma():
        #     return False

        # 满足条件: 穿过所有均线
        if not condition_cross_all_ma():
            return False

        # ================================ Done ================================ #

        scorer = Scorer(kline_queue, start_index=-6, end_index=-1)
        self.score = scorer.get_score()

        self.desc_if_not_open = None
        # 开仓原因描述
        desc_list = [
            '{}{}%'.format(
                kline_queue.queue[-6].direction_symbol,
                kline_queue.queue[-6].percent,
            ),
            '{}{}%'.format(
                kline_queue.queue[-5].direction_symbol,
                kline_queue.queue[-5].percent,
            ),
            '{}{}%'.format(
                kline_queue.queue[-4].direction_symbol,
                kline_queue.queue[-4].percent,
            ),
            '{}{}%'.format(
                kline_queue.queue[-3].direction_symbol,
                kline_queue.queue[-3].percent,
            ),
            '{}{}%'.format(
                kline_queue.queue[-2].direction_symbol,
                kline_queue.queue[-2].percent,
            ),
            '{}{}%'.format(
                kline_queue.queue[-1].direction_symbol,
                kline_queue.queue[-1].percent,
            ),
        ]
        # for ma in self.ma_list:
        #     ma_price = kline_queue.ma(ma)[-1]
        #     desc_list.append(f'ma({ma})={readable_number(ma_price)}')
        desc_list.append(f'current={kline_queue.queue[-1].close}')
        self.desc = ' | '.join(desc_list)
        return True

    def should_close_long(self, open_time:datetime.datetime=None, now:datetime.datetime=None) -> bool:
        """做多平仓"""
        return self._check_should_close(long_or_short=LongOrShort.LONG, open_time=open_time, now=now)

    def should_close_short(self, open_time:datetime.datetime=None, now:datetime.datetime=None) -> bool:
        """做空平仓"""
        return self._check_should_close(long_or_short=LongOrShort.SHORT, open_time=open_time, now=now)

    def _check_should_close(self, long_or_short:LongOrShort, open_time:datetime.datetime=None, now:datetime.datetime=None) -> bool:
        # 首先重置状态
        self.desc = None
        self.desc_if_not_open = None

        kline_queue = self.kline_queue_container.get_by_period(self.default_period)
        assert kline_queue is not None

        if len(kline_queue.queue) < max(self.ma_list):
            return False

        # ================================ KLine 必须已结束 ================================ #
        if not kline_queue.queue[-1].is_last_one:
            self.desc_if_not_open = 'kline还未结束'
            return False

        # ================================ 最后一个 KLine ================================ #

        # 做多时：最后一个必须是跌
        # 做多时：最后一个必须是涨
        if long_or_short == LongOrShort.LONG:
            self.desc_if_not_close = '最后一个不是跌'
            check_direction = KLineDirection.GOING_LOW
        else:
            self.desc_if_not_close = '最后一个不是涨'
            check_direction = KLineDirection.GOING_HIGH
        if kline_queue.queue[-1].direction != check_direction:
            return False

        # ================================ ma_list 的价格介于 kline 之间 ================================ #
        last_kline = kline_queue.queue[-1]
        min_price = min(last_kline.open, last_kline.close)
        max_price = max(last_kline.open, last_kline.close)

        ma = min(self.ma_list)
        ma_price = kline_queue.ma(ma)[-1]
        if long_or_short == LongOrShort.LONG:
            if ma_price <= min_price:
                self.desc_if_not_open = f'ma({ma})价格未跌破. {ma_price}({min_price}~{max_price})'
                return False
        else:
            if ma_price >= min_price:
                self.desc_if_not_open = f'ma({ma})价格未涨破. {ma_price}({min_price}~{max_price})'
                return False

        return True


class MACDSteps(BaseStrategy):
    """MACD策略

    macd 的 5 步策略

    - https://zhuanlan.zhihu.com/p/68375348
    - https://zhuanlan.zhihu.com/p/76864391
    """
    _nickname = "macd"

    @property
    def nickname(self):
        return f"{self._nickname}-{self.default_period.value}"

    def should_open_long(self) -> bool:
        """开仓做多
        """
        res = self._check_should_open(long_or_short=LongOrShort.LONG)
        self.desc_if_not_open_long = self.desc_if_not_open
        return res

    def should_open_short(self) -> bool:
        """开仓做空"""
        res = self._check_should_open(long_or_short=LongOrShort.SHORT)
        self.desc_if_not_open_short = self.desc_if_not_open
        return res

    def _check_should_open(self, long_or_short:LongOrShort) -> bool:
        # 首先重置状态
        self.desc = None
        self.desc_if_not_open = None

        kline_queue = self.kline_queue_container.get_by_period(self.default_period)
        assert kline_queue is not None

        if len(kline_queue.macd) < 5:
            return False

        # ================================ KLine 必须已结束 ================================ #
        if not kline_queue.queue[-1].is_last_one:
            self.desc_if_not_open = 'kline还未结束'
            return False

        # ================================ 最后一个 KLine ================================ #

        # 做多时：最后一个必须是涨
        # 做空时：最后一个必须是跌
        if long_or_short == LongOrShort.LONG:
            if kline_queue.queue[-1].direction != KLineDirection.GOING_HIGH:
                self.desc_if_not_open = '最后一个不是涨'
                return False
        else:
            if kline_queue.queue[-1].direction != KLineDirection.GOING_LOW:
                self.desc_if_not_open = '最后一个不是跌'
                return False

        # ================================ 前几个 macd 值 ================================ #
        macd_list = [kline_queue.macd[i] for i in range(-5, 0)]
        if long_or_short == LongOrShort.LONG:
            if any([i.hist <= 0 for i in macd_list]):
                self.desc_if_not_open = '存在hist<=0'
                return False
        else:
            if any([i.hist >= 0 for i in macd_list]):
                self.desc_if_not_open = '存在hist>=0'
                return False

        # ================================ Done ================================ #

        scorer = Scorer(kline_queue, start_index=-6, end_index=-1)
        self.score = scorer.get_score()

        self.desc_if_not_open = None
        # 开仓原因描述
        desc_list = [
            '{}{}%'.format(
                kline_queue.queue[-6].direction_symbol,
                kline_queue.queue[-6].percent,
            ),
            '{}{}%'.format(
                kline_queue.queue[-5].direction_symbol,
                kline_queue.queue[-5].percent,
            ),
            '{}{}%'.format(
                kline_queue.queue[-4].direction_symbol,
                kline_queue.queue[-4].percent,
            ),
            '{}{}%'.format(
                kline_queue.queue[-3].direction_symbol,
                kline_queue.queue[-3].percent,
            ),
            '{}{}%'.format(
                kline_queue.queue[-2].direction_symbol,
                kline_queue.queue[-2].percent,
            ),
            '{}{}%'.format(
                kline_queue.queue[-1].direction_symbol,
                kline_queue.queue[-1].percent,
            ),
        ]
        # for i in range(-5, 0):
        for i in range(-3, 0):
            macd = kline_queue.macd[i]
            desc_list.append(f'macd({i})={readable_number(macd.hist)}')
        desc_list.append(f'current={kline_queue.queue[-1].close}')
        self.desc = ' | '.join(desc_list)
        return True
