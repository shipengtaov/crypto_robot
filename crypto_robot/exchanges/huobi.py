"""
交易所 api

## 现货
https://huobiapi.github.io/docs/spot/v1/cn/#urls

### 接入URLs
您可以自行比较使用api.huobi.pro和api-aws.huobi.pro两个域名的延迟情况，选择延迟低的进行使用。
其中，api-aws.huobi.pro域名对使用aws云服务的用户做了一定的链路延迟优化。
REST API
    https://api.huobi.pro
    https://api-aws.huobi.pro
    Websocket Feed（行情，不包含MBP增量行情）
    wss://api.huobi.pro/ws
    wss://api-aws.huobi.pro/ws
    Websocket Feed（行情，仅MBP增量行情）
    wss://api.huobi.pro/feed
    wss://api-aws.huobi.pro/feed
    Websocket Feed（资产和订单）
    wss://api.huobi.pro/ws/v1
    wss://api-aws.huobi.pro/ws/v1

## 合约交易
认证: https://github.com/hbdmapi/huobi_futures_Python/blob/master/alpha/platforms/huobi_swap_api.py

https://huobiapi.github.io/docs/usdt_swap/v1/cn/?shell#0adb1147b3
Q2: 为什么经常出现断线、超时的错误？
如果是在大陆网络环境去请求API接口，网络连接很不稳定，很容易出现超时。建议使用AWS东京C区服务器进行访问。

国内网络可以使用api.btcgateway.pro或者api.hbdm.vn来进行调试,如果仍然无法请求，请在国外服务器上进行运行。

Q3: 为什么WebSocket总是断开连接？
由于网络环境不同，很容易导致websocket断开连接(websocket: close 1006 (abnormal closure))，目前最佳实践是建议您将服务器放置在AWS东京C区，并且使用api.hbdm.vn域名；同时需要做好断连重连操作；行情心跳与订单心跳均需要按照《Websocket心跳以及鉴权接口》的行情心跳与订单心跳回复不同格式的Pong消息：这里。以上操作可以有效减少断连情况。

Q4: api.hbdm.com与api.hbdm.vn有什么区别？
api.hbdm.vn域名使用的是AWS的CDN服务，理论上AWS服务器用户使用此域名会更快更稳定；api.hbdm.com域名使用的是Cloudflare的CDN服务。
"""

import asyncio
import base64
import datetime
import gzip
import hashlib
import hmac
import json
import math
import re
import time
import urllib
from enum import Enum
from typing import Any, Dict, List, NamedTuple, Optional, Tuple
from pprint import pprint

import aiohttp
import attr
import websockets

from .. import settings, exception
from ..common import (
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


class BaseHuobi:
    ACCESS_KEY = settings.huobi_access_key
    SECRET = settings.huobi_secret
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
    def tick_price(cls, data: Dict, realtime:int=None):
        """
        Args:
            realtime: 实时交易时间
        """
        if not isinstance(data, dict):
            return

        if realtime:
            ts = convert_timestamp_to_second_level(realtime)
        else:
            ts = convert_timestamp_to_second_level(data['id'])
        date = datetime.datetime.fromtimestamp(ts)
        open = data['open']
        close = data['close']
        high = data['high']
        low = data['low']
        amount = data['amount']
        vol = data['vol']

        # print(date, open, close, vol)
        return Tick(date=date, timestamp=ts, open=open, close=close, high=high, low=low, vol=vol, amount=amount)

    def get_params_with_signature(self, method, url:str=None, host:str=None, request_path:str=None, params=None):
        """来自：https://github.com/huobiapi/Futures-Python-demo/blob/master/websocket-python3.6-demo/websocket_example.py#L17
        https://github.com/hbdmapi/huobi_futures_Python/blob/master/alpha/platforms/huobi_usdt_swap_api.py
        """
        if not url and not (host and request_path):
            raise Exception('get_params_with_signature 缺少参数')
        method = method.upper()

        host = (host or url).lower()
        if host.startswith('http'):
            host = urllib.parse.urlparse(host).netloc

        request_path = (request_path or url).lower()
        if request_path.startswith('http'):
            request_path = urllib.parse.urlparse(request_path).path

        params = params or {}
        utc_time = datetime.datetime.utcnow()
        signature_params = {
            'AccessKeyId': self.ACCESS_KEY,
            "SignatureMethod": "HmacSHA256",
            "SignatureVersion": "2",
            "Timestamp": utc_time.strftime('%Y-%m-%dT%H:%M:%S'),
            # "Signature": "",
        }
        params.update(signature_params)

        sorted_params = sorted(params.items(), key=lambda d: d[0], reverse=False)
        encode_params = urllib.parse.urlencode(sorted_params)

        payload = [method, host, request_path, encode_params]
        payload = "\n".join(payload)
        payload = payload.encode(encoding="UTF8")
        secret_key = self.SECRET.encode(encoding="utf8")
        digest = hmac.new(secret_key, payload, digestmod=hashlib.sha256).digest()
        signature = base64.b64encode(digest)
        signature = signature.decode()
        params['Signature'] = signature

        return params

    @classmethod
    async def realtime(cls, coin_period_pairs:List[Tuple[BaseCoin, KLinePeriod]]):
        """实时数据"""
        logger.debug(f"calling {cls.coin_type} realtime...")

        if cls.coin_type == 'spot':
            ws_connection = cls.spot_realtime_ws_connection
            subbed_channel = cls.spot_realtime_subbed_channel
        elif cls.coin_type == 'swap':
            ws_connection = cls.swap_realtime_ws_connection
            subbed_channel = cls.swap_realtime_subbed_channel

        logger.debug("connecting websocket...")
        async with websockets.connect(cls.websocket_api) as websocket:
            logger.debug('connected websocket')
            # 登录
            # logger.debug('logging in...')
            # await cls.websocket_auth(ws)

            # 订阅
            for coin_period_pair in coin_period_pairs:
                coin, period = coin_period_pair
                channel = cls.realtime_sub_channel_template.format(coin=coin.value, period=period.value).lower()
                request_data = {
                    "sub": channel,
                    # "id": "huobi-eth-usdt",
                }
                await websocket.send(json.dumps(request_data))
                # response
                # {'id': None, 'status': 'ok', 'subbed': 'market.linkusdt.kline.15min', 'ts': 1623334589624}
                # msg = await websocket.recv()
                # msg_formatted = cls.decode_msg(msg)
                # assert msg_formatted and msg_formatted['status'] == 'ok'
                subbed_channel.add(channel)

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
                if  'ts' not in msg_formatted or 'tick' not in msg_formatted:
                    logger.warning(f'no ts/tick key. {msg_formatted}')
                    continue

                res_channel = msg_formatted['ch']
                coin_str, period_str = cls.get_coin_and_period_from_channel(res_channel)
                if not coin_str or not period_str:
                    logger.error(f"unknown response channel: {res_channel}")
                    continue

                tick = cls.tick_price(msg_formatted['tick'], realtime=msg_formatted['ts'])
                if tick is None:
                    continue

                if not has_reported_ready.get((coin_str, period_str)):
                    logger.debug(f"realtime tick is ready:{coin_str}-{period_str}")
                    has_reported_ready[(coin_str, period_str)] = True

                yield (coin_str, period_str, tick)

    @classmethod
    async def realtime_using_aiohttp(cls, coin_period_pairs:List[Tuple[BaseCoin, KLinePeriod]]):
        """实时数据"""
        logger.debug(f"calling {cls.coin_type} realtime...")

        if cls.coin_type == 'spot':
            ws_connection = cls.spot_realtime_ws_connection
            subbed_channel = cls.spot_realtime_subbed_channel
        elif cls.coin_type == 'swap':
            ws_connection = cls.swap_realtime_ws_connection
            subbed_channel = cls.swap_realtime_subbed_channel

        async with aiohttp.ClientSession(read_timeout=60, conn_timeout=60) as session:
        # async with aiohttp.ClientSession(read_timeout=60*5, conn_timeout=60*5) as session:
            logger.debug("connecting websocket...")
            ws = await session.ws_connect(cls.websocket_api)
            ws_connect = ws

            # 登录
            # logger.debug('logging in...')
            # await cls.websocket_auth(ws)

            # 订阅
            for coin_period_pair in coin_period_pairs:
                coin, period = coin_period_pair
                channel = cls.realtime_sub_channel_template.format(coin=coin.value, period=period.value).lower()
                request_data = {
                    "sub": channel,
                    # "id": "huobi-eth-usdt",
                }
                await ws.send_json(request_data)
                subbed_channel.add(channel)

            has_reported_ready:Dict[Tuple, bool] = dict()
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.binary:
                    res = cls.decode_msg(msg.data)
                    if 'ping' in res:
                        # print('ping: ', res)
                        await ws.send_json(dict(pong=res['ping']))
                        continue
                    if  'ts' not in res or 'tick' not in res:
                        continue

                    res_channel = res['ch']
                    coin_str, period_str = cls.get_coin_and_period_from_channel(res_channel)
                    if not coin_str or not period_str:
                        continue

                    tick = cls.tick_price(res['tick'], realtime=res['ts'])
                    if tick is None:
                        continue

                    if not has_reported_ready.get((coin_str, period_str)):
                        logger.debug(f"realtime tick is ready:{coin_str}-{period_str}")
                        has_reported_ready[(coin_str, period_str)] = True

                    yield (coin_str, period_str, tick)
                elif msg.type == aiohttp.WSMsgType.closed:
                    break
                elif msg.type == aiohttp.WSMsgType.error:
                    break

    @classmethod
    async def get_json_response(cls, response):
        # 返回 headers 为 text/plain, 直接使用 response.json() 会报错
        # res_json = await response.json()
        res_json = json.loads(await response.text())
        return res_json

    @classmethod
    def decode_msg(cls, data):
        if not data:
            return data
        return json.loads(gzip.decompress(data))

    @classmethod
    def get_coin_and_period_from_channel(cls, channel:str):
        """
        >>> f = BaseHuobi.get_coin_and_period_from_channel
        >>> f('market.ethusdt.kline.1min')
        ('ETH', '1min')

        >>> f('market.ETH-usdt.kline.60min')
        ('ETH', '60min')
        """
        pattern = re.compile(r'^market\.(?P<coin>\w+?)\-?usdt\.kline\.(?P<period>.+)$', re.I)
        match = pattern.match(channel)
        if not match:
            return None, None
        coin_str = match.group('coin')
        period_str = match.group('period')
        return coin_str.upper(), period_str.lower()


class HuobiSpot(BaseHuobi):
    """现货交易"""
    coin_type = 'spot'
    websocket_api = settings.spot_websocket_api

    realtime_sub_channel_template = "market.{coin}usdt.kline.{period}"

    def __init__(self, coin: str):
        super().__init__(coin=coin)

    @classmethod
    async def get_all_coins(cls):
        """获取所有支持的合约币"""
        api = settings.spot_all_currency_api
        async with aiohttp.ClientSession() as session:
            response = await session.get(url=api, timeout=15)
            res_json = await cls.get_json_response(response)
            if str(res_json.get('status')) != 'ok' or 'data' not in res_json:
                msg = f"fetch huobi all spot coins error: {res_json}"
                logger.error(msg)
                raise Exception(msg)
            data = res_json['data']
            # 去掉 2,3 倍多和空的币
            pattern = re.compile(r'[23456789][ls]$', re.I)
            coins = [i for i in data if not pattern.search(i)]
            return make_coin_enum_dynamicly_adding(coins, store_cache=True)

    async def get_history(self, period:KLinePeriod, from_:int=None, to:int=None, size:int=None) -> List[Tick]:
        """获取现货历史数据
        https://huobiapi.github.io/docs/spot/v1/cn/#k-2

        Args:
            from_: 开始时间戳. 默认取 5 天前
            to: 结束时间戳

        火币参数说明(每次最多返回300条):
            from: 起始时间 (epoch time in second); 缺省值: 1501174800(2017-07-28T00:00:00+08:00); 取值范围: [1501174800, 2556115200]
            to: 结束时间 (epoch time in second); 缺省值: 2556115200(2050-01-01T00:00:00+08:00); 取值范围: [1501174800, 2556115200] or ($from, 2556115200] if "from" is set
        """
        from_ = from_ or time.time() - 3600*24*5

        logger.debug(f"calling {self.coin_type} history: {self.coin.value}. period:{period.value}")

        async with aiohttp.ClientSession() as session:
            # logger.debug("connecting websocket...")
            ws = await session.ws_connect(self.websocket_api)
            # logger.debug("requesting history...")
            # 请求历史数据
            request_data = {
                "req": self.realtime_sub_channel_template.format(coin=self.coin.value, period=period.value).lower(),
                # "id": "huobi-eth-usdt",
                "from": from_,
                "to": to,
            }
            await ws.send_json(request_data)
            while True:
                ws_msg = await ws.receive()
                res = self.decode_msg(ws_msg.data)
                if 'ping' in res:
                    await ws.send_json(dict(pong=res['ping']))
                    continue
                break
        if str(res.get('status')) != 'ok' or 'data' not in res:
            if res.get('err-msg').lower() == f'invalid symbol {self.coin.value}usdt'.lower():
                raise exception.SymbolPairNotExist(res['err-msg'])
            msg = f"fetch huobi spot history error: {res}"
            logger.error(msg)
            raise Exception(msg)
        ticks = [self.tick_price(d) for d in res['data']]
        return ticks


class HuobiUsdtSwap(BaseHuobi):
    """eth-usdt 永续合约"""
    coin_type = 'swap'
    # api_url = 'wss://www.hbdm.vn/ws'
    websocket_api = settings.swap_websocket_api
    history_api = settings.swap_history_api
    # websocket_api = 'wss://api.btcgateway.pro/linear-swap-ws'

    realtime_sub_channel_template = "market.{coin}-usdt.kline.{period}"

    def __init__(self, coin: str):
        super().__init__(coin=coin)

    @classmethod
    def convert_usdt_to_volume(cls, coin:Coin, usdt:float, current_price:float) -> int:
        """转换 usdt 为张数

        Args:
            coin: 币种. 不同币种转换为张时不同
            usdt: usdt数量
            current_price: 当前价格

        >>> f = HuobiUsdtSwap.convert_usdt_to_volume
        >>> f(Coin.BTC, usdt=100, current_price=100)
        1000

        >>> f(Coin.ETH, usdt=100, current_price=100)
        100
        """
        # 可购买多少个币
        coin_count = usdt/current_price
        volume = None
        if coin == Coin.BTC:
            volume = coin_count * pow(10, 3)
        elif coin == Coin.ETH:
            volume = coin_count * pow(10, 2)
        elif coin == Coin.BCH:
            volume = coin_count * pow(10, 2)
        elif coin == Coin.LTC:
            volume = coin_count * pow(10, 1)
        elif coin == Coin.LINK:
            volume = coin_count * pow(10, 1)
        elif coin == Coin.DOGE:
            volume = coin_count / pow(10, 2)
        else:
            raise Exception(f"币种不支持转为张数: {coin.value}")
        return math.floor(volume)

    @classmethod
    async def get_all_coins(cls):
        """获取所有支持的合约币"""
        api = settings.swap_contract_info_api
        params = {
            # 合约代码，不填查询所有合约
            # "contract_code": "btc-usdt",
            # 合约支持的保证金模式.	cross：仅支持全仓模式；isolated：仅支持逐仓模式；all：全逐仓都支持
            # "support_margin_mode": 
        }
        async with aiohttp.ClientSession() as session:
            response = await session.get(url=api, params=params, timeout=15)
            res_json = await cls.get_json_response(response)
            if str(res_json.get('status')) != 'ok' or 'data' not in res_json:
                msg = f"fetch huobi all coins error: {res_json}"
                logger.error(msg)
                raise Exception(msg)
            data = res_json['data']
            coins = [i['symbol'] for i in data]
            return make_coin_enum_dynamicly_adding(coins)

    async def get_history(self, period:KLinePeriod, size: int = 100) -> List[Tick]:
        """获取历史数据
        https://huobiapi.github.io/docs/usdt_swap/v1/cn/?shell#k

        Args:
            period: 火币可选值: 1min, 5min, 15min, 30min, 60min, 4hour, 1day, 1week, 1mon
            size: 获取数量

        火币参数:
            contract_code: 合约代码. 取值范围 "BTC-USDT" ...
            period: K线类型. 取值范围 1min, 5min, 15min, 30min, 60min, 4hour, 1day, 1week, 1mon
            size: 获取数量，默认150. 取值范围 [1,2000]
            from: 开始时间戳 10位 单位S
            to: 结束时间戳 10位 单位S

            1、size与from&to 必填其一，若全不填则返回空数据。
            2、如果填写from，也要填写to。最多可获取连续两年的数据。
            3、如果size、from、to 均填写，会忽略from、to参数。
        火币返回结果:
            {
                'ch': 'market.BTC-USDT.kline.1min',
                'ts': 1610678310847,
                'status': 'ok', # "ok" , "error"
                'data': [
                    {'id': 1610672340, 'open': 39510, 'close': 39550, 'low': 39510, 'high': 39568, 'amount': 75.692, 'vol': 75692, 'trade_turnover': 2993158.9524, 'count': 725},
                    ...
                ]
            }
        """
        logger.debug(f"calling {self.coin_type} history: {self.coin.value}. period:{period.value}")

        assert period.value in {'1min', '5min', '15min', '30min', '60min', '4hour', '1day', '1week', '1mon'}
        size = size or 100

        params = {
            "contract_code": f"{self.coin.value}-usdt",
            "period": period.value,
            "size": size,
        }
        async with aiohttp.ClientSession() as session:
            response = await session.get(url=self.history_api, params=params, timeout=15)
            res_json = await self.get_json_response(response)
            if str(res_json.get('status')) != 'ok' or 'data' not in res_json:
                msg = f"fetch huobi history error: {res_json}"
                logger.error(msg)
                raise Exception(msg)
            data = res_json['data']
            # data: List[Dict] 中元素越靠近尾部时间越靠后
            assert data[0]['id'] < data[1]['id']
            ticks = [self.tick_price(d) for d in data]
            # print(ticks)
            return ticks

    async def websocket_auth(self, ws):
        """websocket 登录

        https://huobiapi.github.io/docs/usdt_swap/v1/cn/?shell#authentication
        注意：
            - 为了减少已有用户的接入工作量，此处使用了与REST接口同样的签名算法进行鉴权。
            - 请注意大小写
            - 当type为api时，参数op，type，cid，Signature不参加签名计算
            - 此处签名计算中请求方法固定值为GET,其余值请参考REST接口签名算法文档
        """
        data = {
            'op': 'auth',
            'type': 'api',
            # 选填；Client请求唯一ID
            # 'cid': '',
        }
        signature_params = self.get_params_with_signature(
            'GET',
            self.websocket_api,
            '/linear-swap-notification')
        data.update(signature_params)
        await ws.send_json(data)

    async def get_account_info(self, cross:bool=False) -> float:
        """获取用户账户信息
        https://huobiapi.github.io/docs/usdt_swap/v1/cn/?shell#0b91d90b81

        Args:
            cross: 是否全仓
                - False: 逐仓
                - True: 全仓
        """
        # 暂时只支持逐仓
        assert cross is False
        if not cross:
            api = settings.swap_account_info_api
        else:
            api = settings.swap_cross_account_info_api
        data = {
            'contract_code': f'{self.coin.value}-usdt',
        }
        signature_params = self.get_params_with_signature(
            method='POST',
            host=api,
            request_path=urllib.parse.urlparse(api).path)
        async with aiohttp.ClientSession() as session:
            response = await session.post(url=api, params=signature_params, json=data, timeout=10)
            res_json = await self.get_json_response(response)
            if res_json.get('status') != 'ok':
                raise Exception(f'获取火币账户信息错误: {res_json}')
        assert len(res_json['data']) == 1
        account_info = res_json['data'][0]
        # 账户权益
        # print(account_info['margin_balance'])
        # 可用保证金
        margin_available = account_info['margin_available']
        return margin_available

    async def open(self, volume:float, long_or_short:LongOrShort, lever_rate:int):
        """开仓
        暂时只支持开多

        Args:
            volume: 张数
            long_or_short: 做多还是做空
            lever_rate: 杠杆
        """
        volume = int(volume)
        if long_or_short == LongOrShort.LONG:
            direction = 'buy'
            offset = 'open'
        elif long_or_short == LongOrShort.SHORT:
            direction = 'sell'
            offset = 'open'
        # 对手价
        order_price_type = 'optimal_5_fok'
        res = await self.make_swap_order(
            volume=volume,
            direction=direction,
            offset=offset,
            lever_rate=lever_rate,
            order_price_type=order_price_type)
        return res

    async def close(self, volume:float, long_or_short:LongOrShort):
        """暂时使用货币的闪电平仓接口.
        候选: def:make_swap_order

        Args:
            volume(required): 委托数量（张）
            long_or_short: 平多还是平空
        """
        volume = int(volume)
        api = settings.swap_lighting_close_order_api
        if long_or_short == LongOrShort.LONG:
            direction = 'sell'
        elif long_or_short == LongOrShort.SHORT:
            direction = 'buy'
        data = {
            'contract_code': f'{self.coin.value}-usdt',
            'volume': volume,
            'direction': direction,
        }
        signature_params = self.get_params_with_signature(method='POST', url=api)
        async with aiohttp.ClientSession() as session:
            response = await session.post(url=api, params=signature_params, json=data, timeout=15)
            res_json = await self.get_json_response(response)
            if res_json.get('status') != 'ok':
                # {'status': 'error', 'err_code': 1048, 'err_msg': 'Insufficient close amount available.', 'ts': 1611223623102}
                if str(res_json.get('err_code')) == '1048':
                    return
                raise Exception(f'平仓下单出错: {res_json}')
        res_data = res_json['data']
        order_id = res_data.get('order_id') or res_data['order_id_str']
        order_id = str(order_id) if order_id else order_id
        return order_id

    async def make_swap_order(self, volume:float, direction:str, offset:str, lever_rate:int, order_price_type:str) -> str:
        """火币合约下单[逐仓].
        https://huobiapi.github.io/docs/usdt_swap/v1/cn/?shell#0a9b6ea149

        包括:
            - 开多：买入开多(direction用buy、offset用open)
            - 平多：卖出平多(direction用sell、offset用close)
            - 开空：卖出开空(direction用sell、offset用open)
            - 平空：买入平空(direction用buy、offset用close)

        order_price_type: 订单报价类型
            "limit":限价
            "opponent":对手价
            "post_only":只做maker单,post only下单只受用户持仓数量限制,
            optimal_5：最优5档、optimal_10：最优10档、optimal_20：最优20档，
            ioc:IOC订单，
            fok：FOK订单, 
            "opponent_ioc": 对手价-IOC下单，"optimal_5_ioc": 最优5档-IOC下单，"optimal_10_ioc": 最优10档-IOC下单，"optimal_20_ioc"：最优20档-IOC下单，
            "opponent_fok"： 对手价-FOK下单，"optimal_5_fok"：最优5档-FOK下单，"optimal_10_fok"：最优10档-FOK下单，"optimal_20_fok"：最优20档-FOK下单

        返回示例:
            {
                "status": "ok",
                "data": {
                    "order_id": 770323133537685504,
                    "client_order_id": 57012021022,
                    "order_id_str": "770323133537685504"
                },
                "ts": 1603700946949
            }
        """
        api = settings.swap_order_api
        data = {
            'contract_code': f'{self.coin.value}-usdt',
            'volume': volume,
            'direction': direction,
            'offset': offset,
            'lever_rate': lever_rate,
            'order_price_type': order_price_type,
        }
        # print(data)
        signature_params = self.get_params_with_signature(method='POST', url=api)
        async with aiohttp.ClientSession() as session:
            response = await session.post(url=api, params=signature_params, json=data, timeout=15)
            res_json = await self.get_json_response(response)
            if res_json.get('status') != 'ok':
                if str(res_json.get('err_code')) == '1047':
                    raise exception.InsufficientMarginAvailable(res_json.get('err_msg'))
                raise exception.HuobiException(f'下单出错: {res_json}')
        res_data = res_json['data']
        order_id = res_data.get('order_id') or res_data['order_id_str']
        order_id = str(order_id) if order_id else order_id
        return order_id

    async def get_order_info_until_done(self, order_id) -> OrderInExchange:
        """获取订单直到订单为已完成状态"""
        while True:
            order = await self.get_order_info(order_id)
            assert order.status not in {4, 5}
            if order.status in {1, 2, 3, 11}:
                await asyncio.sleep(1)
                continue
            if order.status == 6:
                return order
            if order.status == 7:
                return
            raise exception.HuobiException(f"获取订单时 status 未知: {order.status}")

    async def get_order_info(self, order_id) -> OrderInExchange:
        """获取合约订单信息
        https://huobiapi.github.io/docs/usdt_swap/v1/cn/?shell#630c0b679f

        火币文档中:
            order_id, client_order_id 至少传一个
            status: 订单状态(1准备提交 2准备提交 3已提交 4部分成交 5部分成交已撤单 6全部成交 7已撤单 11撤单中)
        """
        assert order_id
        order_id = str(order_id)
        api = settings.swap_order_info_api
        data = {
            'contract_code': f'{self.coin.value}-usdt',
            'order_id': order_id,
        }
        signature_params = self.get_params_with_signature(method='POST', url=api)
        async with aiohttp.ClientSession() as session:
            response = await session.post(url=api, params=signature_params, json=data, timeout=15)
            res_json = await self.get_json_response(response)
            if res_json.get('status') != 'ok':
                raise Exception(f'获取订单出错: {res_json}')
        assert res_json.get('data')
        res_data = res_json['data'][0]
        order = OrderInExchange(
            order_id=order_id,
            volume=res_data['volume'],
            price=res_data['price'],
            lever_rate=res_data['lever_rate'],
            trade_volume=res_data['trade_volume'],
            trade_avg_price=res_data['trade_avg_price'],
            trade_turnover=res_data['trade_turnover'],
            fee=res_data['fee'],
            status=int(res_data['status']) if res_data['status'] else None,
        )
        return order

    async def get_account_position(self):
        """获取持仓信息[逐仓]
        https://huobiapi.github.io/docs/usdt_swap/v1/cn/?shell#316a79c93e
        """
        api = settings.swap_account_position_api
        data = {
            'contract_code': f'{self.coin.value}-usdt',
        }
        signature_params = self.get_params_with_signature(method='POST', url=api)
        async with aiohttp.ClientSession() as session:
            response = await session.post(url=api, params=signature_params, json=data, timeout=15)
            res_json = await self.get_json_response(response)
            if res_json.get('status') != 'ok':
                raise Exception(f'获取订单出错: {res_json}')
        assert res_json.get('data')
        pprint(res_json, indent=2)

    async def get_open_orders(self):
        """获取未成交的订单/委托订单. 暂时无用
        https://huobiapi.github.io/docs/usdt_swap/v1/cn/?shell#136259e73a
        """
        api = settings.swap_open_orders_api
        data = {
            'contract_code': f'{self.coin.value}-usdt',
            # 'page_index': 1,
            # 'page_size': 20,
        }
        signature_params = self.get_params_with_signature(method='POST', url=api)
        async with aiohttp.ClientSession() as session:
            response = await session.post(url=api, params=signature_params, json=data, timeout=15)
            res_json = await self.get_json_response(response)
            if res_json.get('status') != 'ok':
                raise Exception(f'获取订单出错: {res_json}')
        assert res_json.get('data')
        pprint(res_json, indent=2)


if __name__ == "__main__":
    async def debug_fn():
        from pprint import pprint

        period = KLinePeriod.MIN_1

        async def debug_swap():
            res = None
            huobi = HuobiUsdtSwap(coin=Coin.BTC)
            # res = await huobi.get_history(period)
            async for tick in huobi.realtime(period):
                pprint(tick)
            # res = await huobi.get_account_info()
            # res = await huobi.get_order_info(order_id)
            # res = await huobi.get_account_position()
            # res = [i.value for i in await huobi.get_all_coins()]
            pprint(res)

        async def debug_spot():
            res = None
            huobi = HuobiSpot(coin=Coin.BTC)
            # res = [i.value for i in await HuobiSpot.get_all_coins()]
            res = await huobi.get_history(period)
            async for tick in huobi.realtime([(Coin.BTC, period)]):
                # pprint(tick)
                pass

            pprint(res)

        # await debug_swap()
        await debug_spot()

    loop = asyncio.get_event_loop()
    run_fn = debug_fn()
    loop.run_until_complete(run_fn)
