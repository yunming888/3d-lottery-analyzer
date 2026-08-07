# -*- coding: utf-8 -*-
"""
大乐透 增强选号引擎
------------------
每注 = 前区 5 个不重复号(1-35) + 后区 2 个不重复号(1-12)，生成 NOTES 注。
选号逻辑三要素（与 fc3d 平行）：
  1) 冷热号分析：权重 = 频率归一 + 冷号补偿(遗漏) + 随机扰动
  2) 奇偶/大小均衡：全局统计奇/偶、大/小，对“多数方”加权惩罚，逼近 50:50
  3) 随机扰动：权重注入扰动 + 加权随机抽样，避免号码呈固定规律
"""
import random
from .analysis import red_freq, blue_freq, hot_cold
from . import config

RED_BIG = config.RED_BIG_THRESHOLD
BLUE_BIG = config.BLUE_BIG_THRESHOLD


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
    """构建前区(1-35)与后区(1-12)的数字权重：频率归一 + 冷号补偿 + 随机扰动。"""
    hc = hot_cold(records, config.WINDOW)
    rfc, bfc = hc["red_freq"], hc["blue_freq"]
    r_miss, b_miss = hc["red_omission"], hc["blue_omission"]
    rmax = max(r_miss.values()) or 1
    bmax = max(b_miss.values()) or 1

    red_w = {}
    tot_r = sum(rfc.values()) or 1
    for d in range(config.RED_MIN, config.RED_MAX + 1):
        freq_norm = rfc.get(d, 0) / tot_r
        cold_bonus = (r_miss.get(d, config.WINDOW) / rmax) * config.COLD_WEIGHT
        perturb = rng.uniform(-config.PERTURB, config.PERTURB)
        red_w[d] = max(0.01, freq_norm + cold_bonus + perturb)

    blue_w = {}
    tot_b = sum(bfc.values()) or 1
    for d in range(config.BLUE_MIN, config.BLUE_MAX + 1):
        freq_norm = bfc.get(d, 0) / tot_b
        cold_bonus = (b_miss.get(d, config.WINDOW) / bmax) * config.COLD_WEIGHT
        perturb = rng.uniform(-config.PERTURB, config.PERTURB)
        blue_w[d] = max(0.01, freq_norm + cold_bonus + perturb)

    return {"red": red_w, "blue": blue_w}


def _pick_reds(weights: dict, rng: random.Random, totals: dict) -> list:
    """按权重无放回抽 5 个前区号，实时奇偶/大小均衡惩罚。"""
    w = dict(weights["red"])
    chosen = []
    for _ in range(config.RED_COUNT):
        w2 = dict(w)
        # 奇偶均衡
        if totals["r_odd"] > totals["r_even"]:
            for d in w2:
                if d % 2 == 1:
                    w2[d] *= config.BALANCE_PENALTY
        else:
            for d in w2:
                if d % 2 == 0:
                    w2[d] *= config.BALANCE_PENALTY
        # 大小均衡
        if totals["r_big"] > totals["r_small"]:
            for d in w2:
                if d >= RED_BIG:
                    w2[d] *= config.BALANCE_PENALTY
        else:
            for d in w2:
                if d < RED_BIG:
                    w2[d] *= config.BALANCE_PENALTY
        d = _weighted_choice(w2, rng)
        chosen.append(d)
        w.pop(d, None)
        totals["r_odd"] += (d % 2 == 1)
        totals["r_even"] += (d % 2 == 0)
        totals["r_big"] += (d >= RED_BIG)
        totals["r_small"] += (d < RED_BIG)
    return sorted(chosen)


def _pick_blues(weights: dict, rng: random.Random, totals: dict) -> list:
    """按权重无放回抽 2 个后区号，实时奇偶/大小均衡惩罚。"""
    w = dict(weights["blue"])
    chosen = []
    for _ in range(config.BLUE_COUNT):
        w2 = dict(w)
        if totals["b_odd"] > totals["b_even"]:
            for d in w2:
                if d % 2 == 1:
                    w2[d] *= config.BALANCE_PENALTY
        else:
            for d in w2:
                if d % 2 == 0:
                    w2[d] *= config.BALANCE_PENALTY
        if totals["b_big"] > totals["b_small"]:
            for d in w2:
                if d >= BLUE_BIG:
                    w2[d] *= config.BALANCE_PENALTY
        else:
            for d in w2:
                if d < BLUE_BIG:
                    w2[d] *= config.BALANCE_PENALTY
        d = _weighted_choice(w2, rng)
        chosen.append(d)
        w.pop(d, None)
        totals["b_odd"] += (d % 2 == 1)
        totals["b_even"] += (d % 2 == 0)
        totals["b_big"] += (d >= BLUE_BIG)
        totals["b_small"] += (d < BLUE_BIG)
    return sorted(chosen)


def generate_notes(records: list, count: int = config.NOTES, seed=config.SEED):
    """生成 count 注（前区5 + 后区2），返回 (notes, balance)。"""
    rng = random.Random(seed)
    weights = build_weights(records, rng)
    notes = []
    seen = set()
    totals = {"r_odd": 0, "r_even": 0, "r_big": 0, "r_small": 0,
              "b_odd": 0, "b_even": 0, "b_big": 0, "b_small": 0}
    attempts = 0
    max_attempts = count * 80
    while len(notes) < count and attempts < max_attempts:
        attempts += 1
        reds = _pick_reds(weights, rng, totals)
        blues = _pick_blues(weights, rng, totals)
        key = (tuple(reds), tuple(blues))
        if key in seen:
            continue
        seen.add(key)
        notes.append({"reds": reds, "blues": blues})
    return notes, totals
