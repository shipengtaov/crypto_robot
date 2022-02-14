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
from .common import Coin, convert_timestamp_to_second_level, get_logger
from . import notification
from .server_view_slack import SlackView
from .server_view_dingding import DingDingMessageView

logger = get_logger()

# routes = web.RouteTableDef()
app = web.Application()
# app.add_routes(routes)
app.router.add_view('/slack', SlackView)
app.router.add_view('/dingding', DingDingMessageView)


def set_trade_info(robot):
    """
    https://docs.aiohttp.org/en/stable/web_advanced.html#application-s-config
    """
    app['robot'] = robot


if __name__ == '__main__':
    from argparse import ArgumentParser
    parser = ArgumentParser()
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    web.run_app(app, host='0.0.0.0', port=args.port)
