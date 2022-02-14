
if __name__ == '__main__':
    import copy
    import types
    import doctest
    from crypto_robot import (
        coin_config,
        command_ui,
        common,
        db,
        exception,
        exchanges,
        kline,
        main,
        notification,
        scorer,
        server,
        server_view_dingding,
        server_view_slack,
        settings,
        stop_loss,
        strategy,
        third_package,
        trader,
    )
    from crypto_robot.exchanges import huobi, binance
    from crypto_robot.backtesting import backtesting

    global_var = copy.copy(globals())
    for k, v in global_var.items():
        if not isinstance(v, types.ModuleType):
            # print(f'not ModuleType: {k}')
            continue
        if not v.__package__.startswith('crypto_robot'):
            # print(f'not crypto_robot package: {k}: {v.__package__}')
            continue
        test_results = doctest.testmod(v)
        if test_results.failed != 0:
            raise Exception
        # print('-'*30)
        # print(k, v)
        # print(test_results)
