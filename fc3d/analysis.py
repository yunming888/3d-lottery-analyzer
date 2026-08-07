# -*- coding: utf-8 -*-
"""
历史数据分析：冷号/热号、奇偶大小、形态连出
---------------------------------------------
从 data/3d_history.json 读取真实开奖，为选号提供统计依据。
"""
import json
from collections import Counter
from .config import HISTORY_FILE, WINDOW

POSITIONS = ["bai", "shi", "ge"]


def load_history(path: str = HISTORY_FILE) -> list:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def position_freq(records: list, window: int = WINDOW) -> dict:
    """各位置（百/十/个）上 0-9 的出现次数。"""
    recs = records[:window]
    freqs = {p: Counter() for p in POSITIONS}
    for r in recs:
        for p in POSITIONS:
            freqs[p][int(r[p])] += 1
    return freqs


def overall_freq(records: list, window: int = WINDOW) -> Counter:
    """全位（不区分位置）0-9 出现次数。"""
    recs = records[:window]
    c = Counter()
    for r in recs:
        for n in r["nums"]:
            c[int(n)] += 1
    return c


def omission(records: list, window: int = 100) -> dict:
    """每个数字距上次出现的期数（0=本期刚出；从未出现=window）。records[0] 为最新。"""
    recs = records[:window]
    miss = {}
    seen = set()
    for idx, r in enumerate(recs):
        for n in set(int(x) for x in r["nums"]):
            if n not in seen:
                seen.add(n)
                miss[n] = idx
    for n in range(10):
        if n not in miss:
            miss[n] = window
    return miss


def hot_cold(records: list, window: int = WINDOW) -> dict:
    """返回热号(top3)、冷号(top3, 按遗漏)、频率表、遗漏表。"""
    of = overall_freq(records, window)
    miss = omission(records, max(window, 100))
    max_miss = max(miss.values()) or 1
    ranked = sorted(of.items(), key=lambda x: -x[1])
    hot = [d for d, _ in ranked[:3]]
    cold = [d for d, _ in sorted(miss.items(), key=lambda x: -x[1])[:3]]
    return {
        "overall_freq": of,
        "omission": miss,
        "max_omission": max_miss,
        "hot": hot,
        "cold": cold,
    }


def zuliu_streak(records: list) -> int:
    """从最新一期起，连续“组六”的期数。"""
    s = 0
    for r in records:
        if r.get("type") == "组六":
            s += 1
        else:
            break
    return s
