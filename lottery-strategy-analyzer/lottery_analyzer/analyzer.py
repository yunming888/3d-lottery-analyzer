# -*- coding: utf-8 -*-
"""
统计分析模块
-----------
对历史开奖数据运用统计算法，计算：
- 出现频率（全窗口 & 近30期）
- 冷热号分布（按频率三分位：热号/温号/冷号）
- 遗漏值（当前遗漏、最大遗漏、理论出现次数、偏离度）
- 区间分布、奇偶比、和值分布等辅助指标

全部为描述性统计，仅刻画「已经发生」的规律，不代表未来。
"""

from collections import Counter


def _number_stats(pool, chron_sets, per_draw_count, recent_n=30):
    """
    计算单个号码池（红球或蓝球）的统计指标。

    pool:        号码列表，如 [1..33]
    chron_sets:  按时间升序的每期出现集合列表（旧->新）
    per_draw_count: 每注该区号码个数
    """
    N = len(chron_sets)
    positions = {x: [] for x in pool}
    for i, s in enumerate(chron_sets):
        for x in s:
            positions[x].append(i)

    freq, omission, max_omis = {}, {}, {}
    recent_freq = {x: 0 for x in pool}
    recent_sets = chron_sets[-recent_n:] if recent_n <= N else chron_sets
    for s in recent_sets:
        for x in s:
            recent_freq[x] += 1

    for x in pool:
        pos = positions[x]
        freq[x] = len(pos)
        if pos:
            omission[x] = (N - 1) - pos[-1]          # 距最新一期的遗漏
            gaps = []
            if pos[0] > 0:
                gaps.append(pos[0])                  # 首次出现前的遗漏
            for k in range(len(pos) - 1):
                gaps.append(pos[k + 1] - pos[k] - 1)  # 连续出现间隔
            gaps.append((N - 1) - pos[-1])           # 末次至今的遗漏
            max_omis[x] = max(gaps) if gaps else 0
        else:
            omission[x] = N
            max_omis[x] = N

    expected = N * per_draw_count / len(pool)        # 理论平均出现次数

    # 按频率三分位划分 热/温/冷
    ordered = sorted(pool, key=lambda x: freq[x])
    third = max(1, len(pool) // 3)
    cold = ordered[:third]
    hot = ordered[-third:]
    warm = ordered[third:-third]
    # 高遗漏（最「该出」）top third
    high_omis = sorted(pool, key=lambda x: omission[x], reverse=True)[:third]

    return {
        "freq": freq,
        "recent_freq": recent_freq,
        "omission": omission,
        "max_omission": max_omis,
        "expected_freq": round(expected, 2),
        "hot": hot,
        "warm": warm,
        "cold": cold,
        "high_omission": high_omis,
    }


def _band_dist(pool, chron_sets, bands=3):
    """区间分布：把号码池均分为 bands 段，统计每段时间窗口内的总出现次数。"""
    size = len(pool)
    step = size / bands
    result = {}
    for b in range(bands):
        lo = pool[0] + int(b * step)
        hi = pool[0] + int((b + 1) * step) - 1 if b < bands - 1 else pool[-1]
        cnt = sum(1 for s in chron_sets for x in s if lo <= x <= hi)
        result[f"{lo:02d}-{hi:02d}"] = cnt
    return result


def _parity_and_sum(chron_sets):
    """奇偶比（平均）与和值分布（按窗口）。"""
    total_odd = 0
    total_n = 0
    sums = []
    for s in chron_sets:
        total_odd += sum(1 for x in s if x % 2 == 1)
        total_n += len(s)
        sums.append(sum(s))
    avg_odd_ratio = (total_odd / total_n) if total_n else 0
    return {
        "avg_odd_ratio": round(avg_odd_ratio, 3),
        "sum_min": min(sums) if sums else 0,
        "sum_max": max(sums) if sums else 0,
        "sum_avg": round(sum(sums) / len(sums), 1) if sums else 0,
    }


def analyze(draws, spec, recent_n=30, bands=3):
    """
    主分析入口。

    draws: 统一结构列表（最新在前）
    返回结构化统计 dict。
    """
    chron_red = [set(d["reds"]) for d in reversed(draws)]    # 旧->新
    chron_blue = [set(d["blues"]) for d in reversed(draws)]

    red_stats = _number_stats(spec.red_pool, chron_red, spec.red_count, recent_n)
    blue_stats = _number_stats(spec.blue_pool, chron_blue, spec.blue_count, recent_n)

    red_stats["band_dist"] = _band_dist(spec.red_pool, chron_red, bands)
    blue_stats["band_dist"] = _band_dist(spec.blue_pool, chron_blue, bands)
    red_stats["parity_sum"] = _parity_and_sum(chron_red)
    blue_stats["parity_sum"] = _parity_and_sum(chron_blue)

    return {
        "window": len(draws),
        "red": red_stats,
        "blue": blue_stats,
    }
