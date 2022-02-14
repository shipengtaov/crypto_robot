from functools import partial
from os import path
from typing import Dict

import yaml

from . import settings
from .common import Coin, CoinSwap, KLinePeriod, LongOrShort, make_coin_enum_dynamicly_adding
from .strategy import BaseStrategy
from .third_package import CaseInsensitiveDict


with open(path.join(settings.root_dir, 'config.yaml'), 'r') as f:
    raw_config = yaml.safe_load(f)


def format_case_insensitive(raw_config):
    if not isinstance(raw_config, dict):
        return raw_config
    raw_config = CaseInsensitiveDict(raw_config)
    for k, v in raw_config.items():
        if isinstance(v, dict):
            raw_config[k] = format_case_insensitive(v)
    return raw_config


raw_config = format_case_insensitive(raw_config)


def format_raw_config(raw_config):
    """需要先调用 现货获取所有币种的接口，才能正确运行 notify_all
    """
    all_coin_map = CaseInsensitiveDict({i.value:i for i in make_coin_enum_dynamicly_adding()})
    coin_swap_map = CaseInsensitiveDict({f"{i.value}-swap":i for i in CoinSwap})
    all_coin_map.update(coin_swap_map)
    period_map = CaseInsensitiveDict({i.value:i for i in KLinePeriod})
    long_or_short_map = CaseInsensitiveDict({i.value:i for i in LongOrShort})

    res = dict(
        notify=dict(),
        notify_all=False,
        trade=dict(),
    )
    if raw_config['notify']['notify_all']:
        notify_coins = [i.value for i in make_coin_enum_dynamicly_adding()]
        res['notify_all'] = True
    else:
        notify_coins = raw_config['notify'].get('coins') or []
    trade_coins = (raw_config.get('trade') or dict()).get('coins') or []
    for k, coin_strings in [('notify', notify_coins), ('trade', trade_coins)]:
        for coin_str in coin_strings:
            coin = all_coin_map[coin_str]
            coin_config = (raw_config[k].get('coins') or dict()).get(coin_str) or dict()

            res[k].setdefault(coin, dict())

            # period
            periods = coin_config.get('periods') or raw_config[k]['default_periods']
            periods = [period_map[i] for i in periods]
            res[k][coin]['periods'] = periods or []

            # 做多还是做空
            long_or_short = coin_config.get('long_or_short') or raw_config[k]['default_long_or_short']
            long_or_short = [long_or_short_map[i] for i in long_or_short]
            res[k][coin]['long_or_short'] = long_or_short or []

            # 策略
            res[k][coin]['strategies'] = []
            strategies = coin_config.get('strategies') or raw_config[k]['default_strategies']
            for strategy_config in strategies:
                strategy_name = strategy_config['strategy_name']
                strategy_cls = BaseStrategy.get_strategy_cls_by_name(strategy_name)

                strategy_kwargs = strategy_config.get('kwargs')
                if strategy_kwargs:
                    kwargs = BaseStrategy.format_init_kwargs(**strategy_kwargs)
                else:
                    kwargs = dict()
                partial_cls = partial(strategy_cls, **kwargs)
                webhook_url_attr = strategy_config.get('webhook_url_attr')
                if webhook_url_attr and getattr(settings, webhook_url_attr):
                    setattr(partial_cls, 'webhook_url', getattr(settings, webhook_url_attr))
                notify_extra_key = strategy_config.get('notify_extra_key')
                if notify_extra_key:
                    setattr(partial_cls, 'notify_extra_key', notify_extra_key)
                res[k][coin]['strategies'].append(partial_cls)

            # 提醒时间间隔
            if k == 'notify':
                notify_time_gap = coin_config.get('notify_time_gap') or raw_config[k]['default_notify_time_gap']
                if notify_time_gap:
                    res[k][coin]['notify_time_gap'] = eval(notify_time_gap)

    if res['notify_all'] and raw_config['notify']['ignore_coin_if_price_less_than']:
        res['ignore_coin_if_price_less_than'] = raw_config['notify']['ignore_coin_if_price_less_than']
    return res


if __name__ == '__main__':
    from pprint import pprint
    res = format_raw_config(raw_config)
    pprint(res)
