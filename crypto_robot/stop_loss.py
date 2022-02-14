from .common import KLineDirection, KLinePeriod
from .kline import KLineQueue
from .trader import Trader


class StopLoss:
    """止损"""
    # 不同 period 对应的跌倒某一价位需要持续的秒数
    DURATION_FOR_CLOSE_PRICE_CONDITION = {
        KLinePeriod.MIN_1: 30,
        KLinePeriod.MIN_5: 60,
        KLinePeriod.MIN_15: 90,
    }
    def should_close_long(self, kline_queue:KLineQueue, trader:Trader) -> bool:
        if not trader:
            return False
        if trader.stop_loss_price is None:
            return False
        if kline_queue.queue[-1].direction == KLineDirection.GOING_HIGH:
            return False
        if abs(kline_queue.queue[-1].percent) < 0.1:
            return False

        # current_price = kline_queue.queue[-1].close
        # if current_price <= trader.stop_loss_price:
        #     return True
        # 低于止损价, 并且持续 30 秒以上
        seconds = kline_queue.seconds_fitting_condition(lambda x:x<=trader.stop_loss_price)
        if seconds and seconds >= self.DURATION_FOR_CLOSE_PRICE_CONDITION[kline_queue.period]:
            return True
        return False

    def should_close_short(self, kline_queue:KLineQueue, trader:Trader) -> bool:
        if not trader:
            return False
        if trader.stop_loss_price is None:
            return False
        if kline_queue.queue[-1].direction == KLineDirection.GOING_LOW:
            return False
        if abs(kline_queue.queue[-1].percent) < 0.1:
            return False

        # current_price = kline_queue.queue[-1].close
        # if current_price >= trader.stop_loss_price:
        #     return True
        # 高于止损价, 并且持续 30 秒以上
        seconds = kline_queue.seconds_fitting_condition(lambda x:x>=trader.stop_loss_price)
        if seconds and seconds >= self.DURATION_FOR_CLOSE_PRICE_CONDITION[kline_queue.period]:
            return True
        return False
