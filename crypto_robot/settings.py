import os
from os import environ, path
from urllib.parse import urljoin

from environs import Env

env = Env()
env.read_env()

debug = env.bool('DEBUG', False)
debug_strategy = env.bool('DEBUG_STRATEGY', False)

root_dir = path.dirname(path.dirname(path.abspath(__file__)))
logs_dir = path.join(root_dir, 'logs')

# -------------------------------------- 交易配置 -------------------------------------- #
enable_stop_loss = env.bool('ENABLE_STOP_LOSS', False)
# 交易多少百分比的金额
trade_percent = 1

# -------------------------------------- 环境配置 -------------------------------------- #
# MySQL
mysql_config = {
    'host': env.str('MYSQL_HOST', 'localhost'),
    'port': env.int('MYSQL_PORT', 3306),
    'user': env.str('MYSQL_USER', 'root'),
    'password': env.str('MYSQL_PASSWORD', ''),
    'db': env.str('MYSQL_DB', 'crypto_robot'),
    'charset': 'utf8',
}

# -------------------------------------- Slack配置 -------------------------------------- #
slack_webhook_url = env.str('SLACK_WEBHOOK_URL', 'input-this')
# https://api.slack.com/apps
slack_signing_secret = env.str('SLACK_SIGNING_SECRET', 'input-this')
slack_webhook_url_enable_customize_notify_short = env.bool('SLACK_WEBHOOK_URL_ENABLE_CUSTOMIZE_NOTIFY_SHORT', True)
slack_webhook_url_notify_short = env.str('SLACK_WEBHOOK_URL_NOTIFY_SHORT', 'input-this')
slack_webhook_url_ma_strategy_20_40 = env.str('SLACK_WEBHOOK_URL_MA_STRATEGY_20_40', 'input-this')
slack_webhook_url_ma_strategy_20_40_60 = env.str('SLACK_WEBHOOK_URL_MA_STRATEGY_20_40_60', 'input-this')
slack_webhook_url_macd_strategy = env.str('SLACK_WEBHOOK_URL_MACD_STRATEGY', 'input-this')
slack_webhook_url_ma_macd_strategy = env.str('SLACK_WEBHOOK_URL_MA_MACD_STRATEGY', 'input-this')

# -------------------------------------- 钉钉配置 -------------------------------------- #
dingding_api = env.str('DINGDING_API', '')
dingding_app_secret = env.str('DINGDING_APP_SECRET', '')

# -------------------------------------- 交易所配置 -------------------------------------- #

# ---------------------------------- 币安 Binance ---------------------------------- #
binance_access_key = env.str('BINANCE_ACCESS_KEY', "foo")
binance_secret = env.str('BINANCE_SECRET', "foo")

# ---- 现货交易 ---- #
binance_spot_websocket_api = env.str('BINANCE_SPOT_WEBSOCKET_API', 'wss://stream.binance.com:9443/ws')
binance_spot_history_api = env.str('BINANCE_SPOT_HISTORY_API', 'https://api.binance.com/api/v3/klines')
# ---- 币本位合约 ---- #
binance_coin_based_swap_api_host = "https://dapi.binance.com"
binance_coin_based_swap_api_host_test = "https://testnet.binancefuture.com"
# 余额
binance_coin_based_swap_balance_api = urljoin(binance_coin_based_swap_api_host, '/dapi/v1/balance')
# 余额 - 测试接口
binance_coin_based_swap_balance_api_test = urljoin(binance_coin_based_swap_api_host_test, '/dapi/v1/balance')
# 下单(POST)/查询(GET)
binance_coin_based_swap_order_api = urljoin(binance_coin_based_swap_api_host, '/dapi/v1/order')
# 下单 - 测试接口
binance_coin_based_swap_order_api_test = urljoin(binance_coin_based_swap_api_host, '/dapi/v1/order/test')
# ---- USDT合约 ---- #
binance_usdt_based_swap_api_host = "https://fapi.binance.com"
# 余额
binance_usdt_based_swap_balance_api = urljoin(binance_usdt_based_swap_api_host, '/fapi/v2/balance')
# 下单(POST)/查询(GET)
binance_usdt_based_swap_order_api = urljoin(binance_usdt_based_swap_api_host, '/fapi/v1/order')

# ---------------------------------- 火币 ---------------------------------- #
huobi_access_key = env.str('HUOBI_ACCESS_KEY', None)
huobi_secret = env.str('HUOBI_SECRET', None)

# ---- 现货交易 ---- #
# https://huobiapi.github.io/docs/spot/v1/cn/#urls
spot_api_host = env.str('SPOT_API_HOST', 'api.huobi.pro')
# spot_api_host = env.str('SPOT_API_HOST', 'api-aws.huobi.pro')
spot_all_currency_api = urljoin(f'https://{spot_api_host}', env.str('SPOT_ALL_CURRENCY_API', '/v1/common/currencys'))
spot_websocket_api = urljoin(f'wss://{spot_api_host}', env.str('SPOT_WEBSOCKET_API', '/ws'))

# ---- 合约交易 ---- #
swap_api_host = env.str('SWAP_API_HOST', 'api.btcgateway.pro')
swap_websocket_api = urljoin(f'wss://{swap_api_host}', env.str('SWAP_WEBSOCKET_PATH', '/linear-swap-ws'))
# 合约历史行情
swap_history_api = urljoin(f'https://{swap_api_host}', env.str('SWAP_HISTORY_PATH', '/linear-swap-ex/market/history/kline'))
# 合约资产[逐仓]
swap_account_info_api = urljoin(f'https://{swap_api_host}', env.str('SWAP_ACCOUNT_INFO_API', '/linear-swap-api/v1/swap_account_info'))
# 持仓信息[逐仓]
swap_account_position_api = urljoin(f'https://{swap_api_host}', env.str('SWAP_ACCOUNT_POSITION_API', '/linear-swap-api/v1/swap_position_info'))
# 合约资产[全仓]
swap_cross_account_info_api = urljoin(f'https://{swap_api_host}', env.str('SWAP_ACCOUNT_INFO_API', '/linear-swap-api/v1/swap_cross_account_info'))
# 合约下单[逐仓]. 包括开仓平仓
swap_order_api = urljoin(f'https://{swap_api_host}', env.str('SWAP_ORDER_API', '/linear-swap-api/v1/swap_order'))
# 订单信息[逐仓]
swap_order_info_api = urljoin(f'https://{swap_api_host}', env.str('SWAP_ORDER_INFO_API', '/linear-swap-api/v1/swap_order_info'))
# 当前未成交订单[逐仓]
swap_open_orders_api = urljoin(f'https://{swap_api_host}', env.str('SWAP_OPEN_ORDERS_API', '/linear-swap-api/v1/swap_openorders'))
# 闪电平仓下单[逐仓]
swap_lighting_close_order_api = urljoin(f'https://{swap_api_host}', env.str('SWAP_LIGHTING_CLOSE_ORDER_API', '/linear-swap-api/v1/swap_lightning_close_position'))
swap_contract_info_api = urljoin(f'https://{swap_api_host}', env.str('SWAP_CONTRACT_INFO_API', '/linear-swap-api/v1/swap_contract_info'))
