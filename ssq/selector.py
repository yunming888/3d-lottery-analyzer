# -*- coding: utf-8 -*-
"""
双色球 选号引擎 v2（2026-08-20 重写 generate_notes，规则参考大乐透 dlt）
-------------------------------------------------------------------
每注 = 红球 6 个不重复号(1-33) + 蓝球 1 个号(1-16)，生成 NOTES 注。

选号要素:
  1) 经验频率加权(保留): 红球/蓝球经验频率归一作先验, 使号码"典型";
  2) 奇偶/大小均衡(保留): 单注内对多数方加权惩罚, 逼近 50:50;
  3) 覆盖最大化贪心(新增): 在有效候选池中, 优先选取能引入最多"未覆盖数字"的注。
     目的: 降低"5注全不中"的方差(经验期望不变, 但减少连续空枪的体验);
  4) 冷号补偿: 已下调为装饰性(见 config.COLD_WEIGHT)。冷号≠必出, 属赌徒谬误。

重要: 公平随机下每注理论中奖率恒定, 本引擎不改变负EV与理论中奖率。
"""
import random
from .analysis import red_freq, blue_freq, hot_cold
from . import config

ENGINE_VERSION = "v3"  # 选号引擎版本，供报告/推送标注（出号时附带说明）

RED_BIG = config.RED_BIG_THRESHOLD
BLUE_BIG = config.BLUE_BIG_THRESHOLD


def _weighted_choice(w: dict, rng: random.Random) -> int:
    items = list(w.items())
    total = sum(v for _, v in items)
    if total <= 0:
        return items[rng.randrange(len(items))][0]
    r = rng.random() * total
    cum = 0.0
    for d, val in items:
        cum += val
        if r <= cum:
            return d
    return items[-1][0]


def build_weights(records: list, rng: random.Random) -> dict:
    """构建红球(1-33)与蓝球(1-16)的数字权重：频率归一 + 冷号补偿(装饰性) + 随机扰动。"""
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


def _pick_reds(weights: dict, rng: random.Random, totals: dict, forced=()) -> list:
    """按权重无放回抽 6 个红球号，实时奇偶/大小均衡惩罚。

    forced: 必须包含的号码（热号追号用的核心号，v3 新增）。
            先落定 forced，再从剩余号中补足 RED_COUNT - len(forced) 个。
    """
    w = dict(weights["red"])
    chosen = []
    for d in forced:
        chosen.append(d)
        w.pop(d, None)
        totals["r_odd"] += (d % 2 == 1)
        totals["r_even"] += (d % 2 == 0)
        totals["r_big"] += (d >= RED_BIG)
        totals["r_small"] += (d < RED_BIG)
    for _ in range(config.RED_COUNT - len(chosen)):
        w2 = dict(w)
        if totals["r_odd"] > totals["r_even"]:
            for d in w2:
                if d % 2 == 1:
                    w2[d] *= config.BALANCE_PENALTY
        else:
            for d in w2:
                if d % 2 == 0:
                    w2[d] *= config.BALANCE_PENALTY
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
    """按权重无放回抽 1 个蓝球号（奇偶/大小均衡惩罚同样适用）。"""
    w = dict(weights["blue"])
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
    totals["b_odd"] += (d % 2 == 1)
    totals["b_even"] += (d % 2 == 0)
    totals["b_big"] += (d >= BLUE_BIG)
    totals["b_small"] += (d < BLUE_BIG)
    return [d]


def _red_sum_band(records):
    """红球和值经验区间（10%~90% 分位），用于剔除极端和值。"""
    sums = [sum(r.get("reds", [])) for r in records if r.get("reds")]
    if len(sums) < 10:
        return None, None
    sums.sort()
    n = len(sums)
    return sums[n // 10], sums[min(n - 1, n * 9 // 10)]


def _valid_note(reds, blues, red_sum_lo, red_sum_hi, check_sum=True):
    """硬均衡：红球奇偶/大小不极端(2..RED_COUNT-2)，和值在区间内；蓝球无额外奇偶/大小硬约束。

    check_sum=False 时放宽和值约束（热号追号的强制核心号可能与和值区间冲突，
    用于兜底重试，避免候选池被筛空导致静默出 0 注）。
    """
    ro = sum(1 for d in reds if d % 2 == 1)
    if not (2 <= ro <= config.RED_COUNT - 2):
        return False
    rb = sum(1 for d in reds if d >= RED_BIG)
    if not (2 <= rb <= config.RED_COUNT - 2):
        return False
    rs = sum(reds)
    if check_sum and red_sum_lo is not None and not (red_sum_lo <= rs <= red_sum_hi):
        return False
    return True


def _aggregate_balance(notes):
    """计算一组注的奇偶/大小均衡统计（用于报告展示）。"""
    totals = {"r_odd": 0, "r_even": 0, "r_big": 0, "r_small": 0,
              "b_odd": 0, "b_even": 0, "b_big": 0, "b_small": 0}
    for n in notes:
        for d in n["reds"]:
            totals["r_odd"] += (d % 2 == 1)
            totals["r_even"] += (d % 2 == 0)
            totals["r_big"] += (d >= RED_BIG)
            totals["r_small"] += (d < RED_BIG)
        for d in n["blues"]:
            totals["b_odd"] += (d % 2 == 1)
            totals["b_even"] += (d % 2 == 0)
            totals["b_big"] += (d >= BLUE_BIG)
            totals["b_small"] += (d < BLUE_BIG)
    return totals


def _new_coverage(note, covered_r, covered_b):
    """该注能引入的"新"红球/蓝球数字个数。"""
    return len(set(note["reds"]) - covered_r) + len(set(note["blues"]) - covered_b)


def generate_notes(records: list, count: int = config.NOTES, seed=config.SEED):
    """生成 count 注（红球 + 蓝球），返回 (notes, balance)。

    v3 改动 (2026-08-29 热号追号):
      - 每注红球**必含核心热号 TOP2**（近100期频率最高，按月锁定）;
      - 蓝球不锁, 保持权重的奇偶/大小均衡;
      - 成本不变(仍 5 注 / 10 元)。
      ⚠️ 与随机选号数学等价, 不提升任何概率优势, 属投注结构偏好。

    v2 改动:
      - 先生成较大有效候选池;
      - 覆盖最大化贪心: 依次选取能引入最多未覆盖数字的注(经验权重仅作弱 tie-break),
        降低"5注全不中"的方差(期望不变);
      - 返回整组注的聚合均衡统计(原实现只返回末注统计, 已修正)。
    """
    rng = random.Random(seed)
    weights = build_weights(records, rng)
    red_sum_lo, red_sum_hi = _red_sum_band(records)

    # v3: 热号追号 —— 锁定红球核心号（按月缓存，失败则不锁、退化为 v2）
    forced_red = ()
    try:
        from hot_core import get_ssq_core, is_active
        if not is_active():
            raise ValueError("未到生效日，走 v2 回退（不锁核心号）")
        forced_red = tuple(get_ssq_core(records)[0])
    except Exception:
        forced_red = ()

    # 1) 候选池（有效注）
    pool_target = max(count * 12, 80)
    max_attempts = count * 1000

    def _build_pool(check_sum):
        pool = []
        seen = set()
        attempts = 0
        while len(pool) < pool_target and attempts < max_attempts:
            attempts += 1
            totals = {"r_odd": 0, "r_even": 0, "r_big": 0, "r_small": 0,
                      "b_odd": 0, "b_even": 0, "b_big": 0, "b_small": 0}
            reds = _pick_reds(weights, rng, totals, forced=forced_red)
            blues = _pick_blues(weights, rng, totals)
            key = (tuple(reds), tuple(blues))
            if key in seen:
                continue
            if not _valid_note(reds, blues, red_sum_lo, red_sum_hi, check_sum=check_sum):
                continue
            seen.add(key)
            score = (sum(weights["red"][d] for d in reds)
                     + sum(weights["blue"][d] for d in blues))
            pool.append({"reds": reds, "blues": blues, "score": score})
        return pool

    pool = _build_pool(True)
    if not pool and forced_red:
        # 核心热号与和值区间冲突 → 放宽和值约束重试，避免静默出 0 注
        pool = _build_pool(False)

    # 2) 覆盖最大化贪心
    selected = []
    covered_r = set()
    covered_b = set()
    remaining = list(pool)
    while len(selected) < count and remaining:
        best = None
        best_val = None
        for cand in remaining:
            nc = _new_coverage(cand, covered_r, covered_b)
            val = nc + 0.03 * cand["score"]  # 覆盖主导, 经验权重弱 tie-break
            if best_val is None or val > best_val:
                best = cand
                best_val = val
        selected.append(best)
        covered_r |= set(best["reds"])
        covered_b |= set(best["blues"])
        remaining.remove(best)

    # 3) 兜底: 池不足时直接补齐
    if len(selected) < count:
        for c in pool:
            if c not in selected:
                selected.append(c)
            if len(selected) >= count:
                break

    balance = _aggregate_balance(selected)
    return selected, balance
