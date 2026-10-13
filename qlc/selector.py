# -*- coding: utf-8 -*-
"""
七乐彩 选号引擎 v3（2026-10-13 新增，与 dlt/ssq 口径对齐）
-------------------------------------------------------
每注 = 基本号码 7 个不重复号(01-30) + 特别号码 1 个（官方规则：特别号只有 1 个），
生成 NOTES 注；开奖日 周一/三/五，每周 3 期，成本 5注×2元×3期 = 30 元/周。

选号要素（与 dlt/ssq v3 完全一致的口径）:
  1) 经验频率加权：基本号近 100 期频率归一作先验，使号码"典型"；
  2) 奇偶/大小均衡：单注内对多数方加权惩罚，逼近 50:50；
  3) 覆盖最大化贪心：优先选能引入最多未覆盖数字的注，降低"5注全不中"的方差；
  4) v3 热号追号：每注基本号**必含核心热号 TOP2**（近100期频率最高，按月锁定），
     特别号码不锁；
  5) 和值区间：剔除 P10~P90 之外��极端和值。

与 dlt/ssq 的实现差异（有意为之）:
  * 首抽不做均衡惩罚 —— dlt/ssq 旧实现中首抽时 totals 全为 0，`if a > b` 恒为 False
    会固定惩罚偶数/小号一方（审计 P2-4：实测 ssq 蓝球奇数占比达 75%）。本实现判断
    `> 0` 后再惩罚，首抽无偏。
  * _valid_note 不约束特别号（SPECIAL_COUNT=1，奇偶/大小约束无意义）。

⚠️ 公平随机下每注一等奖概率恒为 1/2,035,800，本引擎不改变负 EV 与理论中奖率；
   热号锁定与结构约束均属投注结构偏好，不具备预测能力。
"""
import random
from .analysis import red_freq, blue_freq, hot_cold
from . import config

ENGINE_VERSION = "v3"  # 选号引擎版本，供报告/推送标注

BASIC_BIG = config.BASIC_BIG_THRESHOLD


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
    """构建基本号(1-30)与特别号(1-30)的权重：频率归一 + 冷号补偿(装饰性) + 随机扰动。"""
    hc = hot_cold(records, config.WINDOW)
    rfc, bfc = hc["red_freq"], hc["blue_freq"]
    r_miss, b_miss = hc["red_omission"], hc["blue_omission"]
    rmax = max(r_miss.values()) or 1
    bmax = max(b_miss.values()) or 1

    basic_w = {}
    tot_r = sum(rfc.values()) or 1
    for d in range(config.BASIC_MIN, config.BASIC_MAX + 1):
        freq_norm = rfc.get(d, 0) / tot_r
        cold_bonus = (r_miss.get(d, config.WINDOW) / rmax) * config.COLD_WEIGHT
        perturb = rng.uniform(-config.PERTURB, config.PERTURB)
        basic_w[d] = max(0.01, freq_norm + cold_bonus + perturb)

    special_w = {}
    tot_b = sum(bfc.values()) or 1
    for d in range(config.SPECIAL_MIN, config.SPECIAL_MAX + 1):
        freq_norm = bfc.get(d, 0) / tot_b
        cold_bonus = (b_miss.get(d, config.WINDOW) / bmax) * config.COLD_WEIGHT
        perturb = rng.uniform(-config.PERTURB, config.PERTURB)
        special_w[d] = max(0.01, freq_norm + cold_bonus + perturb)

    return {"red": basic_w, "blue": special_w}


def _pick_basics(weights: dict, rng: random.Random, totals: dict, forced=()) -> list:
    """按权重无放回抽 7 个基本号码，实时奇偶/大小均衡惩罚。

    forced: 必须包含的号码（热号追号核心号）。先落定 forced 再补足。
    首抽惩罚修正：仅当某一侧计数 > 0 且确实占多数时才惩罚，避免首抽恒定惩罚一侧。
    """
    w = dict(weights["red"])
    chosen = []
    for d in forced:
        if d not in w:
            continue
        chosen.append(d)
        w.pop(d, None)
        totals["r_odd"] += (d % 2 == 1)
        totals["r_even"] += (d % 2 == 0)
        totals["r_big"] += (d >= BASIC_BIG)
        totals["r_small"] += (d < BASIC_BIG)
    while len(chosen) < config.BASIC_COUNT:
        w2 = dict(w)
        n_odd, n_even = totals["r_odd"], totals["r_even"]
        if n_odd > n_even:                      # 奇数占多数 → 惩罚奇数（首抽 n=0 时不触发）
            for d in w2:
                if d % 2 == 1:
                    w2[d] *= config.BALANCE_PENALTY
        elif n_even > n_odd:
            for d in w2:
                if d % 2 == 0:
                    w2[d] *= config.BALANCE_PENALTY
        n_big, n_small = totals["r_big"], totals["r_small"]
        if n_big > n_small:
            for d in w2:
                if d >= BASIC_BIG:
                    w2[d] *= config.BALANCE_PENALTY
        elif n_small > n_big:
            for d in w2:
                if d < BASIC_BIG:
                    w2[d] *= config.BALANCE_PENALTY
        if not w2:
            break
        d = _weighted_choice(w2, rng)
        chosen.append(d)
        w.pop(d, None)
        totals["r_odd"] += (d % 2 == 1)
        totals["r_even"] += (d % 2 == 0)
        totals["r_big"] += (d >= BASIC_BIG)
        totals["r_small"] += (d < BASIC_BIG)
    return sorted(chosen)


def _pick_special(weights: dict, rng: random.Random, basics: list) -> list:
    """从剩余号码中按权重抽 1 个特别号码（不得与基本号重复）。"""
    w = {d: v for d, v in weights["blue"].items() if d not in basics}
    if not w:
        return []
    return [_weighted_choice(w, rng)]


def _basic_sum_band(records):
    """基本号和值经验区间（10%~90% 分位），用于剔除极端和值。"""
    sums = [sum(r.get("reds", [])) for r in records if r.get("reds")]
    if len(sums) < 10:
        return None, None
    sums.sort()
    n = len(sums)
    return sums[n // 10], sums[min(n - 1, n * 9 // 10)]


def _valid_note(basics, special, sum_lo, sum_hi, check_sum=True):
    """硬均衡：基本号奇偶/大小不极端（3..BASIC_COUNT-3），和值在经验区间内。

    check_sum=False 时放宽和值约束（核心热号可能与和值区间冲突，兜底重试，
    避免候选池被筛空导致静默出 0 注）。
    特别号码不设奇偶/大小约束（仅 1 个，约束无意义）。
    """
    bo = sum(1 for d in basics if d % 2 == 1)
    if not (3 <= bo <= config.BASIC_COUNT - 3):
        return False
    bb = sum(1 for d in basics if d >= BASIC_BIG)
    if not (3 <= bb <= config.BASIC_COUNT - 3):
        return False
    bs = sum(basics)
    if check_sum and sum_lo is not None and not (sum_lo <= bs <= sum_hi):
        return False
    if len(set(basics)) != config.BASIC_COUNT:
        return False
    if len(special) != config.SPECIAL_COUNT:
        return False
    if special and special[0] in basics:
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
            totals["r_big"] += (d >= BASIC_BIG)
            totals["r_small"] += (d < BASIC_BIG)
        for d in n.get("blues", []):
            totals["b_odd"] += (d % 2 == 1)
            totals["b_even"] += (d % 2 == 0)
            totals["b_big"] += (d >= BASIC_BIG)
            totals["b_small"] += (d < BASIC_BIG)
    return totals


def _new_coverage(note, covered_r, covered_b):
    """该注能引入的"新"基本号/特别号个数。"""
    return len(set(note["reds"]) - covered_r) + len(set(note.get("blues", [])) - covered_b)


def generate_notes(records: list, count: int = config.NOTES, seed=config.SEED):
    """生成 count 注（基本号 7 + 特别号 1），返回 (notes, balance)。

    v3（热号追号）：每注基本号必含核心热号 TOP2（近100期频率最高，按月锁定），
    特别号码不锁；成本不变（5 注 / 10 元每期）。
    ⚠️ 与随机选号数学等价，不提升任何概率优势，属投注结构偏好。
    """
    rng = random.Random(seed)
    weights = build_weights(records, rng)
    sum_lo, sum_hi = _basic_sum_band(records)

    # v3: 热号追号 —— 锁定基本号核心号（按月缓存，失败则不锁、退化为基础逻辑）
    forced = ()
    try:
        from hot_core import get_qlc_core, is_active
        if not is_active():
            raise ValueError("未到生效日，不锁核心号")
        forced = tuple(get_qlc_core(records)[0])
        if len(forced) > config.BASIC_COUNT:
            forced = ()
    except Exception:
        forced = ()

    pool_target = max(count * 16, 80)
    max_attempts = count * 1000

    def _build_pool(check_sum):
        pool = []
        seen = set()
        attempts = 0
        while len(pool) < pool_target and attempts < max_attempts:
            attempts += 1
            totals = {"r_odd": 0, "r_even": 0, "r_big": 0, "r_small": 0,
                      "b_odd": 0, "b_even": 0, "b_big": 0, "b_small": 0}
            basics = _pick_basics(weights, rng, totals, forced=forced)
            if len(basics) < config.BASIC_COUNT:
                continue
            special = _pick_special(weights, rng, basics)
            key = (tuple(basics), tuple(special))
            if key in seen:
                continue
            if not _valid_note(basics, special, sum_lo, sum_hi, check_sum=check_sum):
                continue
            seen.add(key)
            score = (sum(weights["red"][d] for d in basics)
                     + sum(weights["blue"][d] for d in special))
            pool.append({"reds": basics, "blues": special, "score": score})
        return pool

    pool = _build_pool(True)
    if not pool and forced:
        # 核心热号与和值/均衡区间冲突 → 放宽和值约束重试，避免静默出 0 注
        pool = _build_pool(False)

    # 覆盖最大化贪心
    selected = []
    covered_r, covered_b = set(), set()
    remaining = list(pool)
    while len(selected) < count and remaining:
        best, best_val = None, None
        for cand in remaining:
            nc = _new_coverage(cand, covered_r, covered_b)
            val = nc + 0.03 * cand["score"]
            if best_val is None or val > best_val:
                best, best_val = cand, val
        selected.append(best)
        covered_r |= set(best["reds"])
        covered_b |= set(best.get("blues", []))
        remaining.remove(best)

    # 兜底：池不足时直接补齐
    if len(selected) < count:
        for c in pool:
            if c not in selected:
                selected.append(c)
            if len(selected) >= count:
                break

    balance = _aggregate_balance(selected)
    return selected, balance
