"""
交易
"""
import datetime
import time
from typing import List, Optional
import traceback

from .common import Coin, LongOrShort, OrderInExchange, get_logger, auto_retry, get_coin_lever
from . import db
from . import exception
from . import settings
from .exchanges import BinanceUsdtSwap
from .exchanges.binance import OrderStatus as BinanceOrderStatus
from .notification import Notification


logger = get_logger()


class Trader:
    def __init__(self,
                 coin:Coin,
                 trading:bool,
                 trade_count:int=None,
                 long_or_short:LongOrShort=None,
                 balance_before_open:float=None,
                 open_price:float=None,
                 open_volume:float=None,
                 open_time:datetime.datetime=None,
                 db_id:int=None,
                 consider_pseudo_trading:bool=False):
        """
        Args:
            coin: 币种
            long_or_short: 做多还是做空
            trading: 是否正在交易中
            trade_count: 交易次数
            balance_before_open: 开仓前余额
            open_price: 开仓成交价格
            open_volume: 开仓成交量
            open_time: 开仓时间
            db_id: 数据库id
        """
        self.coin = coin
        self.trading:bool = trading

        self.exchange_cls = BinanceUsdtSwap

        # 交易次数. 开仓时开始 +1
        self.trade_count:int = trade_count or 0

        # 是否考虑刚启动时第一次伪装交易
        self.consider_pseudo_trading:bool = consider_pseudo_trading
        # 是否正在伪装交易
        self.pseudo_trading:bool = False

        self.long_or_short = long_or_short

        self.balance_before_open:float = balance_before_open
        # 优先使用订单中获取的价格, 其次使用 current_price(不精确). 为其它策略而准备
        self.open_price = open_price
        self.open_volume = open_volume
        self.open_time:datetime.datetime = open_time

        self.close_price:float = None
        self.close_time:datetime.datetime = None
        self.profit:float = None

        # 数据库
        self.write_to_db:bool = False
        # 数据库中记录的 id
        self.db_id:int = db_id

        # 杠杆倍数
        self.lever_rate = get_coin_lever(self.coin)

        # 第一次伪装开仓. 防止刚启动脚本时立即开仓
        # 至少第一次交易之后才开始真实交易
        self.max_pseudo_trading_count:int = 1

        self.stop_trade:bool = False
        # time.time()
        self.re_trade_until:float = None

    @property
    def can_i_trade(self) -> bool:
        """是否可以交易"""
        if self.stop_trade:
            return False
        if self.re_trade_until:
            return time.time() >= self.re_trade_until
        return True

    @property
    def stop_loss_price(self) -> Optional[float]:
        """止损价"""
        if not self.open_price or not self.long_or_short:
            return
        # 开仓平仓总的手续费
        total_fee_percent = 0.08/100
        # 能容忍的价格变化百分比
        tolerant_percent = total_fee_percent/self.lever_rate
        open_price = float(self.open_price)
        # 做多时: (开仓价-当前价) / 开仓价 >= 百分比/杠杆
        if self.long_or_short == LongOrShort.LONG:
            return open_price - tolerant_percent * open_price
        # 做空时: (当前价-开仓价) / 开仓价 >= 百分比/杠杆
        elif self.long_or_short == LongOrShort.SHORT:
            return open_price + tolerant_percent * open_price

    @classmethod
    async def init_traders(cls, coins:List[Coin]=None, read_db:bool=False, consider_pseudo_trading:bool=False, exchange_cls=BinanceUsdtSwap):
        """初始化数据库数据
        这里提前初始化余额，避免开仓时还得读取余额而耗费时间

        操作包括:
        - 先读取数据库中进行中的交易;
        - 按参数 coins 初始化余额信息;

        Args:
            coins: 所有需要交易的币种. 单用户时使用此，之后如果多用户则需要读取数据库
        """
        coins = coins or set()
        # Dict[Coin, Trader]
        traders = dict()

        # 读取数据库
        if read_db:
            sql = "select * from orders where closed!=%s"
            args = (True,)
            data = await db.execute(sql, args=args) or []
            coin_map = {i.value:i for i in Coin}
            long_or_short_map = {i.value:i for i in LongOrShort}
            for d in data:
                coin = coin_map[d['coin']]
                trader = cls(
                    coin=coin,
                    long_or_short=long_or_short_map[d['long_or_short']],
                    trading=True,
                    trade_count=1,
                    balance_before_open=d['balance_before_open'],
                    open_price=d['open_price'] or d['open_plan_price'],
                    open_volume=d['open_volume'] or d['open_plan_volume'],
                    open_time=d['open_time'],
                    db_id=d['id'],
                    consider_pseudo_trading=consider_pseudo_trading,
                )
                traders[coin] = trader

        # 按参数 coins 初始化
        for coin in set(coins) - set(traders.keys()):
            # 获取余额
            future_fn = lambda:exchange_cls(coin=coin).get_account_info()
            balance = await auto_retry(future_fn=future_fn, infinite=True)
            trader = cls(coin=coin, trading=False, balance_before_open=balance, consider_pseudo_trading=consider_pseudo_trading)
            traders[coin] = trader
        return traders

    def pseudo_open(self, long_or_short:LongOrShort, current_price:float=None) -> bool:
        """第一次交易伪装开仓"""
        logger.debug(f'pseudo open: {self.coin}')
        self.trading = True
        self.pseudo_trading = True
        self.trade_count += 1
        self.long_or_short = long_or_short
        self.open_price = current_price
        self.open_time = datetime.datetime.now()
        return True

    async def open(self, long_or_short:LongOrShort, current_price:float) -> bool:
        """开仓"""
        if self.balance_before_open <= 0:
            # logger.waring('balance not enough')
            return

        # 交易使用多少百分比总成本
        using_balance = self.balance_before_open * settings.trade_percent * self.lever_rate

        volume = self.exchange_cls.convert_balance_to_volume(coin=self.coin, balance=using_balance, current_price=current_price)
        # 至少有 1 张
        if not volume:
            # logger.warning('volumn not enough')
            return

        # 第一次伪装交易
        if self.consider_pseudo_trading and self.trade_count < self.max_pseudo_trading_count:
            return self.pseudo_open(long_or_short=long_or_short, current_price=current_price)

        self.long_or_short = long_or_short
        exchange_obj = self.exchange_cls(coin=self.coin)
        try:
            future_fn = lambda:exchange_obj.open(quantity=volume, long_or_short=self.long_or_short)
            order_id = await auto_retry(future_fn=future_fn, retry_count=5, retry_msg=f'retry 开仓: {self.coin.value}')
        except Exception as e:
            if isinstance(e, exception.InsufficientMarginAvailable):
                logger.warning(f"开仓时volumn不足:{self.coin.value}.{e}")
                return

            logger.error(f"开仓下单出错. {self.coin.value}. {e}")
            if settings.debug:
                logger.error(traceback.format_exc())
            await Notification.send_catching_exc(msg=f'{self.coin.value}: 开仓下单出错.{e}')
            return False

        # 获取新订单的信息. 刚开仓的订单信息会更新
        try:
            # 如果获取订单出错则使用此处的值
            order = OrderInExchange(order_id=order_id, volume=volume, price=current_price)
            future_fn = lambda:exchange_obj.get_order_info_until_done(order_id=order_id)
            order = await auto_retry(future_fn=future_fn, retry_count=10, retry_msg=f'retry get_order_info of {self.coin.value}: {order_id}')
        except Exception as e:
            logger.error(f'开仓时获取订单出错: {self.coin.value}, {order_id}. {e}')
            if settings.debug:
                logger.error(traceback.format_exc())
            await Notification.send_catching_exc(msg=f'{self.coin.value}: 开仓时获取订单出错.{e}')
            return

        if not order:
            msg = f'{self.coin.value}: 订单已撤销'
            logger.warning(msg)
            await Notification.send_catching_exc(msg=msg)
            return False

        # 未全部成交
        if order.status != BinanceOrderStatus.FILLED:
            msg = f'{self.coin.value}: 订单未全部成交'
            logger.warning(msg)
            await Notification.send_catching_exc(msg=msg)
            return False

        if self.write_to_db:
            try:
                # 插入数据库
                sql = """insert into orders (
                    coin, open_price, open_volume, open_plan_price, open_plan_volume,
                    open_fee, long_or_short, balance_before_open, huobi_open_order_id)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """
                args = [
                    self.coin.value, order.trade_avg_price, order.trade_volume, order.price, order.volume,
                    order.fee, self.long_or_short.value, self.balance_before_open, order_id
                ]
                inserted_id = await db.execute(sql, args=args)
                self.db_id = inserted_id
            except Exception as e:
                logger.error(f"开仓时插入数据库出错: {self.coin.value},{order_id}. {e}")
                if settings.debug:
                    logger.error(traceback.format_exc())
                await Notification.send_catching_exc(msg=f'{self.coin.value}: 开仓时插入数据库出错.{e}')

        # 设置 instance 状态
        self.trading = True
        self.trade_count += 1
        # 优先使用订单中获取的价格, 其次使用 current_price(不精确)
        self.open_price = order.trade_avg_price or current_price
        self.open_volume = order.trade_volume or order.volume or volume
        self.open_time = datetime.datetime.now()

        if settings.debug:
            logger.debug(f'开仓:price:{self.open_price}, volume:{self.open_volume}')
        msg = "`{}`{}`open:{}`     `price:{}`     `volume:{}`".format(
            self.coin.value,
            ' '*(13-len(self.coin.value)),
            self.long_or_short.value,
            self.open_price,
            self.open_volume,
        )
        await Notification.send_catching_exc(msg=msg)
        return True

    def pseudo_close(self, current_price:float=None) -> bool:
        logger.debug(f'pseudo close: {self.coin}')
        self.close_price = current_price
        self.close_time = datetime.datetime.now()

        self.auto_set_profit()

        self.trading = False
        self.pseudo_trading = False
        self.open_price = None
        self.open_volume = None
        self.open_time = None
        self.db_id = None
        return True

    async def close(self, current_price:float=None) -> bool:
        """关仓

        Args:
            current_price: 触发平仓时的价格
        """
        # 是否是伪装交易
        if self.consider_pseudo_trading and self.pseudo_trading:
            return self.pseudo_close(current_price=current_price)

        exchange_obj = self.exchange_cls(coin=self.coin)
        close_volume = self.open_volume
        if not close_volume:
            logger.error(f"平仓时close_volume错误:{close_volume}")
            await Notification.send_catching_exc(msg=f'{self.coin.value}: 平仓时volume错误:{close_volume}')
            return False

        try:
            order_id = None
            future_fn = lambda:exchange_obj.close(quantity=close_volume, long_or_short=self.long_or_short)
            order_id = await auto_retry(future_fn=future_fn, retry_count=3, retry_msg=f'retry 平仓: {self.coin.value}')
        except Exception as e:
            logger.error(f"平仓下单出错. {self.coin.value}. {e}")
            if settings.debug:
                logger.error(traceback.format_exc())
            await Notification.send_catching_exc(msg=f'{self.coin.value}: 平仓下单出错.{e}')
            return False

        # 获取新订单的信息. 新订单的状态会更新
        # 如果获取订单出错则使用此处的值
        order = OrderInExchange(order_id=order_id, price=current_price)
        if order_id:
            try:
                future_fn = lambda:exchange_obj.get_order_info(order_id=order_id)
                order = await auto_retry(future_fn=future_fn, retry_count=3, retry_msg=f'retry get_order_info of {self.coin.value}: {order_id}')
            except Exception as e:
                # 即使获取不到订单问题也不大，因为订单已成交. 而且订单信息主要用来事后分析
                logger.error(f'平仓时获取订单出错: {self.coin.value}, {order_id}. {e}')
                if settings.debug:
                    logger.error(traceback.format_exc())
                await Notification.send_catching_exc(msg=f'{self.coin.value}: 平仓时获取订单出错.{e}')
        else:
            logger.warning('平仓时未获取到order_id')

        # 重新获取账户信息. 更新账户余额
        future_fn = lambda:exchange_obj.get_account_info()
        new_balance = await auto_retry(future_fn=future_fn, infinite=True)

        if self.write_to_db and self.db_id:
            try:
                # 更新数据库
                sql = """update orders set
                    close_price=%s,
                    close_plan_price=%s,
                    close_fee=%s,
                    huobi_close_order_id=%s,
                    balance_after_close=%s,
                    closed=%s,
                    close_time=%s
                where id=%s
                """
                args = [
                    order.trade_avg_price,
                    order.price,
                    order.fee,
                    order_id,
                    new_balance,
                    True,
                    datetime.datetime.now(),
                    self.db_id
                ]
                await db.execute(sql, args=args)
            except Exception as e:
                logger.error(f"平仓时更新数据库出错: {self.coin.value},{order_id}. {e}")
                if settings.debug:
                    logger.error(traceback.format_exc())
                await Notification.send_catching_exc(msg=f'{self.coin.value}: 开仓时更新数据库出错.{e}')

        self.close_price = order.trade_avg_price or order.price
        self.close_time = datetime.datetime.now()
        self.auto_set_profit()

        # 设置 instance 状态
        self.trading = False
        self.balance_before_open = new_balance
        self.open_price = None
        self.open_volume = None
        self.open_time = None
        self.db_id = None

        if settings.debug:
            logger.debug(f'平仓:price:{order.trade_avg_price or order.price}, volume:{close_volume}')
        msg = "`{}`{}`close:{}`     `price:{}`     `volume:{}`".format(
            self.coin.value,
            ' '*(13-len(self.coin.value)),
            self.long_or_short.value,
            order.trade_avg_price or order.price,
            close_volume,
        )
        await Notification.send_catching_exc(msg=msg)
        return True

    async def refresh_balance_before_open(self):
        """刷新余额"""
        future_fn = lambda:self.exchange_cls(coin=self.coin).get_account_info()
        balance = await auto_retry(future_fn=future_fn, infinite=True)
        self.balance_before_open = balance

    def auto_set_profit(self):
        self.profit = None
        if not self.open_price or not self.close_price:
            return
        open_price = float(self.open_price)
        close_price = float(self.close_price)
        if self.long_or_short == LongOrShort.LONG:
            self.profit = (close_price - open_price) / open_price
        elif self.long_or_short == LongOrShort.SHORT:
            self.profit = (open_price - close_price) / open_price
