使用策略监控币安中的币价，再发送消息到 Slack
=================

## 运行

具体配置修改 `config.yaml`

    $ python -m crypto_robot.main

## 安装

### Slack

配置 webhook:

- [Sending messages using Incoming Webhooks](https://api.slack.com/messaging/webhooks)
    - create workspace
    - create app
    - add feature: `Incoming Webhooks`
    - add `Webhook URL`

配置 Slack Commands:

- [Enabling interactivity with Slash Commands](https://api.slack.com/interactivity/slash-commands)
    - Create New Command(<https://api.slack.com/apps>), 设置 url;
    - 验证请求是否来自 Slack(<https://api.slack.com/authentication/verifying-requests-from-slack>),可以直接使用[python-slack-sdk](https://github.com/slackapi/python-slack-sdk);
        - 查看 `signing secret`: <https://api.slack.com/apps>

文档：

- [查看已配置的 webhook url](https://api.slack.com/apps/A02695R3XS5/incoming-webhooks)
- [Formatting text for app surfaces](https://api.slack.com/reference/surfaces/formatting)

### 钉钉安装

- 添加 app key/ app secret
- app 设置 keyword
- 开发者后台修改回调地址

文档：

- 钉钉企业内部机器人：https://developers.dingtalk.com/document/app/develop-enterprise-internal-robots
- 开发者后台：https://open-dev.dingtalk.com/fe/app#/corp/robot

## DEX

### The Graph

<https://thegraph.com/>

#### uniswap

<https://github.com/Uniswap/v3-subgraph/blob/main/src/utils/intervalUpdates.ts>
只有 `tokenHourData` 和 `tokenDayData`

uniswap token:sos例子:
POST https://api.thegraph.com/subgraphs/name/uniswap/uniswap-v3

```
{
    "operationName":"tokenHourDatas",
    "variables":{"address":"0x3b484b82567a09e2588a13d54d032153f0c0aee0","startTime":1639818000,"skip":0},"query":"query tokenHourDatas($startTime: Int!, $skip: Int!, $address: Bytes!) {
  tokenHourDatas(
    first: 100
    skip: $skip
    where: {token: $address, periodStartUnix_gt: $startTime}
    orderBy: periodStartUnix
    orderDirection: asc
  ) {
    periodStartUnix
    high
    low
    open
    close
    __typename
  }
}
"}
```

### Coingecko

- eg. <https://www.coingecko.com/en/coins/floki-inu>
- [coingecko: api doc](https://www.coingecko.com/en/api/documentation)
- [github: pycoingecko](https://github.com/man-c/pycoingecko)

### Bitquery.io

- <https://graphql.bitquery.io/ide>
- [bitquery: Uniswap OHLC data (5 minute candle , CHINU/WETH)](https://graphql.bitquery.io/ide/gH9DfsZBDC)
- [bitquery: Pancake OHLC data WBNB-BUSD](https://graphql.bitquery.io/ide/euYQzeteTI)
- <https://community.bitquery.io/t/integrating-tradingview-s-technical-analysis-charts-with-bitquery-graphql-api-using-vuejs/343>

```graphql
{
ethereum(network: bsc){
dexTrades(options: {limit: 30, desc: "timeInterval.hour"},
# date: {since:""},
exchangeName: {in:["Pancake v2"]},
# mobox
baseCurrency: {is: "0x3203c9e46ca618c8c1ce5dc67e7e9d75f5da2377"},
# usdt
quoteCurrency: {is: "0x55d398326f99059fF775485246999027B3197955"}){
timeInterval {
hour(count: 1)
}
baseCurrency {
symbol
address
}
baseAmount
quoteCurrency {
symbol
address
}
quoteAmount
trades: count
quotePrice
maximum_price: quotePrice(calculate: maximum)
minimum_price: quotePrice(calculate: minimum)
open_price: minimum(of: block get: quote_price)
close_price: maximum(of: block get: quote_price)
}}
}
```

### cryptocompare

- [cryptocompare: api doc](https://min-api.cryptocompare.com/documentation)
- [github: TradingView 例子, api+websocket](https://github.com/tradingview/charting-library-tutorial/blob/master/documentation/streaming-implementation.md)

### Pancake

- <https://tokens.pancakeswap.finance/pancakeswap-top-100.json>
- <https://tokens.pancakeswap.finance/pancakeswap-extended.json>

### Useful links

- [github: 基于reddit实现的 dex 链上计算实时价格](https://github.com/cjxe/dex-crawler)
    - [reddit: is_there_a_way_to_monitor_the_price_on_pancake](https://www.reddit.com/r/pancakeswap/comments/mwz72v/is_there_a_way_to_monitor_the_price_on_pancake/)

## Help

设置时区:

    $ sudo timedatectl set-timezone your_time_zone
