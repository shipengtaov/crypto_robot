import asyncio
import base64
import datetime
import hashlib
import hmac
import re
import time
from functools import partial

from aiohttp import web

from . import settings
from .common import Coin, convert_timestamp_to_second_level
from . import notification


class DingDingMessageView(web.View):
    async def post(self):
        """自动回复钉钉消息
        https://developers.dingtalk.com/document/app/develop-enterprise-internal-robots
        https://open-dev.dingtalk.com/

        HTTP body 例子:
            {
                "msgtype": "text", 
                "text": {
                    "content": "我就是我, 是不一样的烟火"
                }, 
                "msgId": "XXXX", 
                "createAt": 1487561654123,
                "conversationType": "2", 
                "conversationId": "XXXX", 
                "conversationTitle": "钉钉群标题", 
                "senderId": "XXXX", 
                "senderNick": "星星",
                "senderCorpId": "XXXX",
                "senderStaffId": "XXXX",
                "chatbotUserId":"XXXX",
                "atUsers":[
                {
                    "dingtalkId":"XXXX",
                    "staffId":"XXXX"
                }
                ]
            }
        """
        request = self.request
        headers = request.headers
        timestamp = headers.get('timestamp')
        sign = headers.get('sign')
        if not timestamp or not sign:
            return await self._reply_text_message('缺少timestamp,sign')
        date = datetime.datetime.fromtimestamp(convert_timestamp_to_second_level(int(timestamp)))
        now = datetime.datetime.now()
        timedelta = now - date
        if now > date and timedelta.seconds > 60*60:
            return await self._reply_text_message('timestamp expire')
        app_secret = settings.dingding_app_secret

        check_sign = f"{timestamp}\n{app_secret}"
        hmac_code = hmac.new(app_secret.encode('utf-8'), check_sign.encode('utf-8'), digestmod=hashlib.sha256).digest()
        check_sign = base64.b64encode(hmac_code).decode('utf-8')
        if check_sign != sign:
            return await self._reply_text_message('invalid sign')

        data = await request.json()
        msg_type = data['msgtype']
        if msg_type == 'text':
            text = data['text']['content']
            return await self._process_text_message(text)
        return await self._reply_text_message('不支持消息类型:{}'.format(msg_type))

    async def _process_text_message(self, text:str):
        text = text.strip()
        help_content = '\n'.join([
            '支持命令后添加比如: (每隔/i[nterval]/e[very])3(秒) <(持续)1秒/分/个>',
            '* / 或 ? 或 help',
            '* 币(列表)',
            '* <coin>: 查询某一币的状态',
            '* a(ll): 查询所有币的状态',
        ])
        if text in {'/', '?', 'help'}:
            return await self._reply_text_message(help_content)

        robot = self.request.app['robot']
        coin_map = {i.value.lower(): i for i in Coin}

        text_split = [i.strip() for i in text.split() if i.strip()]
        command = text_split[0].lower()
        # coin = text_split[1] if len(text_split) >= 2 else None

        interval = None
        interval_pattern = re.compile(r'[(每隔)ie](?P<interval>\d+)秒?', re.I)
        match = interval_pattern.search(text)
        if match:
            interval = int(match.group('interval'))

        duration_pattern = re.compile(r'[(每隔)ie]\d+秒? (?P<duration>\d+)?(?P<unit>[秒分个])?', re.I)
        duration_seconds = None
        duration_count = None
        match = duration_pattern.search(text)
        if match and match.group('duration'):
            duration = int(match.group('duration'))
            if match.group('unit') == '秒':
                duration_seconds = duration
            elif match.group('unit') == '分':
                duration_seconds = duration*60
            elif match.group('unit') in {'个', None}:
                duration_count = duration

        if command in {'币', '币列表'}:
            res = []
            for coin in robot.trade_coins:
                msg = [coin.value.lower()]
                if coin in robot.trade_coins_long:
                    msg.append('long')
                if coin in robot.trade_coins_short:
                    msg.append('short')
                res.append('-'.join(msg))
            return await self._reply_text_message('\n'.join(res))
        elif command in {'a', 'all'}:
            if interval:
                return self.process_interval(self.process_command_all,
                                      interval=interval,
                                      duration_seconds=duration_seconds,
                                      duration_count=duration_count)
            return await self.process_command_all()
        elif command in coin_map:
            if interval:
                return self.process_interval(self.process_command_coin,
                                      args=[coin_map[command]],
                                      interval=interval,
                                      duration_seconds=duration_seconds,
                                      duration_count=duration_count)
            return await self.process_command_coin(coin_map[command])
        return await self._reply_text_message(help_content)

    async def process_command_all(self, using_notification_api:bool=False):
        robot = self.request.app['robot']
        coins = robot.trade_coins
        res = [self.get_coin_status(i) for i in coins]
        return await self._reply_text_message('\n'.join(res), using_notification_api=using_notification_api)

    async def process_command_coin(self, coin, using_notification_api:bool=False):
        return await self._reply_text_message(self.get_coin_status(coin), using_notification_api=using_notification_api)

    def process_interval(self,
                         fn,
                         interval:int,
                         duration_seconds:int=None,
                         duration_count:int=None,
                         args=None):
        """
        Args:
            fn: 执行的函数
            args: fn 参数
            interval: 间隔(秒)
            duration_seconds: 持续秒数
            duration_count: 持续个数
        """
        fn = partial(fn, using_notification_api=True)
        args = args or []
        if not interval:
            return
        # 最大 30
        interval = min(interval, 30)
        if not duration_seconds and not duration_count:
            duration_count = 3
        # 最多15分钟
        if duration_seconds and duration_seconds > 60*15:
            duration_seconds = 60*5
        if duration_count and duration_count > 60*15//interval:
            duration_count = 60*15//interval

        async def loop_fn():
            index = 0
            start_time = time.time()
            while True:
                index += 1
                if duration_count and index > duration_count:
                    break
                if duration_seconds and time.time() - start_time > duration_seconds:
                    break
                await fn(*args)
                await asyncio.sleep(interval)
        asyncio.gather(loop_fn())

    async def _reply_text_message(self, content, using_notification_api:bool=False):
        if not using_notification_api:
            return web.json_response({
                'msgtype': 'text',
                'text': {
                    'content': content,
                }
            })
        await notification.DingDing.send_text_message(content)

    def get_coin_status(self, coin:Coin):
        robot = self.request.app['robot']
        trader = robot.traders.get(coin)
        if not trader:
            return
        strategy = robot.trade_strategies.get(coin)
        if not strategy:
            return
        res = ['{}:'.format(coin.value.lower())]
        if trader.trading:
            res.append('* 已开仓({})'.format(trader.long_or_short.value.lower()))
            res.append('* 未平仓原因:{}'.format(strategy.desc_if_not_close))
            res.append('* 开仓前余额:{}'.format(trader.balance_before_open))
        else:
            res.append('* 未开仓')
            res.append('* long:{}'.format(strategy.desc_if_not_open_long))
            res.append('* short:{}'.format(strategy.desc_if_not_open_short))
            res.append('* 当前余额:{}'.format(trader.balance_before_open))
        return f'\n{" "*4}'.join(res)
