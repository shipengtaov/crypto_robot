import asyncio
import datetime
import time

import aiohttp
import slack_sdk
from slack_sdk.webhook.async_client import AsyncWebhookClient

from .common import Coin, auto_retry, obscurity_coin, get_logger, get_random_emoji
from . import settings

logger = get_logger()


class Notification:
    @classmethod
    async def send_catching_exc(cls, *args, **kwargs):
        await Slack.send_catching_exc(*args, **kwargs)
        # await DingDing.send_catching_exc(*args, **kwargs)


class Slack:
    webhook_url = settings.slack_webhook_url

    # (timestamp, msg)
    buffers = []

    @classmethod
    async def send_catching_exc(cls, *args, **kwargs):
        """捕获异常版本的发送消息"""
        try:
            future_fn = lambda:cls.send(*args, **kwargs)
            await auto_retry(future_fn=future_fn, retry_count=3, retry_msg='resending msg to slack...')
        except Exception as e:
            logger.error(f"slack发送消息失败.{e}")

    @classmethod
    async def send(cls, msg:str, webhook_url:str=None, is_short_notification:bool=False, buffer_seconds:int=None, random_emoji:bool=False):
        """
        Args:
            is_short_notification: bool, 是否是做空的通知
            buffer_seconds: int, 缓存若干秒再发送
            random_emoji: 是否在消息中放入一个随机的表情
        """
        emoji = get_random_emoji() if random_emoji else ''
        now = datetime.datetime.now().strftime('%m-%d %H:%M')

        webhook_url = webhook_url or cls.webhook_url
        if is_short_notification and settings.slack_webhook_url_enable_customize_notify_short:
            webhook_url = settings.slack_webhook_url_notify_short

        if not buffer_seconds:
            msg = f'{msg}\n>_{now}_{emoji}'
            await cls.send_text_message(msg, webhook_url=webhook_url)
            return

        cls.buffers.append((time.time(), msg))
        if time.time() - cls.buffers[0][0] >= buffer_seconds:
            msg = '\n--------\n'.join([i[1] for i in cls.buffers])
            msg = f'{msg}\n>_{now}_{emoji}'
            # 先清空再发送, 否则容易有重复的消息
            cls.buffers = []
            await cls.send_text_message(msg, webhook_url=webhook_url)
            return

    @classmethod
    async def send_text_message(cls, msg:str, webhook_url:str=None):
        client = AsyncWebhookClient(url=webhook_url or cls.webhook_url)
        await client.send(text=msg)
        # 2021.06.23 15:39 下面的消息测试的没用
        # await client.send(text=msg, blocks=[
        #     {
        #         'type': 'section',
        #         'text': {
        #             'type': 'mrkdwn',
        #             'text': msg,
        #         }
        #     }
        # ])


class DingDing:
    """
    https://ding-doc.dingtalk.com/doc#/serverapi2/qf2nxq
    """
    api = settings.dingding_api
    keyword = '🤖️'

    # (timestamp, msg)
    buffers = []

    @classmethod
    async def send_catching_exc(cls, *args, **kwargs):
        """捕获异常版本的发送消息"""
        try:
            future_fn = lambda:cls.send(*args, **kwargs)
            await auto_retry(future_fn=future_fn, retry_count=3, retry_msg='resending msg to 钉钉...')
        except Exception as e:
            logger.error(f"钉钉发送消息失败.{e}")

    @classmethod
    async def send(cls, msg:str, webhook_url:str=None, is_short_notification:bool=False, buffer_seconds:int=None, random_emoji:bool=False):
        """
        Args:
            buffer_seconds: int, 缓存若干秒再发送
            random_emoji: 是否在消息中放入一个随机的表情
        """
        emoji = get_random_emoji() if random_emoji else ''
        now = datetime.datetime.now().strftime('%m-%d %H:%M')

        if not buffer_seconds:
            msg = f'{cls.keyword}{emoji}{msg}\n{now}'
            await cls.send_text_message(msg, add_keyword=False)
            return

        cls.buffers.append((time.time(), msg))
        if time.time() - cls.buffers[0][0] >= buffer_seconds:
            msg = '\n--------\n'.join([i[1] for i in cls.buffers])
            msg = f'{emoji}{msg}\n{now}'
            # 先清空再发送, 否则容易有重复的消息
            cls.buffers = []
            await cls.send_text_message(msg, add_keyword=False)
            return

    @classmethod
    async def send_text_message(cls, msg:str, add_keyword:bool=True):
        if add_keyword:
            msg = f'{cls.keyword}{msg}'
        data = {
            'msgtype': 'text',
            'text': {
                'content': msg,
            }
        }
        async with aiohttp.ClientSession() as session:
            response = await session.post(url=cls.api, json=data, timeout=10)
            res_json = await response.json()
            # print(res_json)
            if str(res_json.get('errcode')) != '0':
                logger.error(f"dingding error: {res_json}")


if __name__ == "__main__":
    import datetime
    loop = asyncio.get_event_loop()
    # loop.run_until_complete(Slack.send(Coin.BTC, 'hello, now {}'.format(datetime.datetime.now())))
    # loop.run_until_complete(DingDing.send(Coin.BTC, 'hello, now {}'.format(datetime.datetime.now())))
    loop.run_until_complete(
        Notification.send_catching_exc(
            '`hello`    `hi`'.format(datetime.datetime.now()),
            webhook_url=settings.slack_webhook_url_ma_macd_strategy,
            # random_emoji=True,
        ))
