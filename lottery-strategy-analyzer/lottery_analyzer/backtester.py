# -*- coding: utf-8 -*-
"""
历史命中率回测模块
------------------
用历史数据对推荐策略做「滚动回测」：对每一期，仅使用该期之前的历史（训练窗口）
生成推荐，再与该期实际开奖比对，统计命中情况。

同时用组合数学计算各奖级的理论概率，将策略实际命中率与理论随机命中率对比，
给出客观结论——以事实说明统计策略并未获得超越随机的预测优势。
"""

import math
from collections import Counter

from . import config, analyzer, recommender


def _combo_prob(red_pool, red_count, blue_pool, blue_count, r, b):
    """恰好命中 r 个前区、b 个后区的组合概率。"""
    total = math.comb(red_pool, red_count) * math.comb(blue_pool, blue_count)
    num = (math.comb(red_count, r) * math.comb(red_pool - red_count, red_count - r) *
           math.comb(blue_count, b) * math.comb(blue_pool - blue_count, blue_count - b))
    return num / total


def theoretical(spec):
    """计算各奖级理论概率与总中奖概率。"""
    tfunc = config.TIER_FUNC[spec.key]
    probs = {}
    any_prize = 0.0
    for r in range(spec.red_count + 1):
        for b in range(spec.blue_count + 1):
            p = _combo_prob(len(spec.red_pool), spec.red_count,
                            len(spec.blue_pool), spec.blue_count, r, b)
            t = tfunc(r, b)
            if t >= 1:
                probs[t] = probs.get(t, 0.0) + p
                any_prize += p
    return probs, any_prize


def backtest(draws, spec, strategy="balanced", k=100, train_window=300):
    """
    滚动回测指定策略。

    draws: 统一结构列表（最新在前）
    strategy: hot / cold / balanced
    k: 回测期数（取最近 k 期作为测试集）
    train_window: 每期使用的训练历史窗口大小
    """
    chron = list(reversed(draws))           # 旧 -> 新
    n = len(chron)
    start = max(1, n - k)

    tier_counts = Counter()
    red_match_dist = Counter()
    blue_match_dist = Counter()
    total_red = total_blue = 0
    tested = 0

    for i in range(start, n):
        train = chron[max(0, i - train_window):i]
        if len(train) < 20:
            continue
        stats = analyzer.analyze(train, spec)
        rec = recommender.recommend(stats, spec, alt_count=0)[strategy]
        pred_red = set(rec["red"])
        pred_blue = set(rec["blue"])
        actual = chron[i]
        rm = len(pred_red & set(actual["reds"]))
        bm = len(pred_blue & set(actual["blues"]))
        t = config.TIER_FUNC[spec.key](rm, bm)
        tier_counts[t] += 1
        red_match_dist[rm] += 1
        blue_match_dist[bm] += 1
        total_red += rm
        total_blue += bm
        tested += 1

    # 统计汇总
    cost = tested * spec.cost_per_note
    prize_ret = 0.0
    jackpot_wins = 0
    tier_detail = {}
    for t in sorted([x for x in tier_counts if x >= 1]):
        cnt = tier_counts[t]
        name, fixed = spec.prize_table.get(t, (f"{t}奖", None))
        if fixed:
            prize_ret += fixed * cnt
        else:
            jackpot_wins += cnt
        tier_detail[t] = {"name": name, "count": cnt, "fixed": fixed}

    any_prize_rate = (tested - tier_counts.get(0, 0)) / tested if tested else 0.0

    probs, any_prize_theory = theoretical(spec)

    return {
        "strategy": strategy,
        "tested": tested,
        "train_window": train_window,
        "avg_red_match": round(total_red / tested, 3) if tested else 0,
        "avg_blue_match": round(total_blue / tested, 3) if tested else 0,
        "red_match_dist": {str(k_): v for k_, v in sorted(red_match_dist.items())},
        "blue_match_dist": {str(k_): v for k_, v in sorted(blue_match_dist.items())},
        "any_prize_rate": round(any_prize_rate, 4),
        "any_prize_theory": round(any_prize_theory, 6),
        "tier_detail": tier_detail,
        "jackpot_wins": jackpot_wins,
        "cost": cost,
        "fixed_return": round(prize_ret, 2),
        "net": round(prize_ret - cost, 2),
        "theory_probs": {str(t): round(p, 8) for t, p in sorted(probs.items())},
    }
