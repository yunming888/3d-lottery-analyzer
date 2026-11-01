# -*- coding: utf-8 -*-
"""
福彩3D「大小 / 奇偶」可预测性检验（只读诊断，不接每日链路，不改出号/结算）
=====================================================================
目的：回答一个具体问题——能否利用「大/小、奇/偶」这类二元属性提高中奖率？

检验分三层（逐层收窄，任一层不显著则该路不通）：
  L1 边际层：百/十/个 三位的奇数占比、大号(5-9)占比 是否为 50:50（卡方 df=1）
  L2 形态层：8 种奇偶形态 / 8 种大小形态 是否符合理论均匀分布（卡方 df=7）
             并检验"富集倍数"= 实测频率 ÷ 号码数占比，盈利门槛 1.92 倍
  L3 序列层：上期属性 → 本期属性 的 2x2 独立性（lag-1/2/3），即"跟"或"反"有无优势
  L4 赔付层：覆盖 n 注的期望恒等式（不依赖数据，纯赔率结构）

关键门槛（重要，勿误读）：
  买满子集 S（|S| 注）最多中 1 注，收益 1040，成本 2|S|
  → 盈利需 P(开奖∈S) > 2|S|/1040 = |S|/520
  → 而公平分布下 P = |S|/1000
  → 即实测频率必须达到「号码占比」的 1040/(2*520)=1.92 倍，才有正期望

用法：python parity_size_test.py [--json]
"""
import json
import math
import sys
import os
import random
from collections import Counter

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LONG = os.path.join(BASE_DIR, "data", "backtest_3d_long.json")
SHORT = os.path.join(BASE_DIR, "data", "3d_history.json")

BIG_THRESHOLD = 5          # 0-4 小 / 5-9 大（各 5 个，对称）
PRIZE = 1040               # 直选单注奖金
COST = 2                   # 直选单注成本
BREAKEVEN_MULT = PRIZE / (2 * (PRIZE / COST) / 2)  # 1.92，见文档说明


def _chi2_p_df1(x):
    """卡方 df=1 的 p 值（双尾），用正态近似：p = 2*(1-Phi(sqrt(x)))。"""
    return math.erfc(math.sqrt(x / 2.0))


def _chi2_p_sf(x, df):
    """卡方上尾 p 值（Wilson-Hilferty 近似），用于 df=7 等。"""
    if x <= 0:
        return 1.0
    h = 2.0 / (9.0 * df)
    z = ((x / df) ** (1.0 / 3.0) - (1 - h)) / math.sqrt(h)
    return 0.5 * math.erfc(z / math.sqrt(2.0))


def _binom_z(k, n, p=0.5):
    """二项比例 z 值（无连续性修正）。"""
    mu = n * p
    sd = math.sqrt(n * p * (1 - p))
    return (k - mu) / sd if sd else 0.0


def load(path):
    recs = json.load(open(path, encoding="utf-8"))
    # 统一为从旧到新的升序
    recs = sorted(recs, key=lambda r: r["qihao"])
    return recs


def digits(r):
    return [r["bai"], r["shi"], r["ge"]]


# ---------------- L1 边际层 ----------------
def l1_marginal(recs):
    out = []
    n = len(recs)
    for idx, name in ((0, "百位"), (1, "十位"), (2, "个位")):
        ds = [digits(r)[idx] for r in recs]
        odd = sum(1 for d in ds if d % 2 == 1)
        big = sum(1 for d in ds if d >= BIG_THRESHOLD)
        z_odd = _binom_z(odd, n)
        z_big = _binom_z(big, n)
        out.append({
            "pos": name, "n": n,
            "odd_rate": odd / n, "odd_z": z_odd, "odd_p": _chi2_p_df1(z_odd ** 2),
            "big_rate": big / n, "big_z": z_big, "big_p": _chi2_p_df1(z_big ** 2),
        })
    ds = [d for r in recs for d in digits(r)]
    odd = sum(1 for d in ds if d % 2 == 1)
    big = sum(1 for d in ds if d >= BIG_THRESHOLD)
    z_odd = _binom_z(odd, len(ds))
    z_big = _binom_z(big, len(ds))
    out.append({
        "pos": "合计(1500位)", "n": len(ds),
        "odd_rate": odd / len(ds), "odd_z": z_odd, "odd_p": _chi2_p_df1(z_odd ** 2),
        "big_rate": big / len(ds), "big_z": z_big, "big_p": _chi2_p_df1(z_big ** 2),
    })
    return out


# ---------------- L2 形态层 ----------------
def _pattern_counts(recs, kind):
    """kind='odd' 统计奇偶形态（每位奇=1）；kind='big' 统计大小形态。"""
    c = Counter()
    for r in recs:
        dg = digits(r)
        if kind == "odd":
            key = tuple(1 if d % 2 == 1 else 0 for d in dg)
        else:
            key = tuple(1 if d >= BIG_THRESHOLD else 0 for d in dg)
        c[key] += 1
    return c


def l2_pattern(recs):
    n = len(recs)
    res = {}
    for kind, label in (("odd", "奇偶"), ("big", "大小")):
        c = _pattern_counts(recs, kind)
        # 枚举全部 8 种形态，每种对应 125 个号码（每位 5 个数字）
        cells = []
        chi2 = 0.0
        for mask in range(8):
            key = tuple((mask >> (2 - i)) & 1 for i in range(3))
            obs = c.get(key, 0)
            exp = n / 8.0
            chi2 += (obs - exp) ** 2 / exp
            p_hat = obs / n
            base = 125 / 1000.0      # 该形态覆盖的号码占比
            cells.append({
                "pattern": "".join("奇" if b else "偶" for b in key) if kind == "odd"
                           else "".join("大" if b else "小" for b in key),
                "obs": obs, "exp": round(exp, 1),
                "rate": round(p_hat, 4),
                "enrich": round(p_hat / base, 3),
                "z": round(_binom_z(obs, n, 0.125), 2),
            })
        res[label] = {"chi2": round(chi2, 2), "df": 7,
                      "p": round(_chi2_p_sf(chi2, 7), 4), "cells": cells}
    return res


def _subset_stats(recs, predicate, size, name, price=PRIZE, cost=COST):
    """给定号码子集（predicate 判定 000-999 是否属于该子集），统计富集倍数。"""
    n = len(recs)
    obs = sum(1 for r in recs if predicate(digits(r)))
    exp = n * size / 1000.0
    rate = obs / n
    base = size / 1000.0
    z = (obs - exp) / math.sqrt(exp * (1 - base)) if exp > 0 else 0.0
    # 买满该子集的盈亏（最多中 1 注）
    pnl = obs * price - n * size * cost
    return {
        "name": name, "size": size, "base_rate": round(base, 4),
        "obs": obs, "exp": round(exp, 1), "rate": round(rate, 4),
        "enrich": round(rate / base, 3) if base else None,
        "z": round(z, 2),
        "breakeven_mult": round(size / 520.0 / base, 2) if base else None,
        "pnl_if_buy_all": pnl,
    }


def l2b_subsets(recs):
    """针对常见「形态/区间」子集算富集倍数，看有没有接近 1.92 的。"""
    def has(dg, f):
        return f(dg)

    defs = [
        ("3位全奇", lambda d: all(x % 2 == 1 for x in d), 125),
        ("3位全偶", lambda d: all(x % 2 == 0 for x in d), 125),
        ("2奇1偶", lambda d: sum(1 for x in d if x % 2 == 1) == 2, 375),
        ("2偶1奇", lambda d: sum(1 for x in d if x % 2 == 1) == 1, 375),
        ("3位全大", lambda d: all(x >= BIG_THRESHOLD for x in d), 125),
        ("3位全小", lambda d: all(x < BIG_THRESHOLD for x in d), 125),
        ("2大1小", lambda d: sum(1 for x in d if x >= BIG_THRESHOLD) == 2, 375),
        ("2小1大", lambda d: sum(1 for x in d if x >= BIG_THRESHOLD) == 1, 375),
        ("2奇1偶且2大1小", lambda d: sum(1 for x in d if x % 2 == 1) == 2
                                   and sum(1 for x in d if x >= BIG_THRESHOLD) == 2, 188),
        ("和值10-17", lambda d: 10 <= sum(d) <= 17, 0),
        ("和值13-16", lambda d: 13 <= sum(d) <= 16, 0),
    ]
    # 和值类子集精确枚举号码数
    enum_size = {}
    for mask in range(1000):
        d = [mask // 100, (mask // 10) % 10, mask % 10]
        for name, f, _ in defs:
            if name.startswith("和值") and f(d):
                enum_size[name] = enum_size.get(name, 0) + 1
    out = []
    for name, f, size in defs:
        if size == 0:
            size = enum_size.get(name, 0)
        if size == 0:
            continue
        out.append(_subset_stats(recs, f, size, name))
    return out


# ---------------- L3 序列层 ----------------
def l3_serial(recs, max_lag=3):
    """上期属性 → 本期属性 的独立性检验（跟号/反号是否有优势）。"""
    out = []
    for lag in range(1, max_lag + 1):
        for idx, name in ((0, "百位"), (1, "十位"), (2, "个位")):
            a = [1 if digits(r)[idx] % 2 == 1 else 0 for r in recs]
            # a[t-lag] -> a[t]
            pairs = [(a[i - lag], a[i]) for i in range(lag, len(a))]
            c = Counter(pairs)
            n = len(pairs)
            # 2x2 卡方
            o = [[c.get((0, 0), 0), c.get((0, 1), 0)],
                 [c.get((1, 0), 0), c.get((1, 1), 0)]]
            tot = sum(sum(r) for r in o)
            r0, r1 = sum(o[0]), sum(o[1])
            c0, c1 = o[0][0] + o[1][0], o[0][1] + o[1][1]
            chi2 = 0.0
            for i in range(2):
                for j in range(2):
                    e = (r0, r1)[i] * (c0, c1)[j] / tot
                    if e:
                        chi2 += (o[i][j] - e) ** 2 / e
            # 「同位跟上期同奇偶」与「反向」的命中率
            same = o[0][0] + o[1][1]
            out.append({
                "lag": lag, "pos": name, "n": n,
                "p_odd_given_prev_odd": round(o[1][1] / r1, 4) if r1 else None,
                "p_odd_given_prev_even": round(o[0][1] / r0, 4) if r0 else None,
                "same_rate": round(same / n, 4),
                "same_z": round(_binom_z(same, n, 0.5), 2),
                "chi2": round(chi2, 2), "p": round(_chi2_p_df1(chi2), 4),
            })
    return out


# ---------------- L4 赔付层（纯数学，不依赖数据） ----------------
def l4_payout():
    fair_prize = COST * 1000          # 公平赔率：2 元 × 1000 种可能
    rows = []
    for size in (1, 9, 12, 125, 375, 500, 1000):
        p = size / 1000.0
        cost = size * COST
        ev = p * PRIZE - cost
        rows.append({
            "notes": size, "hit_prob": round(p, 4), "cost": cost,
            "ev": round(ev, 2), "roi": round(ev / cost, 4) if cost else None,
            "ev_per_note": round(ev / size, 4) if size else None,
        })
    return {"fair_prize": fair_prize, "actual_prize": PRIZE,
            "house_edge": round(1 - PRIZE / fair_prize, 4), "rows": rows}


def main():
    as_json = "--json" in sys.argv
    recs = load(LONG)
    res = {
        "data": {"file": os.path.basename(LONG), "n_draws": len(recs),
                 "from": recs[0]["qihao"], "to": recs[-1]["qihao"]},
        "L1_marginal": l1_marginal(recs),
        "L2_pattern": l2_pattern(recs),
        "L2b_subsets": l2b_subsets(recs),
        "L3_serial": l3_serial(recs),
        "L4_payout": l4_payout(),
    }
    if as_json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return

    print("=" * 66)
    print("福彩3D 大小/奇偶 可预测性检验（%d 期：%s ~ %s）"
          % (len(recs), recs[0]["qihao"], recs[-1]["qihao"]))
    print("=" * 66)

    print("\n[L1] 边际层：三位奇偶/大小是否 50:50")
    print("  %-10s %6s %8s %7s %8s %7s" % ("位置", "期数", "奇数占比", "z", "大号占比", "z"))
    for r in res["L1_marginal"]:
        print("  %-10s %6d %8.1f%% %7.2f %8.1f%% %7.2f"
              % (r["pos"], r["n"], r["odd_rate"] * 100, r["odd_z"],
                 r["big_rate"] * 100, r["big_z"]))

    for label in ("奇偶", "大小"):
        d = res["L2_pattern"][label]
        print("\n[L2] %s形态分布（8 种，各对应 125 个号码，期望各 %.1f 次）"
              % (label, len(recs) / 8))
        print("  %-8s %6s %7s %7s %8s %6s" % ("形态", "实测", "期望", "频率", "富集倍数", "z"))
        for c in d["cells"]:
            print("  %-8s %6d %7.1f %7.1f%% %8.3f %6.2f"
                  % (c["pattern"], c["obs"], c["exp"], c["rate"] * 100,
                     c["enrich"], c["z"]))
        print("  卡方=%.2f df=7 p=%.4f %s"
              % (d["chi2"], d["p"], "→ 无显著偏离" if d["p"] > 0.05 else "→ 显著"))

    print("\n[L2b] 常见子集富集倍数（盈利需 ≥1.92 倍）")
    print("  %-18s %5s %6s %6s %8s %7s %8s" %
          ("子集", "注数", "实测", "期望", "富集倍数", "z", "买满盈亏"))
    for r in res["L2b_subsets"]:
        print("  %-18s %5d %6d %6.1f %8.3f %7.2f %8d"
              % (r["name"], r["size"], r["obs"], r["exp"],
                 r["enrich"], r["z"], r["pnl_if_buy_all"]))

    print("\n[L3] 序列层：上期→本期 同位属性（跟/反有无优势）")
    print("  %4s %6s %7s %10s %10s %8s %7s" %
          ("lag", "位置", "同向率", "P奇|上期奇", "P奇|上期偶", "chi2", "p"))
    for r in res["L3_serial"]:
        print("  %4d %6s %6.1f%% %11.1f%% %11.1f%% %8.2f %7.4f"
              % (r["lag"], r["pos"], r["same_rate"] * 100,
                 (r["p_odd_given_prev_odd"] or 0) * 100,
                 (r["p_odd_given_prev_even"] or 0) * 100,
                 r["chi2"], r["p"]))

    lp = res["L4_payout"]
    print("\n[L4] 赔付层：公平赔率 %d 元/注 vs 实际 %d 元 → 庄家优势 %.1f%%"
          % (lp["fair_prize"], lp["actual_prize"], lp["house_edge"] * 100))
    print("  %6s %8s %7s %9s %8s %10s" % ("注数", "命中率", "成本", "期望盈亏", "ROI", "每注期望"))
    for r in lp["rows"]:
        print("  %6d %7.1f%% %7d %9.2f %7.1f%% %10.2f"
              % (r["notes"], r["hit_prob"] * 100, r["cost"], r["ev"],
                 r["roi"] * 100, r["ev_per_note"]))
    print("\n结论：任何以「形态/大小奇偶」缩小范围的买法，只要不增加覆盖注数，"
          "单注命中率恒 0.1%；一旦增加覆盖，成本线性上升，每注期望恒亏 0.96 元。")


if __name__ == "__main__":
    main()
