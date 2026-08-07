# -*- coding: utf-8 -*-
"""
增强选号引擎
-----------
每注为三位数（百位/十位/个位，各 0-9），生成 NOTES 注。
选号逻辑三要素：
  1) 冷热号分析：权重 = 频率归一 + 冷号补偿(遗漏) + 随机扰动
  2) 奇偶/大小均衡：全局统计奇/偶、大/小，对“多数方”加权惩罚，逼近 50:50
  3) 随机扰动：权重注入扰动 + 加权随机抽样，避免号码呈固定规律
"""
import random
from .analysis import position_freq, hot_cold
from .config import WINDOW, NOTES, PERTURB, COLD_WEIGHT, BALANCE_PENALTY, SEED

POSITIONS = ["bai", "shi", "ge"]


def _is_odd(d: int) -> bool:
    return d % 2 == 1


def _is_big(d: int) -> bool:
    return d >= 5


def _weighted_choice(w: dict, rng: random.Random) -> int:
    items = list(w.items())
    total = sum(v for _, v in items)
    r = rng.random() * total
    cum = 0.0
    for d, val in items:
        cum += val
        if r <= cum:
            return d
    return items[-1][0]


def build_weights(records: list, rng: random.Random) -> dict:
    """为每个位置构建数字权重：频率归一 + 冷号补偿 + 随机扰动。"""
    freqs = position_freq(records, WINDOW)
    hc = hot_cold(records, WINDOW)
    max_miss = hc["max_omission"] or 1
    weights = {}
    for p in POSITIONS:
        f = freqs[p]
        tot = sum(f.values()) or 1
        w = {}
        for d in range(10):
            freq_norm = f.get(d, 0) / tot
            cold_bonus = (hc["omission"].get(d, WINDOW) / max_miss) * COLD_WEIGHT
            perturb = rng.uniform(-PERTURB, PERTURB)
            # 保证权重为正，避免抽样异常
            w[d] = max(0.01, freq_norm + cold_bonus + perturb)
        weights[p] = w
    return weights


def generate_notes(records: list, count: int = NOTES, seed=SEED):
    """生成 count 注三位数（百/十/个），并返回奇偶/大小均衡统计。"""
    rng = random.Random(seed)
    weights = build_weights(records, rng)

    notes = []
    seen = set()
    odd = even = big = small = 0
    attempts = 0
    max_attempts = count * 50

    while len(notes) < count and attempts < max_attempts:
        attempts += 1
        note = []
        t_odd = t_even = t_big = t_small = 0
        for p in POSITIONS:
            w = dict(weights[p])
            # 奇偶均衡：当前奇数多于偶数 → 压低奇数权重
            if (odd + t_odd) > (even + t_even):
                for d in w:
                    if _is_odd(d):
                        w[d] *= BALANCE_PENALTY
            else:
                for d in w:
                    if not _is_odd(d):
                        w[d] *= BALANCE_PENALTY
            # 大小均衡：当前大号多于小号 → 压低大号权重
            if (big + t_big) > (small + t_small):
                for d in w:
                    if _is_big(d):
                        w[d] *= BALANCE_PENALTY
            else:
                for d in w:
                    if not _is_big(d):
                        w[d] *= BALANCE_PENALTY
            d = _weighted_choice(w, rng)
            note.append(d)
            if _is_odd(d):
                t_odd += 1
            else:
                t_even += 1
            if _is_big(d):
                t_big += 1
            else:
                t_small += 1
        key = tuple(note)
        if key in seen:        # 去重，避免重复注
            continue
        seen.add(key)
        notes.append(note)
        odd += t_odd
        even += t_even
        big += t_big
        small += t_small

    return notes, {"odd": odd, "even": even, "big": big, "small": small}
