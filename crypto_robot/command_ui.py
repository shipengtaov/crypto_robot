"""
执行用户输入的命令
"""

import asyncio
import datetime
import re
import time
import uuid
from typing import Dict, Optional, Tuple

import attr

from .notification import Notification


@attr.s
class CommandResult:
    raw_result: str = attr.ib(factory=str)
    slack_result: str = attr.ib(factory=str)


class CommandUI:
    tasks: Dict[str, str] = dict()

    def __init__(self, command:str, command_text:str, robot):
        self.command = command
        self.command_text = command_text
        self.robot = robot

    async def run(self) -> Optional[CommandResult]:
        method_name = self._get_method_name_from_command()
        if not hasattr(self, method_name):
            return
        return await getattr(self, method_name)()

    def _get_method_name_from_command(self) -> str:
        method = self.command.lower().replace('-', '_')
        if method == 'k':
            method = 'kline'
        if method == 'i' or method == 'info':
            method = 'list'
        method = f"run_command_{method}"
        return method

    async def run_command_list(self) -> Optional[CommandResult]:
        """/list, /info
        """
        robot = self.robot
        res = []
        for coin, trader in robot.traders.items():
            if self.command_text and self.command_text.lower() != coin.value.lower():
                continue

            res.append(f"{coin.value}:")
            indent = ' '*4
            if trader.stop_trade:
                res.append(f"{indent}已停止交易")
            if trader.trading:
                res.append('{}已开仓({})'.format(indent, trader.long_or_short.value.lower()))
                res.append('{}开仓前余额:{}'.format(indent, trader.balance_before_open))
            else:
                res.append(f'{indent}未开仓')
                res.append('{}当前余额:{}'.format(indent, trader.balance_before_open))
            if trader.re_trade_until and trader.re_trade_until > time.time():
                res.append('{}重新开仓时间:{}'.format(indent, datetime.datetime.fromtimestamp(trader.re_trade_until).strftime('%Y-%m-%d %H:%M:%S')))

        res = '\n'.join(res) or 'no result'
        return CommandResult(raw_result=res, slack_result=res)

    async def run_command_kline(self) -> Optional[CommandResult]:
        res = []
        for coin, kline_container in self.robot.kline_containers.items():
            if self.command_text and self.command_text.lower() != coin.value.lower():
                continue

            res.append(f"{coin.value}:")
            indent = ' '*4
            for period in kline_container.periods:
                kline_queue = kline_container.get_by_period(period)
                msg = f"{indent}{period.value}: "
                kline_msg = []
                for i in range(-6, 0):
                    kline = kline_queue.queue[i]
                    kline_msg.append("{}{}%".format(
                        kline.direction_symbol,
                        kline.percent,
                    ))
                    if i == -1:
                        kline_msg[-1] += f",{kline.close}"
                    kline_msg[-1] += f"({kline.period_date.hour}:{kline.period_date.minute})"
                msg += ' | '.join(kline_msg)
                res.append(msg)
        res = '\n'.join(res) or 'no result'
        return CommandResult(raw_result=res, slack_result=res)

    async def run_command_ma(self) -> Optional[CommandResult]:
        """/ma 移动平均线
        """
        res = []
        coin = None
        kline_container = None
        for k, v in self.robot.kline_containers.items():
            if self.command_text and self.command_text.lower() == k.value.lower():
                coin = k
                kline_container = v
                break
        if not kline_container:
            res = ['no coin or unknown coin']

        res.append(f"`{coin.value}:`")
        indent = ' '*4
        for period in kline_container.periods:
            kline_queue = kline_container.get_by_period(period)
            res.append(f"`{period.value}:`")
            for ma in kline_queue.ma_list:
                msg = f"{indent}`ma{ma}:` "
                ma_prices = []
                for i in range(-6, 0):
                    ma_prices.append(kline_queue.ma(ma)[i])
                msg += ' | '.join(map(str, ma_prices))
                res.append(msg)

        res = '\n'.join(res) or 'no result'
        return CommandResult(raw_result=res, slack_result=res)

    async def run_command_start(self) -> Optional[CommandResult]:
        """/start
        """
        res = []
        for coin, trader in self.robot.traders.items():
            if self.command_text and self.command_text.lower() != coin.value.lower():
                continue

            trader.stop_trade = False
            trader.re_trade_until = None
            res.append(coin.value)
            await trader.refresh_balance_before_open()
        res = ', '.join(res)
        if res:
            res = f'start: {res}'
        else:
            res = 'no result'
        return CommandResult(raw_result=res, slack_result=res)

    async def run_command_stop(self) -> Optional[CommandResult]:
        """/stop
        """
        res = []
        for coin, trader in self.robot.traders.items():
            if self.command_text and self.command_text.lower() != coin.value.lower():
                continue

            trader.stop_trade = True
            trader.re_trade_until = None
            trader.trading = False
            res.append(coin.value)
        res = ', '.join(res)
        if res:
            res = f'stop: {res}'
        else:
            res = 'no result'
        return CommandResult(raw_result=res, slack_result=res)

    async def run_command_refresh_balance(self) -> Optional[CommandResult]:
        """/refresh_balance
        """
        res = []
        for coin, trader in self.robot.traders.items():
            if self.command_text and self.command_text.lower() != coin.value.lower():
                continue

            if trader.trading:
                msg = f"{coin.value}: 正在交易"
            else:
                await trader.refresh_balance_before_open()
                msg = f"{coin.value}: 已刷新余额"
            res.append(msg)
        res = '\n'.join(res) or 'no result'
        return CommandResult(raw_result=res, slack_result=res)

    async def run_command_restart_after(self) -> Optional[CommandResult]:
        """/restart_after <time>
        """
        coin_str, time_str = self._parse_command_text_from_restart_after()
        seconds = self.convert_to_seconds(time_str)
        if not seconds:
            res = f"error text: {self.command_text}"
            return CommandResult(raw_result=res, slack_result=res)
        re_trade_until = time.time() + seconds
        res = []
        for coin, trader in self.robot.traders.items():
            if coin_str and coin_str.lower() != coin.value.lower():
                continue

            trader.stop_trade = False
            trader.re_trade_until = re_trade_until
            trader.trading = False
            res.append(coin.value)
        res = ', '.join(res)

        async def fn():
            for coin, trader in self.robot.traders.items():
                if coin_str and coin_str.lower() != coin.value.lower():
                    continue
                await trader.refresh_balance_before_open()

        if res:
            res = f'restart-after: {res}'
            sleep = max(0, seconds-3)
            await self.run_after(fn, sleep, task_name='restart_after')
        else:
            res = 'no result'

        return CommandResult(raw_result=res, slack_result=res)

    def _parse_command_text_from_restart_after(self) -> Tuple[str, str]:
        """
        >>> CommandUI(command=None, command_text="eth 1m", robot=None)._parse_command_text_from_restart_after()
        ('eth', '1m')

        >>> CommandUI(command=None, command_text="1h 1m", robot=None)._parse_command_text_from_restart_after()
        ('', '1h 1m')
        """
        if not self.command_text:
            return '', ''
        command_text = self.command_text.strip()
        pattern = re.compile(r'^[a-zA-Z]+\d*\s')
        match = pattern.match(command_text)
        if match:
            coin = match.group(0).strip()
            time_str = command_text[len(coin):].strip()
            return coin, time_str
        return '', command_text

    async def run_after(self, fn, seconds:int, task_name:str=None):
        task_id = uuid.uuid4().hex
        self.tasks[task_name] = task_id

        async def loop_fn():
            await asyncio.sleep(seconds)
            if self.tasks.get(task_name) != task_id:
                return
            await fn()
            await Notification.send_catching_exc(f"restart after 3 seconds")

        asyncio.gather(loop_fn())

    @classmethod
    def convert_to_seconds(cls, time_str:str) -> Optional[int]:
        """
        convert time string to seconds

        >>> f = CommandUI.convert_to_seconds
        >>> f('1m')
        60

        >>> f('2m 3s')
        123

        >>> f('2min 3 se')
        123
        """
        seconds = 0
        patterns = [
            (re.compile(r'(\d+)\s*h(our)?'), lambda m: int(m.group(1)) * 3600),
            (re.compile(r'(\d+)\s*m(in(ute)?)?'), lambda m: int(m.group(1)) * 60),
            (re.compile(r'(\d+)\s*s(ec(ond)?)?'), lambda m: int(m.group(1))),
        ]
        for pattern, func in patterns:
            match = pattern.search(time_str)
            if match:
                seconds += func(match)
        return seconds
