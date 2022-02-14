import asyncio
import re
from typing import Any

import aiomysql

from . import settings


async def execute(sql:str, args=None, fetchone:bool=False, fetchall:bool=False, callback=None) -> Any:
    """https://aiomysql.readthedocs.io/en/latest/examples.html"""
    sql = sql.strip()
    conn = await aiomysql.connect(**settings.mysql_config)
    try:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(sql, args=args)

            if callback is not None:
                result = await callback(cur=cur)
            else:
                if fetchone or re.search(r'^select.+?limit\s+1$', sql, re.I):
                    result = await cur.fetchone()
                elif fetchall or re.search(r'^select', sql, re.I):
                    result = await cur.fetchall()
                elif re.search(r'^insert', sql, re.I):
                    result = cur.lastrowid
                elif re.search(r'^update', sql, re.I):
                    result = cur.rowcount
                elif re.search(r'^delete', sql, re.I):
                    result = cur.rowcount
        await conn.commit()
        return result
    finally:
        conn.close()


if __name__ == "__main__":
    async def debug_fn(sql_list):
        from pprint import pprint
        if isinstance(sql_list, str):
            sql_list = [sql_list]
        for sql in sql_list:
            result = await execute(sql)
            print('='*20, sql, '='*20)
            pprint(result, indent=2)

    loop = asyncio.get_event_loop()
    sql = [
        "select * from orders limit 1",
        # "select * from orders limit 3",
        # "select * from orders",
    ]
    run_fn = debug_fn(sql)
    loop.run_until_complete(run_fn)
