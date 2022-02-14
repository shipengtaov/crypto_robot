"""
"""

import asyncio
import time
import traceback
from typing import Dict, List, Tuple, Union

import aiohttp.web

from .common import (
    BaseCoin,
    BaseCoinSpot,
    BaseCoinSwap,
    Coin,
    CoinSwap,
    KLinePeriod,
    LongOrShort,
    convert_timestamp_to_minute_level,
    get_coin_lever,
    get_logger,
    make_coin_enum_dynamicly_adding,
)
from .exception import SymbolPairNotExist
from . import coin_config, exchanges, settings, server
from .kline import KLineQueueContainer
from .notification import Notification
from .strategy import TowerOfBabel
from .trader import Trader

logger = get_logger()


class Robot:
    def __init__(self, consider_pseudo_trading:bool=False):
        self.strategy_cls = TowerOfBabel

        # 交易的币种
        self.trade_coins = dict()
        # 交易
        self.traders:Dict[BaseCoin, Trader] = dict()

        # 发送通知的币种
        self.notify_coins = dict()
        # 未发生真实交易
        self.traders_for_notify:Dict[BaseCoin, Trader] = dict()

        self.consider_pseudo_trading = consider_pseudo_trading

        # 所有币种的 kline 队列
        self.kline_containers: Dict[BaseCoin, KLineQueueContainer] = dict()

        # 每个币的配置
        self.coin_config = None
        self.read_coin_config()

        # 价格提醒
        self.send_notify_log: Dict[Tuple[Coin, LongOrShort], int] = dict()

        # 发送是否健康
        self.health_report_log: Dict[Coin, int] = dict()
        # 与上次间隔至少 1 小时
        self.health_report_interval = 60*60*1
        # 只在几点提醒
        self.health_report_only_hours: List[int] = [7, 12, 18, 22]

        # 设置不存在的值，不发送健康消息
        self.health_report_only_hours: List[int] = [99]

        # 几点的时候不发送消息打扰我. 早上 2:00 ~ 6:00
        self.health_report_exclude_hours = [2, 3, 4, 5]

        self.check_before_run()

    def read_coin_config(self, force:bool=False):
        if self.coin_config and not force:
            return coin_config
        self.coin_config = coin_config.format_raw_config(coin_config.raw_config)
        self.trade_coins = self.coin_config['trade']
        self.notify_coins = self.coin_config['notify']
        self.all_coins = set(list(self.trade_coins.keys()) + list(self.notify_coins.keys()))

    def check_before_run(self):
        """运行之前检查潜在的问题

        包括:
        - 检查是否支持转换对应币种在合约中的张数
        """
        for coin in self.trade_coins:
            # exchanges.HuobiUsdtSwap.convert_usdt_to_volume(coin=coin, usdt=1, current_price=1)
            exchanges.BinanceUsdtSwap.convert_balance_to_volume(coin=coin, balance=1, current_price=1)

            get_coin_lever(coin)

    async def init(self):
        """初始化

        - 读取数据库中正在交易的记录
        """
        if self.trade_coins:
            self.traders = await Trader.init_traders(coins=self.trade_coins, consider_pseudo_trading=self.consider_pseudo_trading)
        # for coin in self.notify_coins:
        #     self.traders_for_notify[coin] = Trader(coin=coin, trading=False)

        # 如果需要 notify_all 则需要获取所有币种
        if self.coin_config.get('notify_all'):
            # await exchanges.HuobiSpot.get_all_coins()
            await exchanges.BinanceSpot.get_all_coins()
            self.read_coin_config(force=True)

        for coin, config in list(self.trade_coins.items()) + list(self.notify_coins.items()):
            self.kline_containers.setdefault(coin, KLineQueueContainer(coin=coin, periods=config['periods']))

    async def run(self):
        await self.init()

        # 先统一获取历史, 再获取实时数据
        # 历史数据
        run_coins = set()
        for coin in self.all_coins:
            kline_container = self.kline_containers[coin]
            while True:
                try:
                    await kline_container.tick_history()
                    break
                except Exception as e:
                    logger.warning(f"get history error: {coin.value}. {traceback.format_exc()}")
                    await asyncio.sleep(3)

            # 价格过低的币忽略提醒
            consider_ignore_notify = False
            current_price = kline_container.current_price
            min_price = self.coin_config.get('ignore_coin_if_price_less_than')
            if min_price and current_price < min_price:
                consider_ignore_notify = True

            if (consider_ignore_notify
                and coin in self.notify_coins
                and coin not in self.trade_coins
            ):
                logger.debug(f"ignore coin: {coin.value}. {current_price} < {min_price}")
                continue
            run_coins.add(coin)

        logger.debug("realtime coins: {}".format(','.join([i.value for i in list(run_coins)[:50]])))

        # 实时数据
        spot_coin_period_pairs = []
        swap_coin_period_pairs = []
        for coin in run_coins:
            kline_container = self.kline_containers[coin]
            for period in kline_container.periods:
                if isinstance(coin, BaseCoinSpot):
                    spot_coin_period_pairs.append((coin, period))
                elif isinstance(coin, BaseCoinSwap):
                    swap_coin_period_pairs.append((coin, period))

        try:
            tasks = []
            if spot_coin_period_pairs:
                tasks.append(self.run_realtime(coin_type='spot', coin_period_pairs=spot_coin_period_pairs))
            if swap_coin_period_pairs:
                tasks.append(self.run_realtime(coin_type='swap', coin_period_pairs=swap_coin_period_pairs))
            await asyncio.gather(*tasks)
        finally:
            # https://docs.aiohttp.org/en/stable/faq.html#can-a-handler-receive-incoming-events-from-different-sources-in-parallel
            [task.cancel() for task in tasks]

    async def run_realtime(self, coin_type:str, coin_period_pairs:List):
        if coin_type == 'spot':
            exchange_cls = exchanges.BinanceSpot
        elif coin_type == 'swap':
            exchange_cls = exchanges.BinanceUsdtSwap
        while True:
            try:
                logger.debug(f"running realtime...")
                async for tick_coin_str, tick_period_str, tick in exchange_cls.realtime(coin_period_pairs=coin_period_pairs):
                    coin = make_coin_enum_dynamicly_adding().from_string(tick_coin_str)
                    period = KLinePeriod.from_string(tick_period_str)
                    assert coin
                    assert period

                    if len(coin_period_pairs) >= 15:
                        sleep_before_send = 1
                    else:
                        sleep_before_send = None
                    await self.send_health(coin, sleep_before_send=sleep_before_send)

                    kline_container = self.kline_containers[coin]
                    kline_container.tick(tick, period=period)

                    # print(tick_coin_str, tick_period_str, tick)

                    # 交易
                    if coin in self.trade_coins:
                        await self.run_trade(coin)
                    # 价格提醒
                    if coin in self.notify_coins:
                        await self.run_notification(coin)
            except KeyboardInterrupt as e:
                raise e
            except SymbolPairNotExist as e:
                logger.debug(f"symbol pair not exist:{e}")
                break
            except Exception as e:
                logger.error(tick_period_str)
                logger.error(f"realtime error")
                logger.error(traceback.format_exc())
                await asyncio.sleep(5)
                continue

    async def run_trade(self, coin: Coin):
        """进行交易"""
        trader = self.traders.get(coin)
        if trader is None:
            return
        if not trader.can_i_trade:
            return

        kline_container = self.kline_containers[coin]
        current_price = kline_container.current_price

        # 开仓
        if not trader.trading:
            # 做多
            if LongOrShort.LONG in self.trade_coins[coin]['long_or_short']:
                for strategy_cls in self.trade_coins[coin]['strategies']:
                    strategy = strategy_cls(kline_queue_container=kline_container)
                    if strategy.should_open_long():
                        # logger.debug(f'opening long:{coin.value}')
                        await trader.open(long_or_short=LongOrShort.LONG, current_price=current_price)
                        return
                    elif settings.debug_strategy:
                        logger.debug(f"debug open long({coin.value}): {strategy.desc_if_not_open or ''}")
            # 做空
            if LongOrShort.SHORT in self.trade_coins[coin]['long_or_short']:
                for strategy_cls in self.trade_coins[coin]['strategies']:
                    strategy = strategy_cls(kline_queue_container=kline_container)
                    if strategy.should_open_short():
                        # logger.debug(f'opening short:{coin.value}')
                        await trader.open(long_or_short=LongOrShort.SHORT, current_price=current_price)
                        return
                    elif settings.debug_strategy:
                        logger.debug(f"debug open short({coin.value}): {strategy.desc_if_not_open or ''}")
        # 平仓
        else:
            # 平多
            if trader.long_or_short == LongOrShort.LONG:
                for strategy_cls in self.trade_coins[coin]['strategies']:
                    strategy = strategy_cls(kline_queue_container=kline_container, trader=trader)
                    if strategy.should_close_long():
                        logger.debug(f'closing long:{coin.value}')
                        await trader.close(current_price=current_price)
                    elif settings.debug_strategy:
                        logger.debug(f"close-long({coin.value}): {strategy.desc_if_not_close}")
            # 平空
            elif trader.long_or_short == LongOrShort.SHORT:
                for strategy_cls in self.trade_coins[coin]['strategies']:
                    strategy = strategy_cls(kline_queue_container=kline_container, trader=trader)
                    if strategy.should_close_short():
                        logger.debug(f'closing short:{coin.value}')
                        await trader.close(current_price=current_price)
                    elif settings.debug_strategy:
                        logger.debug(f"close-short({coin.value}): {strategy.desc_if_not_close}")

    async def run_notification(self, coin: Coin):
        """价格提醒"""
        # 提前检查是否最近已发送通知，防止占用cpu
        last_notify_time_long = self.send_notify_log.get((coin, LongOrShort.LONG))
        last_notify_time_short = self.send_notify_log.get((coin, LongOrShort.SHORT))
        if last_notify_time_long and time.time() - last_notify_time_long < 60 and last_notify_time_short and time.time() - last_notify_time_short < 60:
            return

        kline_container = self.kline_containers[coin]
        if self.coin_config.get('notify_all'):
            buffer_seconds = 10
        else:
            buffer_seconds = None
        notify_time_gap = self.notify_coins[coin].get('notify_time_gap')

        # 开仓
        # 做多
        if LongOrShort.LONG in self.notify_coins[coin]['long_or_short']:
            for strategy_cls in self.notify_coins[coin]['strategies']:
                webhook_url = getattr(strategy_cls, 'webhook_url', None)
                notify_extra_key = getattr(strategy_cls, 'notify_extra_key', None)
                strategy = strategy_cls(kline_queue_container=kline_container)
                if strategy.should_open_long():
                    # msg = f"notify open long({period.value}|{strategy.nickname}): {strategy.desc}"
                    msg = "`{}`-{}{}`long`{}`{}`\n>{}".format(
                        coin.value,
                        strategy.nickname,
                        ' '*(13-len(coin.value)),
                        ' '*9,
                        strategy.score,
                        strategy.desc,
                    )
                    await self.send_notify(
                        coin,
                        long_or_short=LongOrShort.LONG,
                        msg=msg,
                        notify_time_gap=notify_time_gap,
                        buffer_seconds=buffer_seconds,
                        notify_extra_key=notify_extra_key,
                        frequency_control=True,
                        webhook_url=webhook_url)
                elif settings.debug_strategy:
                    logger.debug(f"debug open long({coin.value}): {strategy.desc_if_not_open or ''}")
        # 做空
        if LongOrShort.SHORT in self.notify_coins[coin]['long_or_short']:
            for strategy_cls in self.notify_coins[coin]['strategies']:
                webhook_url = getattr(strategy_cls, 'webhook_url', None)
                notify_extra_key = getattr(strategy_cls, 'notify_extra_key', None)
                strategy = strategy_cls(kline_queue_container=kline_container)
                if strategy.should_open_short():
                    # msg = f"notify open short({period.value}|{strategy.nickname}): {strategy.desc}"
                    msg = "`{}`-{}{}`short`{}`{}`\n>{}".format(
                        coin.value,
                        strategy.nickname,
                        ' '*(13-len(coin.value)),
                        ' '*8,
                        strategy.score,
                        strategy.desc,
                    )
                    await self.send_notify(
                        coin,
                        long_or_short=LongOrShort.SHORT,
                        msg=msg,
                        notify_time_gap=notify_time_gap,
                        buffer_seconds=buffer_seconds,
                        notify_extra_key=notify_extra_key,
                        frequency_control=True,
                        is_short_notification=True,
                        webhook_url=webhook_url)
                elif settings.debug_strategy:
                    logger.debug(f"debug open short({coin.value}): {strategy.desc_if_not_open or ''}")

    async def run_notification_pseudo_trade(self, coin: Coin):
        """价格提醒. 模拟真实交易"""
        trader = self.traders_for_notify.get(coin)
        if trader is None:
            return
        # TODO(2021.06.25 00:07): 这里有问题, kline_containers, self.strategy_cls
        kline_queue = self.kline_containers[coin]
        current_price = kline_queue.queue[-1].close
        strategy = self.strategy_cls(trader=trader)

        # 开仓
        # 做多
        if not trader.trading and coin in self.notify_coins_long:
            if strategy.should_open_long(kline_queue):
                await self.send_notify(coin, msg=f"{coin.value}:notify-open-long:{current_price}\n{strategy.nickname}")
                trader.pseudo_open(LongOrShort.LONG, current_price=current_price)
                return
            elif settings.debug_strategy:
                logger.debug(f"debug-open-long({coin.value}): {strategy.desc_if_not_open}")
        # 做空
        if not trader.trading and coin in self.notify_coins_short:
            if strategy.should_open_short(kline_queue):
                await self.send_notify(coin, msg=f"{coin.value}:notify-open-short:{current_price}\n{strategy.nickname}")
                trader.pseudo_open(LongOrShort.SHORT, current_price=current_price)
                return
            elif settings.debug_strategy:
                logger.debug(f"debug-open-short({coin.value}): {strategy.desc_if_not_open}")
        # 平仓
        if trader.trading:
            # 做多
            if trader.long_or_short == LongOrShort.LONG:
                if strategy.should_close_long(kline_queue):
                    await self.send_notify(coin, msg=f"{coin.value}:notify-close-long:profit:{trader.profit} | {current_price}\n{strategy.nickname}")
                    trader.pseudo_close(current_price=current_price)
                elif settings.debug_strategy:
                    logger.debug(f"debug-close-long({coin.value}): {strategy.desc_if_not_close}")
            # 做空
            elif trader.long_or_short == LongOrShort.SHORT:
                if strategy.should_close_short(kline_queue):
                    await self.send_notify(coin, msg=f"{coin.value}:notify-close-short:profit:{trader.profit} | {current_price}\n{strategy.nickname}")
                    trader.pseudo_close(current_price=current_price)
                elif settings.debug_strategy:
                    logger.debug(f"debug-close-short({coin.value}): {strategy.desc_if_not_close}")

    async def send_notify(self,
                          coin: Coin,
                          msg: str,
                          long_or_short:LongOrShort=None,
                          is_short_notification:bool=False,
                          webhook_url:str=None,
                          notify_time_gap:int=60*30,
                          buffer_seconds:int=None,
                          notify_extra_key:str=None,
                          frequency_control:bool=False):
        """发送通知

        Args:
            frequency_control: 是否控制发送频率
        """
        notify_time_gap = notify_time_gap or 60*30
        now = time.time()

        frequency_key = [coin, long_or_short] if long_or_short else [coin]
        if notify_extra_key:
            frequency_key.append(notify_extra_key)
        frequency_key = tuple(frequency_key)

        if frequency_control and self.send_notify_log.get(frequency_key) and now - self.send_notify_log.get(frequency_key) < notify_time_gap:
            return
        self.send_notify_log[frequency_key] = now
        await Notification.send_catching_exc(
            msg,
            webhook_url=webhook_url,
            is_short_notification=is_short_notification,
            buffer_seconds=buffer_seconds,
            random_emoji=False)

    async def send_health(self, coin: Coin, sleep_before_send:int=None):
        """发送健康消息
        Args:
            sleep_before_send: 发送消息前是否 sleep. 防止需要监控的 coin 过多时，一次发送过多消息给钉钉的话会被钉钉限制
        """
        now = time.time()
        date_minute = convert_timestamp_to_minute_level(now)
        if self.health_report_exclude_hours and date_minute.hour in self.health_report_exclude_hours:
            return
        if self.health_report_only_hours and date_minute.hour not in self.health_report_only_hours:
            return
        if self.health_report_log.get(coin) and now - self.health_report_log.get(coin) < self.health_report_interval:
            # print('interval: ', self.health_report_log.get(coin), now - self.health_report_log.get(coin))
            return
        self.health_report_log[coin] = now
        if not sleep_before_send:
            logger.debug(f'sending healthy: {coin.value}')
            await Notification.send_catching_exc(msg=f"{coin.value}: I'm healthy", random_emoji=False)
            return

        async def callback():
            await asyncio.sleep(sleep_before_send)
            logger.debug(f'sending healthy: {coin.value}')
            await Notification.send_catching_exc(msg=f"{coin.value}: I'm healthy", random_emoji=False)
        await asyncio.gather(callback())


def main():
    from argparse import ArgumentParser
    parser = ArgumentParser()
    parser.add_argument('--skip-first-trade', action='store_true', help='是否忽略第一次交易')
    parser.add_argument('--port', type=int, default='8000', help='钉钉服务器端口号.默认:8000')
    args = parser.parse_args()

    loop = asyncio.get_event_loop()
    robot = Robot(consider_pseudo_trading=args.skip_first_trade)
    async def run_robot_loop(robot):
        while True:
            try:
                await robot.run()
            except KeyboardInterrupt as e:
                raise e
            except Exception:
                logger.error(traceback.format_exc())
                await asyncio.sleep(1)
                logger.warning('re-run robot.run...')
                robot = Robot(consider_pseudo_trading=args.skip_first_trade)
                server.set_trade_info(robot=robot)
    asyncio.ensure_future(run_robot_loop(robot=robot))

    server.set_trade_info(robot=robot)
    asyncio.ensure_future(aiohttp.web._run_app(server.app, host='0.0.0.0', port=args.port))
    loop.run_forever()

if __name__ == "__main__":
    main()
