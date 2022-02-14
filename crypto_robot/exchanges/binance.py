"""
币安

• 现货
    https://binance-docs.github.io/apidocs/spot/cn/

    API 基本信息
    - 接口可能需要用户的 API Key，如何创建API-KEY请参考这里
    - 本篇列出接口的baseurl: https://api.binance.com
    - 如果上面的baseURL访问有性能问题，请访问下面的API集群:
        - https://api1.binance.com
        - https://api2.binance.com
        - https://api3.binance.com
    - 所有接口的响应都是 JSON 格式。
    - 响应中如有数组，数组元素以时间升序排列，越早的数据越提前。
    - 所有时间、时间戳均为UNIX时间，单位为毫秒。

• 币本位
    https://binance-docs.github.io/apidocs/delivery/cn/

"""
import asyncio
import copy
import datetime
import hmac
import hashlib
import json
import math
import re
import time
from decimal import Decimal
from typing import Any, Dict, List, NamedTuple, Optional, Tuple, Union
from urllib.parse import urljoin
from pprint import pprint

import aiohttp
import websockets

from .. import settings, exception
from ..common import (
    BaseEnum,
    BaseCoin,
    Coin,
    KLinePeriod,
    LongOrShort,
    OrderInExchange,
    Tick,
    convert_timestamp_to_second_level,
    exec_with_time_window,
    get_logger,
    make_coin_enum_dynamicly_adding,
)

logger = get_logger()


class OrderStatus(BaseEnum):
    """
    订单状态 (status):
        • NEW 新建订单
        • PARTIALLY_FILLED 部分成交
        • FILLED 全部成交
        • CANCELED 已撤销
        • EXPIRED 订单过期(根据timeInForce参数规则)
        • REJECTED 订单被拒绝(U本位特有)
    """
    NEW = 'NEW'
    PARTIALLY_FILLED = 'PARTIALLY_FILLED'
    FILLED = 'FILLED'
    CANCELED = 'CANCELED'
    EXPIRED = 'EXPIRED'
    REJECTED = 'REJECTED'


class BaseBinance:
    # ACCESS_KEY = settings.binance_access_key
    # SECRET = settings.binance_secret
    coin_type = None
    websocket_api = None

    realtime_sub_channel_template = None

    spot_realtime_ws_connection = None
    spot_realtime_subbed_channel = set()

    swap_realtime_ws_connection = None
    swap_realtime_subbed_channel = set()

    def __init__(self, coin: str):
        self.coin = coin

    @classmethod
    async def get_all_coins(cls) -> List[Coin]:
        pass

    @classmethod
    def tick_price(cls, data: Dict, realtime:int=None, full_data:Any=None):
        """
        Args:
            data: 接口中的 tick
            realtime: 实时交易时间
            full_data: 接口的所有原始数据
        """
        if not isinstance(data, dict):
            return

        if realtime:
            # 可能 realtime > 当前 kline 的最大时间
            ts = min(realtime, data['T'])
        else:
            ts = data['t']
        if data.get('x'):
            ts = data['T']
        ts = convert_timestamp_to_second_level(ts)
        date = datetime.datetime.fromtimestamp(ts)

        event_timestamp = convert_timestamp_to_second_level(realtime) if realtime else None

        open = float((data['o']))
        close = float((data['c']))
        high = float((data['h']))
        low = float((data['l']))
        amount = float((data['q']))
        vol = float((data['v']))
        is_last_one = True if data.get('x') else False

        # print(date, open, close, vol)
        return Tick(timestamp=ts,
                    date=date,
                    event_timestamp=event_timestamp,
                    open=open,
                    close=close,
                    high=high,
                    low=low,
                    vol=vol,
                    amount=amount,
                    is_last_one=is_last_one,
                    # raw_data=full_data
        )

    @classmethod
    async def realtime(cls, coin_period_pairs:List[Tuple[BaseCoin, KLinePeriod]]):
        """实时数据
        
        接口返回:
            {
                "e": "kline",     // 事件类型
                "E": 123456789,   // 事件时间
                "s": "BNBBTC",    // 交易对
                "k": {
                    "t": 123400000, // 这根K线的起始时间
                    "T": 123460000, // 这根K线的结束时间
                    "s": "BNBBTC",  // 交易对
                    "i": "1m",      // K线间隔
                    "f": 100,       // 这根K线期间第一笔成交ID
                    "L": 200,       // 这根K线期间末一笔成交ID
                    "o": "0.0010",  // 这根K线期间第一笔成交价
                    "c": "0.0020",  // 这根K线期间末一笔成交价
                    "h": "0.0025",  // 这根K线期间最高成交价
                    "l": "0.0015",  // 这根K线期间最低成交价
                    "v": "1000",    // 这根K线期间成交量
                    "n": 100,       // 这根K线期间成交笔数
                    "x": false,     // 这根K线是否完结(是否已经开始下一根K线)
                    "q": "1.0000",  // 这根K线期间成交额
                    "V": "500",     // 主动买入的成交量
                    "Q": "0.500",   // 主动买入的成交额
                    "B": "123456"   // 忽略此参数
                }
            }
        """
        logger.debug(f"calling {cls.coin_type} realtime...")

        ws_connection = cls.spot_realtime_ws_connection
        subbed_channel = cls.spot_realtime_subbed_channel

        logger.debug("connecting websocket...")
        async with websockets.connect(cls.websocket_api) as websocket:
            logger.debug('connected websocket')
            # 登录
            # logger.debug('logging in...')
            # await cls.websocket_auth(ws)

            # 订阅
            req_data = {
                "method": "SUBSCRIBE",
                "params": [],
                "id": 1,
            }
            streams = []
            for coin_period_pair in coin_period_pairs:
                coin, period = coin_period_pair
                stream_name = f"{coin.value.lower()}usdt@kline_{KLinePeriod.to_binance_value(period)}"
                streams.append(stream_name)
                subbed_channel.add(stream_name)
            req_data['params'] = streams
            await websocket.send(json.dumps(req_data))

            has_reported_ready:Dict[Tuple, bool] = dict()
            while True:
                msg = await websocket.recv()
                msg_formatted = cls.decode_msg(msg)
                if not isinstance(msg_formatted, dict):
                    logger.warning(f"msg not dict: {msg_formatted}")
                    continue
                if 'ping' in msg_formatted:
                    # print('ping: ', msg_formatted)
                    pong_fn = lambda:logger.debug('sending pong')
                    # pong_fn()
                    exec_with_time_window(key='pong', time_window=3600, callback=pong_fn)
                    await websocket.send(json.dumps(dict(pong=msg_formatted['ping'])))
                    continue
                if  'e' not in msg_formatted or 'k' not in msg_formatted:
                    logger.warning(f'no e/k key. {msg_formatted}')
                    continue

                tick = cls.tick_price(msg_formatted['k'], realtime=msg_formatted['E'], full_data=msg_formatted)
                if tick is None:
                    continue

                coin_str = msg_formatted['s']
                coin_str = re.sub('^(.+?)usdt$', '\\1', coin_str, flags=re.I)
                period_str = msg_formatted['k']['i']
                if not has_reported_ready.get((coin_str, period_str)):
                    logger.debug(f"realtime tick is ready:{coin_str}-{period_str}")
                    has_reported_ready[(coin_str, period_str)] = True

                yield (coin_str, period_str, tick)

    @classmethod
    def decode_msg(cls, data):
        if not data:
            return data
        return json.loads(data)

    @classmethod
    def get_signature(cls, msg:Union[str, bytes, dict]) -> str:
        """
        >>> f = BaseBinance.get_signature
        >>> bool(f("hi"))
        True

        >>> bool(f(dict(name='spt')))
        True
        """
        msg_bytes = None
        if isinstance(msg, str):
            msg_bytes = msg.encode("utf-8")
        elif isinstance(msg, dict):
            # 币安的请求依据 data 参数的传入顺序，不能排序，因为 aiohttp 构造请求时不会排序
            # msg_str = '&'.join([f"{k}={msg[k]}" for k in sorted(msg.keys())])
            msg_str = '&'.join([f"{k}={v}" for k,v in msg.items()])
            msg_bytes = msg_str.encode('utf-8')
        else:
            msg_bytes = msg
        # https://stackoverflow.com/questions/38133665/python-encoded-message-with-hmac-sha256
        return hmac.new(key=settings.binance_secret.encode('utf-8'), msg=msg_bytes, digestmod=hashlib.sha256).hexdigest()

    @classmethod
    def convert_balance_to_volume(cls, coin:Coin, balance, current_price:float=None) -> int:
        """转换 balance 为张数

        来自客服：
        quantity 计算: https://www.binance.com/zh-CN/futures/trading-rules/quarterly
        币本位:
            BTC: 1张100USD, 其余: 1张10USD
        U本位:
            直接使用 usdt

        Args:
            balance: 币本位时为币的数量; U本位时为USDT数量
            current_price【暂时无用】: 当前价格
        """
        return balance


class BinanceSpot(BaseBinance):
    """现货交易"""
    coin_type = 'spot'
    websocket_api = settings.binance_spot_websocket_api
    history_api = settings.binance_spot_history_api

    def __init__(self, coin: str):
        super().__init__(coin=coin)

    async def get_history(self, period:KLinePeriod, from_:int=None, to:int=None, size:int=None) -> List[Tick]:
        """获取现货历史数据
        https://binance-docs.github.io/apidocs/spot/cn/#k

        Args:
            from_: 开始时间戳. 默认取 5 天前
            to: 结束时间戳

        币安说明⬇️：
        参数:
            名称	类型	是否必需	描述
            symbol	STRING	YES	
            interval	ENUM	YES	
            startTime	LONG	NO	
            endTime	LONG	NO	
            limit	INT	NO	默认 500; 最大 1000.
        如果未发送 startTime 和 endTime ，默认返回最近的交易。

        接口返回:
            [
                [
                    1499040000000,      // 开盘时间
                    "0.01634790",       // 开盘价
                    "0.80000000",       // 最高价
                    "0.01575800",       // 最低价
                    "0.01577100",       // 收盘价(当前K线未结束的即为最新价)
                    "148976.11427815",  // 成交量
                    1499644799999,      // 收盘时间
                    "2434.19055334",    // 成交额
                    308,                // 成交笔数
                    "1756.87402397",    // 主动买入成交量
                    "28.46694368",      // 主动买入成交额
                    "17928899.62484339" // 请忽略该参数
                ]
            ]
        """
        # 每次最多取1000条. 不实现分页了
        if period is KLinePeriod.MIN_1:
            default_from = time.time() - 60*100
        elif period is KLinePeriod.MIN_3:
            default_from = time.time() - 60*3*100
        elif period is KLinePeriod.MIN_5:
            default_from = time.time() - 60*5*100
        elif period is KLinePeriod.MIN_15:
            default_from = time.time() - 60*15*100
        elif period is KLinePeriod.MIN_30:
            default_from = time.time() - 60*30*100
        elif period is KLinePeriod.HOUR_1:
            default_from = time.time() - 60*60*100
        else:
            raise Exception(f'binance history api not support period: {period}')

        from_ = int(from_ or default_from)*1000
        if to:
            to = int(to)*1000

        logger.debug(f"calling {self.coin_type} history: {self.coin.value}. period:{period.value}")

        async with aiohttp.ClientSession() as session:
            # 请求历史数据
            params = {
                "symbol": f"{self.coin.value.upper()}USDT",
                "interval": KLinePeriod.to_binance_value(period),
                "startTime": from_,
                "limit": 1000,
            }
            if to:
                params['endTime'] = to
            response = await session.get(self.history_api, params=params)
            res_json = json.loads(await response.text())
        if not isinstance(res_json, list):
            msg = f"fetch binance spot history error: {res_json}"
            logger.error(msg)
            raise Exception(msg)
        ticks = []
        for raw in res_json:
            row = dict(
                t=raw[0],
                o=raw[1],
                h=raw[2],
                l=raw[3],
                c=raw[4],
                v=raw[5],
                T=raw[6],
                q=raw[7],
                n=raw[8],
                V=raw[9],
                Q=raw[10],
                B=raw[11],
            )
            tick = self.tick_price(row)
            ticks.append(tick)
        return ticks


class BinanceCoinBasedSwap(BaseBinance):
    """币本位合约"""
    BALANCE_API = settings.binance_coin_based_swap_balance_api
    # BALANCE_API = settings.binance_coin_based_swap_balance_api_test
    ORDER_API = settings.binance_coin_based_swap_order_api
    # ORDER_API = settings.binance_coin_based_swap_order_api_test

    DEFAULT_API_KEY_HEADERS = {
        'X-MBX-APIKEY': settings.binance_access_key
    }

    @classmethod
    def convert_balance_to_volume(cls, coin:Coin, balance, current_price) -> int:
        """
        >>> f = BinanceCoinBasedSwap.convert_balance_to_volume
        >>> f(Coin.BTC, balance=100, current_price=1)
        1

        >>> f(Coin.ETH, balance=100, current_price=1)
        10
        """
        usdt = balance * current_price

        # 可购买多少个币
        volume = None
        if coin == Coin.BTC:
            volume = usdt/100
        else:
            volume = usdt/10
        # elif coin == Coin.ETH:
        #     volume = usdt/10
        # elif coin == Coin.UNI:
        #     volume = usdt/10
        # elif coin == Coin.ADA:
        #     volume = usdt/10
        # elif coin == Coin.BCH:
        #     volume = usdt/10
        # elif coin == Coin.LTC:
        #     volume = usdt/10
        # elif coin == Coin.LINK:
        #     volume = usdt/10
        # elif coin == Coin.BNB:
        #     volume = usdt/10
        # else:
        #     raise Exception(f"币种不支持转为张数: {coin.value}")
        return math.floor(volume)

    async def get_account_info(self, target_asset:str=None) -> float:
        """获取用户账户信息
        https://binance-docs.github.io/apidocs/delivery/cn/#user_data-7
        """
        target_asset = target_asset or self.coin.value.upper()
        params = {
            'timestamp': int(time.time()*1000),
        }
        params['signature'] = self.get_signature(params)
        async with aiohttp.ClientSession() as session:
            response = await session.get(url=self.BALANCE_API, headers=self.DEFAULT_API_KEY_HEADERS, params=params, timeout=10)
            res_json = self.decode_msg(await response.text())
            if not isinstance(res_json, list):
                raise Exception(f'获取币安账户信息错误: {res_json}')
        available_balance = None
        for i in res_json:
            if i.get('asset', '').upper() == target_asset:
                available_balance = float(i.get('availableBalance'))
                break
        return available_balance

    @property
    def order_symbol(self):
        return f'{self.coin.value.upper()}USD_PERP'

    async def open(self, quantity:int, long_or_short:LongOrShort) -> str:
        """开仓

        https://binance-docs.github.io/apidocs/delivery/cn/#trade-2

        Args:
            quantity: 下单数量. 必须是整型，因为币安开合约为张数
            long_or_short: 做多还是做空
        """
        data = {
            # 市价单
            'type': 'MARKET',
            'quantity': quantity,
        }
        if long_or_short == LongOrShort.LONG:
            data.update(dict(
                side='BUY',
                positionSide='LONG',
            ))
        elif long_or_short == LongOrShort.SHORT:
            data.update(dict(
                side='SELL',
                positionSide='SHORT',
            ))
        # 对手价
        res = await self.make_swap_order(data)
        return res

    async def close(self, quantity:int, long_or_short:LongOrShort) -> str:
        """平仓

        https://binance-docs.github.io/apidocs/delivery/cn/#trade-2

        Args:
            quantity: 平仓数量. 必须是整型，因为币安开合约为张数
            long_or_short: 做多还是做空
        """
        data = {
            # 市价单
            'type': 'MARKET',
            'quantity': quantity,
        }
        if long_or_short == LongOrShort.LONG:
            data.update(dict(
                side='SELL',
                positionSide='LONG',
            ))
        elif long_or_short == LongOrShort.SHORT:
            data.update(dict(
                side='BUY',
                positionSide='SHORT',
            ))
        # 对手价
        res = await self.make_swap_order(data)
        return res

    async def make_swap_order(self, data:Dict[str, Any]) -> str:
        """币安币本位合约下单
        https://binance-docs.github.io/apidocs/delivery/cn/#trade-2

        https://stackoverflow.com/questions/63963411/what-are-the-symbols-used-in-binances-dapi-coin-futures-api
        永续合约的 symbol: BTCUSD_PERP
        > If anyone is interested, I found out that you can get a list of all symbols 
        > using: GET /dapi/v1/exchangeInfo​. The BTC/USD perpetual futures one is: BTCUSD_PERP.

        # 不同的币需要不同的 precision
        https://dapi.binance.com/dapi/v1/exchangeInfo

        有效方式 (timeInForce):
            GTC - Good Till Cancel 成交为止
            IOC - Immediate or Cancel 无法立即成交(吃单)的部分就撤销
            FOK - Fill or Kill 无法全部立即成交就撤销
            GTX - Good Till Crossing 无法成为挂单方就撤销

        返回示例:
            {
                "clientOrderId": "testOrder", // 用户自定义的订单号
                "cumQty": "0",
                "cumBase": "0", // 成交额(标的数量)
                "executedQty": "0", // 成交量(张数)
                "orderId": 22542179, // 系统订单号
                "avgPrice": "0.0",      // 平均成交价
                "origQty": "10", // 原始委托数量
                "price": "0", // 委托价格
                "reduceOnly": false, // 仅减仓
                "closePosition": false,   // 是否条件全平仓
                "side": "SELL", // 买卖方向
                "positionSide": "SHORT", // 持仓方向
                "status": "NEW", // 订单状态
                "stopPrice": "0", // 触发价,对`TRAILING_STOP_MARKET`无效
                "symbol": "BTCUSD_200925", // 交易对
                "pair": "BTCUSD",   // 标的交易对
                "timeInForce": "GTC", // 有效方法
                "type": "TRAILING_STOP_MARKET", // 订单类型
                "origType": "TRAILING_STOP_MARKET",  // 触发前订单类型
                "activatePrice": "9020", // 跟踪止损激活价格, 仅`TRAILING_STOP_MARKET` 订单返回此字段
                "priceRate": "0.3", // 跟踪止损回调比例, 仅`TRAILING_STOP_MARKET` 订单返回此字段
                "updateTime": 1566818724722, // 更新时间
                "workingType": "CONTRACT_PRICE", // 条件价格触发类型
                "priceProtect": false            // 是否开启条件单触发保护
            }
        """
        api = self.ORDER_API
        payload = copy.deepcopy(data)
        if 'symbol' not in payload:
            # 永续合约
            payload['symbol'] = self.order_symbol
        if 'timestamp' not in payload:
            payload['timestamp'] = int(time.time()*1000)
        # type 为 MARKET 市价时，timeInForce 不能传，否则报错
        # if 'timeInForce' not in payload:
        #     payload['timeInForce'] = 'FOK'

        payload['signature'] = self.get_signature(payload)
        pprint(payload)
        async with aiohttp.ClientSession() as session:
            response = await session.post(url=api, headers=self.DEFAULT_API_KEY_HEADERS, data=payload, timeout=15)
            res_json = self.decode_msg(await response.text())
            if not isinstance(res_json, dict):
                raise exception.ExchangeException(f'下单出错: {res_json}')
            if str(res_json.get('code')) == '-2019':
                raise exception.InsufficientMarginAvailable(res_json.get('msg'))
            if not res_json.get('executedQty'):
                raise exception.ExchangeException(f'下单出错: {res_json}')
        order = OrderInExchange(
            order_id=res_json.get('orderId'),
            trade_volume=res_json.get('executedQty'),
            trade_avg_price=res_json.get('avgPrice'),
        )
        return order.order_id

    async def get_order_info_until_done(self, order_id) -> OrderInExchange:
        """获取订单直到订单为已完成状态"""
        while True:
            order = await self.get_order_info(order_id)
            if order.status == OrderStatus.NEW:
                await asyncio.sleep(1)
                continue
            elif order.status in {OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED}:
                return order
            elif order.status in {OrderStatus.CANCELED, OrderStatus.EXPIRED}:
                return
            # U本位特有的 status
            elif order.status == OrderStatus.REJECTED:
                return
            else:
                raise exception.HuobiException(f"获取订单时 status 未知: {order.status}")

    async def get_order_info(self, order_id) -> OrderInExchange:
        """获取合约订单信息

        https://binance-docs.github.io/apidocs/delivery/cn/#user_data-3

        币安文档中:
            至少需要发送 orderId 与 origClientOrderId中的一个
            订单状态 (status):
                • NEW 新建订单
                • PARTIALLY_FILLED 部分成交
                • FILLED 全部成交
                • CANCELED 已撤销
                • EXPIRED 订单过期(根据timeInForce参数规则)
        """
        assert order_id
        order_id = str(order_id)
        api = self.ORDER_API
        params = {
            'symbol': self.order_symbol,
            'orderId': order_id,
            'timestamp': int(time.time()*1000),
        }
        params['signature'] = self.get_signature(params)
        async with aiohttp.ClientSession() as session:
            response = await session.get(url=api, headers=self.DEFAULT_API_KEY_HEADERS, params=params, timeout=15)
            res_json = self.decode_msg(await response.text())
            if not isinstance(res_json, dict) or not res_json.get('orderId'):
                raise Exception(f'获取订单出错: {res_json}')
        order = OrderInExchange(
            order_id=order_id,
            volume=res_json['origQty'],
            price=res_json['price'],
            trade_volume=res_json['executedQty'],
            trade_avg_price=res_json['avgPrice'],
            # 币本位: cumBase, U本位: cumQuote
            trade_turnover=res_json.get('cumBase') or res_json.get('cumQuote'),
            status=OrderStatus.from_string(res_json.get('status')),
        )
        return order


class BinanceUsdtSwap(BinanceCoinBasedSwap):
    """U本位合约"""
    BALANCE_API = settings.binance_usdt_based_swap_balance_api
    ORDER_API = settings.binance_usdt_based_swap_order_api

    @classmethod
    def convert_balance_to_volume(cls, coin:Coin, balance:float, current_price:float) -> Union[int, float]:
        """
        https://fapi.binance.com/fapi/v1/exchangeInfo 其中的 filters: filterType: 'LOT_SIZE', stepSize

        >>> f = BinanceUsdtSwap.convert_balance_to_volume
        >>> f(coin=Coin.ETH, balance=12*5, current_price=3626)
        0.016

        >>> f(coin=Coin.UNI, balance=12*5, current_price=30)
        1
        """
        # 这里担心最后计算出的数量不足以开单
        usdt = balance * 0.98
        # 可购买多少个币
        coin_count = usdt / current_price
        step_size = None
        if coin in {Coin.BTC, Coin.ETH, Coin.BCH, Coin.LTC, Coin.DASH}:
            step_size = 3
        elif coin in {Coin.LINK, Coin.BNB}:
            step_size = 2
        elif coin in {Coin.XRP, Coin.EOS, Coin.DOT}:
            step_size = 1
        elif coin in {Coin.ADA, Coin.UNI, Coin.SUSHI, Coin.DOGE}:
            step_size = 0
        else:
            raise Exception(f"币种不支持转为张数: {coin.value}")
        split = str(coin_count).split('.', maxsplit=1)
        if len(split) <= 1:
            return coin_count
        val = '{}.{}'.format(split[0], split[1][:step_size])
        if int(float(val)) == float(val):
            return int(float(val))
        return float(val)

    @property
    def order_symbol(self):
        return f'{self.coin.value.upper()}USDT'

    async def get_account_info(self, target_asset:str='USDT') -> float:
        return await super().get_account_info(target_asset=target_asset)

if __name__ == "__main__":
    async def debug_fn():
        from pprint import pprint

        period = KLinePeriod.MIN_15

        async def debug_spot():
            res = None
            obj = BinanceSpot(coin=Coin.ETH)
            # res = [i.value for i in await BinanceSpot.get_all_coins()]
            res = await obj.get_history(period)
            # async for tick in obj.realtime([(Coin.ETH, period)]):
            #     pprint(tick)

            pprint(res)

        async def debug_balance():
            res = await BinanceCoinBasedSwap(coin=Coin.ETH).get_account_info()
            print("币本位:")
            pprint(res)

            res = await BinanceUsdtSwap(coin=Coin.ETH).get_account_info()
            print("U本位:")
            pprint(res)

        async def debug_open_order():
            # res = await BinanceCoinBasedSwap(coin=Coin.ETH).open(quantity=1, long_or_short=LongOrShort.LONG)
            # pprint(res)

            # res = await BinanceUsdtSwap(coin=Coin.ETH).open(quantity=0.016, long_or_short=LongOrShort.LONG)
            # res = await BinanceUsdtSwap(coin=Coin.ETH).close(quantity=0.016, long_or_short=LongOrShort.LONG)
            # pprint(res)
            pass

        async def debug_get_order():
            # order_id = '3766630506'
            # # res = await BinanceCoinBasedSwap(coin=Coin.ETH).get_order_info(order_id)
            # res = await BinanceCoinBasedSwap(coin=Coin.ETH).get_order_info_until_done(order_id)
            # pprint(res)

            order_id = '8389765507105157472'
            res = await BinanceUsdtSwap(coin=Coin.ETH).get_order_info_until_done(order_id)
            pprint(res)

        # await debug_swap()
        await debug_spot()
        # await debug_balance()
        # await debug_open_order()
        # await debug_get_order()

    loop = asyncio.get_event_loop()
    run_fn = debug_fn()
    loop.run_until_complete(run_fn)
