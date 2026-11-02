# -*- coding: utf-8 -*-
"""
福彩3D 分位（百/十/个）× 大小形态 出号规律分析（只读诊断 + 规则出号）
=====================================================================
用途：
  1) 按百位/十位/个位分别统计数字频率、大小占比、连出与遗漏；
  2) 统计 8 种大小形态（大大大 … 小小小）的真实分布、富集倍数；
  3) 检验「上期形态 → 本期形态」的序列相关（能否据上期推本期）；
  4) 检验三位是否独立（形态概率可否用各位边际相乘）；
  5) 给出可执行的大小形态打分规则（大小钟摆 v1），并输出下一期参考形态与候选号码。

⚠️ 诚实边界（勿删）：
  - 本工具衡量的是「分布与结构」，不产生可盈利的预测力。500 期实测 8 种形态
    卡方不显著（p≈0.48），富集倍数 0.66~1.15，远低于 3D 直选赔率要求的 1.92 倍
    （见 parity_size_test.py 的推导）。规则输出属投注结构偏好，等同机选。
  - 对外表述一律「随机采样」，禁止「推荐/预测/必出」。

用法：
  python position_pattern.py                # 全量分析 + 下一期参考
  python position_pattern.py --json          # 结构化输出
  python position_pattern.py --per-pos 2,2,2 # 指定各位候选数字个数（注数=乘积）
  python position_pattern.py --window 500    # 指定统计窗口
"""
import json
import math
import os
import sys
from collections import Counter, defaultdict

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(BASE_DIR, "data", "3d_history.json")
LONG = os.path.join(BASE_DIR, "data", "backtest_3d_long.json")

BIG = 5                     # 0-4 小 / 5-9 大
POS = ("bai", "shi", "ge")
POS_CN = ("百位", "十位", "个位")
PATTERNS = ["".join("大" if (m >> (2 - i)) & 1 else "小" for i in range(3))
            for m in range(8)]      # 小小小 小小大 小大小 小大大 大小小 大小大 大大小 大大大


# ---------------- 统计工具 ----------------
def chi2_sf(x, df):
    """卡方上尾 p 值（Wilson-Hilferty 近似；df=1 时精确用 erfc）。"""
    if x <= 0:
        return 1.0
    if df == 1:
        return math.erfc(math.sqrt(x / 2.0))
    h = 2.0 / (9.0 * df)
    z = ((x / df) ** (1.0 / 3.0) - (1 - h)) / math.sqrt(h)
    return 0.5 * math.erfc(z / math.sqrt(2.0))


def z_binom(k, n, p=0.5):
    mu, sd = n * p, math.sqrt(n * p * (1 - p))
    return (k - mu) / sd if sd else 0.0


def load(path):
    recs = json.load(open(path, encoding="utf-8"))
    return sorted(recs, key=lambda r: r["qihao"])


def side(d):
    return "大" if d >= BIG else "小"


def pattern_of(r):
    return "".join(side(r[p]) for p in POS)


# ---------------- 1) 分位数字频率 ----------------
def pos_digit_freq(recs, window):
    w = recs[-window:]
    out = {}
    for p, cn in zip(POS, POS_CN):
        c = Counter(r[p] for r in w)
        out[cn] = {d: c.get(d, 0) for d in range(10)}
    return {"window": len(w), "freq": out}


# ---------------- 2) 分位大小 ----------------
def pos_size_stats(recs, window):
    w = recs[-window:]
    n = len(w)
    out = []
    for p, cn in zip(POS, POS_CN):
        big = sum(1 for r in w if r[p] >= BIG)
        z = z_binom(big, n)
        # 当前连出（从最新往回数，同侧连续期数）
        last = side(w[-1][p])
        streak = 0
        for r in reversed(w):
            if side(r[p]) == last:
                streak += 1
            else:
                break
        # 该侧历史最大连出
        mx = cur = 0
        prev = None
        for r in w:
            s = side(r[p])
            if s == prev:
                cur += 1
            else:
                cur = 1
                prev = s
            mx = max(mx, cur)
        # 该侧平均间隔（遗漏均值）
        gaps, gap = [], 0
        for r in w:
            if side(r[p]) == last:
                gaps.append(gap)
                gap = 0
            else:
                gap += 1
        avg_gap = sum(gaps) / len(gaps) if gaps else 0
        out.append({"pos": cn, "n": n,
                    "big_rate": round(big / n, 4), "big_z": round(z, 2),
                    "big_p": round(chi2_sf(z ** 2, 1), 4),
                    "last_side": last, "last_streak": streak,
                    "max_streak": mx,
                    "current_gap_other": gap,
                    "avg_gap": round(avg_gap, 2)})
    return out


# ---------------- 3) 8 种大小形态 ----------------
def pattern_dist(recs, window):
    w = recs[-window:]
    n = len(w)
    c = Counter(pattern_of(r) for r in w)
    chi2 = 0.0
    cells = []
    for pat in PATTERNS:
        obs = c.get(pat, 0)
        exp = n / 8.0
        chi2 += (obs - exp) ** 2 / exp
        rate = obs / n
        cells.append({"pattern": pat, "obs": obs, "exp": round(exp, 1),
                      "rate": round(rate, 4),
                      "enrich": round(rate / 0.125, 3),
                      "z": round(z_binom(obs, n, 0.125), 2)})
    return {"window": n, "chi2": round(chi2, 2), "df": 7,
            "p": round(chi2_sf(chi2, 7), 4), "cells": cells}


# ---------------- 4) 形态 lag-1 转移 ----------------
def pattern_transition(recs, window):
    w = recs[-window:]
    pats = [pattern_of(r) for r in w]
    trans = defaultdict(Counter)
    for a, b in zip(pats[:-1], pats[1:]):
        trans[a][b] += 1
    # 8x8 卡方（独立性）
    rows = {p: sum(trans[p].values()) for p in PATTERNS}
    cols = Counter()
    for p in PATTERNS:
        for q, v in trans[p].items():
            cols[q] += v
    total = sum(rows.values())
    chi2 = 0.0
    for p in PATTERNS:
        for q in PATTERNS:
            e = rows[p] * cols[q] / total if total else 0
            o = trans[p].get(q, 0)
            if e > 0:
                chi2 += (o - e) ** 2 / e
    # 每个上期形态下，本期最偏的形态
    detail = []
    for p in PATTERNS:
        if rows[p] < 20:
            continue
        best = max(PATTERNS, key=lambda q: trans[p].get(q, 0))
        detail.append({"prev": p, "n": rows[p],
                       "top": best, "top_rate": round(trans[p][best] / rows[p], 4),
                       "top_lift": round((trans[p][best] / rows[p]) / 0.125, 3)})
    return {"window": len(w), "transitions": total,
            "chi2": round(chi2, 2), "df": 49,
            "p": round(chi2_sf(chi2, 49), 4), "detail": detail}


# ---------------- 5) 三位独立性（实测 vs 边际相乘） ----------------
def independence(recs, window):
    w = recs[-window:]
    n = len(w)
    marginal = {}
    for p, cn in zip(POS, POS_CN):
        marginal[cn] = sum(1 for r in w if r[p] >= BIG) / n
    c = Counter(pattern_of(r) for r in w)
    chi2 = 0.0
    rows = []
    for pat in PATTERNS:
        p_pred = 1.0
        for ch, cn in zip(pat, POS_CN):
            p_pred *= marginal[cn] if ch == "大" else (1 - marginal[cn])
        obs = c.get(pat, 0)
        exp = n * p_pred
        if exp > 0:
            chi2 += (obs - exp) ** 2 / exp
        rows.append({"pattern": pat, "obs": obs,
                     "exp_indep": round(exp, 1),
                     "obs_rate": round(obs / n, 4),
                     "pred_rate": round(p_pred, 4)})
    # 两两 2x2 卡方
    pair = []
    for i, j in ((0, 1), (1, 2), (0, 2)):
        a = sum(1 for r in w if r[POS[i]] >= BIG and r[POS[j]] >= BIG)
        b = sum(1 for r in w if r[POS[i]] >= BIG and r[POS[j]] < BIG)
        cc = sum(1 for r in w if r[POS[i]] < BIG and r[POS[j]] >= BIG)
        d = n - a - b - cc
        tot = n
        r1, r2 = a + b, cc + d
        c1, c2 = a + cc, b + d
        x2 = 0.0
        for o, e in ((a, r1 * c1 / tot), (b, r1 * c2 / tot),
                     (cc, r2 * c1 / tot), (d, r2 * c2 / tot)):
            if e:
                x2 += (o - e) ** 2 / e
        pair.append({"pair": POS_CN[i] + "-" + POS_CN[j],
                     "chi2": round(x2, 2), "p": round(chi2_sf(x2, 1), 4)})
    return {"window": n, "marginal": {k: round(v, 4) for k, v in marginal.items()},
            "chi2_vs_indep": round(chi2, 2), "df": 7,
            "p_vs_indep": round(chi2_sf(chi2, 7), 4),
            "cells": rows, "pairwise": pair}


# ---------------- 6) 大小钟摆打分规则 ----------------
def score_sides(recs):
    """每位给「大」「小」打分，供形态排序。

    规则（大小钟摆 v1，与 pendulum_v2 同族、降维到大小层）：
      S(侧) = 100 × [ 0.45×回摆 + 0.30×欠账 + 0.25×遗漏 ] + 连出极值加成
      回摆：当前连出 k 期（k≥3 时）→ 反向得分 +min(1, (k-2)/3)
      欠账：近30期该侧占比低于 0.5 → (0.5-占比)/0.5
      遗漏：该侧当前间隔 ÷ 该侧平均间隔（>1 说明等得比历史久）
    """
    out = {}
    for p, cn in zip(POS, POS_CN):
        seq = [side(r[p]) for r in recs]
        cur = seq[-1]
        k = 0
        for s in reversed(seq):
            if s == cur:
                k += 1
            else:
                break
        w30 = seq[-30:]
        rate_big = w30.count("大") / len(w30)
        sc = {}
        for s in ("大", "小"):
            other = "小" if s == "大" else "大"
            # 回摆：若当前连出的是 opposite(s)，则 s 得分
            rebound = 0.0
            if cur == other and k >= 3:
                rebound = min(1.0, (k - 2) / 3.0)
            # 欠账
            share = rate_big if s == "大" else (1 - rate_big)
            debt = max(0.0, (0.5 - share) / 0.5)
            # 遗漏：s 距上次出现的期数 / s 历史平均间隔
            gap = 0
            for x in reversed(seq):
                if x == s:
                    break
                gap += 1
            gaps, g = [], 0
            for x in seq:
                if x == s:
                    gaps.append(g)
                    g = 0
                else:
                    g += 1
            avg = (sum(gaps) / len(gaps)) if gaps else 1.0
            miss = min(2.0, gap / avg) if avg else 0.0
            base = 100 * (0.45 * rebound + 0.30 * debt + 0.25 * (miss / 2.0))
            bonus = 15 if (cur == other and k >= 4) else 0
            sc[s] = round(base + bonus, 2)
        # 归一成相对权重
        tot = sc["大"] + sc["小"] or 1
        out[cn] = {"score": sc,
                   "weight": {"大": round(sc["大"] / tot, 4),
                              "小": round(sc["小"] / tot, 4)},
                   "last_side": cur, "streak": k, "big_rate_30": round(rate_big, 4)}
    return out


def rank_patterns(scores, recs, window):
    """用打分权重给 8 种形态排序，并与历史频率对照。"""
    hist = Counter(pattern_of(r) for r in recs[-window:])
    n = min(window, len(recs))
    rows = []
    for pat in PATTERNS:
        w = 1.0
        for ch, cn in zip(pat, POS_CN):
            w *= scores[cn]["weight"]["大" if ch == "大" else "小"]
        rows.append({"pattern": pat,
                     "rule_weight": round(w, 4),
                     "hist_rate": round(hist.get(pat, 0) / n, 4),
                     "hist_n": hist.get(pat, 0)})
    rows.sort(key=lambda x: -x["rule_weight"])
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


# ---------------- 7) 形态 → 具体号码 ----------------
def build_notes(scores, per_pos, recs, window=100, pattern=None):
    """按指定形态（缺省用打分权重推出的形态），各位取该侧内频率最高的 per_pos 个数字，
    笛卡尔积成注。pattern 形如 "大大小"。"""
    if pattern:
        want = pattern
    else:
        top = []
        for cn in POS_CN:
            w = scores[cn]["weight"]
            top.append("大" if w["大"] >= w["小"] else "小")
        want = "".join(top)
    w = recs[-window:]
    digits = {}
    for p, cn, ch in zip(POS, POS_CN, want):
        c = Counter(r[p] for r in w)
        cand = [d for d in range(10) if side(d) == ch]
        cand.sort(key=lambda d: (-c.get(d, 0), d))
        digits[cn] = cand[:per_pos[POS_CN.index(cn)]]
    notes = []
    for a in digits["百位"]:
        for b in digits["十位"]:
            for c in digits["个位"]:
                notes.append((a, b, c))
    return {"pattern": want, "digits": digits, "notes": notes}


def main():
    as_json = "--json" in sys.argv
    per_pos = (2, 2, 2)
    window = 500
    pattern = None
    for i, a in enumerate(sys.argv):
        if a == "--per-pos" and i + 1 < len(sys.argv):
            per_pos = tuple(int(x) for x in sys.argv[i + 1].split(","))
        if a == "--window" and i + 1 < len(sys.argv):
            window = int(sys.argv[i + 1])
        if a == "--pattern" and i + 1 < len(sys.argv):
            pattern = sys.argv[i + 1]

    short = load(HIST)
    long_ = load(LONG)
    # 合并去重（qihao 唯一），取最近 window 期
    merged = {r["qihao"]: r for r in long_}
    merged.update({r["qihao"]: r for r in short})
    recs = sorted(merged.values(), key=lambda r: r["qihao"])[-window:]

    res = {
        "data": {"n": len(recs), "from": recs[0]["qihao"], "to": recs[-1]["qihao"],
                 "last_draw": recs[-1]["nums"], "last_date": recs[-1]["date"]},
        "pos_digit_freq_100": pos_digit_freq(recs, 100),
        "pos_size_30": pos_size_stats(recs, 30),
        "pos_size_100": pos_size_stats(recs, 100),
        "pattern_30": pattern_dist(recs, 30),
        "pattern_100": pattern_dist(recs, 100),
        "pattern_all": pattern_dist(recs, len(recs)),
        "transition": pattern_transition(recs, len(recs)),
        "independence": independence(recs, len(recs)),
        "scores": score_sides(recs),
        "rank": rank_patterns(score_sides(recs), recs, 100),
        "notes": build_notes(score_sides(recs), per_pos, recs, 100, pattern),
        "pattern_arg": pattern,
        "per_pos": per_pos,
    }
    if as_json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return

    d = res["data"]
    print("=" * 70)
    print("福彩3D 分位×大小形态 分析｜数据 %d 期 (%s ~ %s)"
          % (d["n"], d["from"], d["to"]))
    print("最新开奖 %s = %s (%s)｜大小形态 = %s"
          % (recs[-1]["qihao"], "".join(str(x) for x in d["last_draw"]),
             d["last_date"], pattern_of(recs[-1])))
    print("=" * 70)

    print("\n【1】百/十/个位 数字频率（近100期，加粗为该位前三）")
    fq = res["pos_digit_freq_100"]["freq"]
    for cn in POS_CN:
        row = fq[cn]
        top3 = sorted(range(10), key=lambda x: (-row[x], x))[:3]
        print("  %s  " % cn + "  ".join(
            ("%d:%d*" % (k, row[k]) if k in top3 else "%d:%d" % (k, row[k]))
            for k in range(10)))

    for tag, key in (("近30期", "pos_size_30"), ("近100期", "pos_size_100")):
        print("\n【2】%s 各位大小占比" % tag)
        print("  %-6s %8s %7s %8s %8s %8s" %
              ("位置", "大号占比", "z", "当前连出", "最大连出", "平均间隔"))
        for r in res[key]:
            print("  %-6s %7.1f%% %7.2f %6s×%d %8d %8.1f"
                  % (r["pos"], r["big_rate"] * 100, r["big_z"],
                     r["last_side"], r["last_streak"], r["max_streak"], r["avg_gap"]))

    for tag, key in (("近30期", "pattern_30"), ("近100期", "pattern_100"),
                     ("全样本", "pattern_all")):
        dist = res[key]
        print("\n【3】%s 8 种大小形态分布（期望 %.1f 次）" % (tag, dist["window"] / 8))
        print("  %-8s %6s %7s %8s %9s %6s" %
              ("形态", "实测", "期望", "频率", "富集倍数", "z"))
        for c in sorted(dist["cells"], key=lambda x: -x["obs"]):
            print("  %-8s %6d %7.1f %7.1f%% %9.3f %6.2f"
                  % (c["pattern"], c["obs"], c["exp"], c["rate"] * 100,
                     c["enrich"], c["z"]))
        print("  χ²=%.2f df=7 p=%.4f → %s"
              % (dist["chi2"], dist["p"],
                 "无显著偏离（8 形态近似等概率）" if dist["p"] > 0.05 else "显著偏离"))

    tr = res["transition"]
    print("\n【4】上期形态 → 本期形态 序列相关（%d 次转移）" % tr["transitions"])
    print("  χ²=%.2f df=49 p=%.4f → %s"
          % (tr["chi2"], tr["p"],
             "无显著序列相关（看上期猜不了本期）" if tr["p"] > 0.05 else "存在显著相关"))
    print("  各上期形态下，本期出现最多的形态：")
    print("  %-8s %6s %8s %10s %8s" % ("上期", "样本", "本期最多", "该组合频率", "相对 12.5%"))
    for x in tr["detail"]:
        print("  %-8s %6d %8s %9.1f%% %8.2f×"
              % (x["prev"], x["n"], x["top"], x["top_rate"] * 100, x["top_lift"]))

    ind = res["independence"]
    print("\n【5】三位独立性：实测形态频率 vs 「各位边际相乘」预测")
    print("  χ²=%.2f df=7 p=%.4f → %s"
          % (ind["chi2_vs_indep"], ind["p_vs_indep"],
             "三位相互独立，形态概率=各位概率相乘" if ind["p_vs_indep"] > 0.05
             else "存在位间关联"))
    print("  边际大号率：" + "　".join("%s %.1f%%" % (k, v * 100)
                                   for k, v in ind["marginal"].items()))
    for x in ind["pairwise"]:
        print("  两两独立性 %-12s χ²=%.2f p=%.4f %s"
              % (x["pair"], x["chi2"], x["p"],
                 "独立" if x["p"] > 0.05 else "相关"))

    sc = res["scores"]
    print("\n【6】大小钟摆打分（规则，非预测）")
    for cn in POS_CN:
        s = sc[cn]
        print("  %s  当前连出 %s×%d｜近30期大号率 %.1f%%｜大分 %.1f 小分 %.1f → 权重 大%.2f/小%.2f"
              % (cn, s["last_side"], s["streak"], s["big_rate_30"] * 100,
                 s["score"]["大"], s["score"]["小"],
                 s["weight"]["大"], s["weight"]["小"]))

    print("\n【7】8 种形态排序（按规则权重；历史频率列作对照）")
    print("  %4s %-8s %10s %10s %6s" % ("排名", "形态", "规则权重", "历史频率", "样本"))
    for r in res["rank"]:
        print("  %4d %-8s %10.4f %9.1f%% %6d"
              % (r["rank"], r["pattern"], r["rule_weight"],
                 r["hist_rate"] * 100, r["hist_n"]))

    nt = res["notes"]
    print("\n【8】参考组合（形态 %s，各位取该侧近100期频率最高 %s 个数字）"
          % (nt["pattern"], "/".join(str(x) for x in res["per_pos"])))
    for cn in POS_CN:
        print("  %s 候选：%s" % (cn, " ".join(str(x) for x in nt["digits"][cn])))
    print("  注数 %d，成本 %d 元" % (len(nt["notes"]), len(nt["notes"]) * 2))
    for i, n in enumerate(nt["notes"], 1):
        print("    %2d. %d %d %d" % (i, n[0], n[1], n[2]))

    print("\n⚠️ 以上为规则输出（随机采样口径），等同机选、无预测力。"
          "8 形态卡方与序列相关检验均未给出可用信号，"
          "直选单注中奖率恒 0.1%、返奖率 52%，不构成投注建议。")


if __name__ == "__main__":
    main()
