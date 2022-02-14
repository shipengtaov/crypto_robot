import datetime
from decimal import Decimal

import attr
import pandas as pd

from ..common import LongOrShort


@attr.s
class Order:
    long_or_short:LongOrShort = attr.ib()
    open_price = attr.ib(factory=float)
    close_price = attr.ib(factory=float)
    open_time = attr.ib(default=None)
    close_time = attr.ib(default=None)

    closed:bool = attr.ib(factory=bool)

    @property
    def profit(self) -> Decimal:
        if not self.closed or not self.long_or_short or not self.open_price or not self.close_price:
            return

        res = None
        if self.long_or_short is LongOrShort.LONG:
            res = (Decimal(self.close_price) - Decimal(self.open_price)) / Decimal(self.open_price)
        if self.long_or_short is LongOrShort.SHORT:
            res = (Decimal(self.open_price) - Decimal(self.close_price)) / Decimal(self.open_price)
        if res is not None:
            return res


class Trade:
    def __init__(self, balance:float=None) -> None:
        default_balance = 10000
        self.balance = balance or default_balance

        self.orders = []

    def open(self, long_or_short:LongOrShort, current_price:float, open_time:datetime.datetime=None):
        order = Order(
            long_or_short=long_or_short,
            open_price=current_price,
            open_time=open_time or datetime.datetime.now(),
        )
        self.orders.append(order)

    def close(self, current_price:float, long_or_short:LongOrShort=None, close_time:datetime.datetime=None):
        if not self.orders:
            return
        order = self.orders[-1]
        if long_or_short and order.long_or_short != long_or_short:
            return
        if order.closed:
            return
        if not order.open_price:
            return
        order.close_price = current_price
        order.close_time = close_time or datetime.datetime.now()
        order.closed = True

    @property
    def final_balance(self) -> float:
        """
        >>> obj = Trade()
        >>> obj.open(LongOrShort.LONG, 100)
        >>> obj.close(110)
        >>> obj.final_balance
        11000.0

        >>> obj.open(LongOrShort.SHORT, 110)
        >>> obj.close(99)
        >>> obj.final_balance
        12100.0
        """
        balance = Decimal(self.balance)
        for order in self.orders:
            if order.profit is not None:
                balance *= 1 + Decimal(str(order.profit))
        return float(balance)

    @property
    def final_profit(self) -> str:
        """
        >>> obj = Trade()
        >>> obj.open(LongOrShort.LONG, 100)
        >>> obj.close(110)
        >>> obj.final_profit
        '10.000%'
        """
        profit = 100*(self.final_balance - self.balance)/self.balance
        return f'{profit:.3f}%'

    @property
    def stats(self) -> str:
        res = [
            f"初始余额：{self.balance}",
            f"最终余额：{self.final_balance}",
            f"收益率：{self.final_profit}",
            f"交易次数：{len(self.orders)}",
            f"收益为正的交易次数：{len([i for i in self.orders if i.profit > 0])}",
            f"收益为负的交易次数：{len([i for i in self.orders if i.profit < 0])}",
            f"最大收益的交易：{max([i.profit for i in self.orders])}",
            f"最大亏损的交易：{min([i.profit for i in self.orders])}",
        ]
        return '\n'.join(res)

    @property
    def orders_df(self) -> pd.DataFrame:
        columns = [
            'long_or_short',
            'open_time',
            'open_price',
            'close_time',
            'close_price',
            'profit',
        ]
        data = []
        for order in self.orders:
            row = [
                order.long_or_short.value,
                order.open_time,
                order.open_price,
                order.close_price,
                order.close_time,
                order.profit,
            ]
            data.append(row)
        return pd.DataFrame(data, columns=columns)
