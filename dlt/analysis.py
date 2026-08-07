# -*- coding: utf-8 -*-
"""
大乐透 历史数据分析：冷号/热号、奇偶大小分布
---------------------------------------------
从 data/dlt_history.json 读取真实开奖（前区 reds / 后区 blues），为选号提供统计依据。
统一结构每期: {"issue", "date", "reds":[5], "blues":[2]}，records[0] 为最新。
"""
import os
import json
from collections import Counter

from . import config


def load_history(path: str = config.HISTORY_FILE) -> list:
    """读取历史（兼容 {meta,draws} 与裸 list 两种格式）。空文件/缺失返回 []。"""
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        return data.get("draws", [])
    return data


def red_freq(records: list, window: int = config.WINDOW) -> Counter:
    """前区（1-35）出现次数。"""
    recs = records[:window]
    c = Counter()
    for r in recs:
        for n in r["reds"]:
            c[int(n)] += 1
    return c


def blue_freq(records: list, window: int = config.WINDOW) -> Counter:
    """后区（1-12）出现次数。"""
    recs = records[:window]
    c = Counter()
    for r in recs:
        for n in r["blues"]:
            c[int(n)] += 1
    return c


def omission(records: list, pool: str, pool_max: int, window: int = 200) -> dict:
    """每个号码距上次出现的期数（0=本期刚出；从未出现=window）。pool='red'/'blue'。"""
    recs = records[:window]
    miss = {}
    seen = set()
    for idx, r in enumerate(recs):
        nums = set(int(x) for x in (r["reds"] if pool == "red" else r["blues"]))
        for n in nums:
            if n not in seen:
                seen.add(n)
                miss[n] = idx
    for n in range(1, pool_max + 1):
        if n not in miss:
            miss[n] = window
    return miss


def hot_cold(records: list, window: int = config.WINDOW) -> dict:
    """返回前区/后区的热号(top5)、冷号(top5, 按遗漏)、频率表、遗漏表。"""
    rfc = red_freq(records, window)
    bfc = blue_freq(records, window)
    r_miss = omission(records, "red", config.RED_MAX, max(window, 200))
    b_miss = omission(records, "blue", config.BLUE_MAX, max(window, 200))
    hot_r = [d for d, _ in sorted(rfc.items(), key=lambda x: -x[1])[:5]]
    hot_b = [d for d, _ in sorted(bfc.items(), key=lambda x: -x[1])[:5]]
    cold_r = [d for d, _ in sorted(r_miss.items(), key=lambda x: -x[1])[:5]]
    cold_b = [d for d, _ in sorted(b_miss.items(), key=lambda x: -x[1])[:5]]
    return {
        "red_freq": rfc, "blue_freq": bfc,
        "red_omission": r_miss, "blue_omission": b_miss,
        "hot_red": hot_r, "hot_blue": hot_b,
        "cold_red": cold_r, "cold_blue": cold_b,
    }


def latest(records: list) -> dict:
    """最新一期（records[0]）。"""
    return records[0] if records else {}
