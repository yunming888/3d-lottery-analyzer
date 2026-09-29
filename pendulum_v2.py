# -*- coding: utf-8 -*-
"""
福彩3D 钟摆原理 v2（在 pendulum.py v1 基础上的升级版）
========================================================
只读诊断工具，不接每日链路，不改出号/结算逻辑。

相对 v1 的升级点
----------------
U1 多窗口融合：10 / 30 / 60 期三窗口加权(C=0.25/0.50/0.25)替代单一 30 期窗口，
   短窗抓动量、长窗抓均值回归，降低单窗口噪声。
U2 Z 值标准化：数字热度改用 z=(观测频率-0.1)/√(0.1·0.9/n_eff)，
   n_eff=1/Σ(w_i²/n_i)，过热(|z|>HOT_CAP)降权、过冷不盲目追，替代原始计数。
U3 极值回撤维度：最新值落在边界{0,9}或同侧连出≥3期时，回摆系数 0.80→1.00。
U4 和值分位带：改用近100期和值 P20–P80 动态带过滤候选（不足时放宽至 P10–P90），
   替代 v1「峰值±2」窄带，避免和值带过窄导致凑注失真。
U5 区域多样性约束：禁止三位同区；三区互异的注数不少于 1/3，避免候选塌缩到单区。
U6  annotation：输出候选奇偶/大小/区间分布，便于人工核对结构。

⚠️ 性质：候选号码为随机采样，等同机选、无预测力，直选单注中奖概率恒 0.1%。
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import statistics
import sys
from itertools import product

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pendulum as P  # noqa: E402  （复用 v1 的基础统计）

BASE_DIR = P.BASE_DIR
REPORT_DIR = P.REPORT_DIR
ZONES, ZONE_CENTER, ZONE_LABEL, ZONE_SIZE = P.ZONES, P.ZONE_CENTER, P.ZONE_LABEL, P.ZONE_SIZE
POSITIONS = P.POSITIONS

# ---- v2 可调参数 ----
WINDOWS = (10, 30, 60)
WINDOW_W = (0.25, 0.50, 0.25)
HOT_CAP = 2.0            # U2：|z| > 此值视为过热/过冷
HOT_PENALTY = 0.80       # 过热降权系数
COLD_PENALTY = 0.90      # 过冷降权系数
REBOUND_BASE = 0.80      # U3：常态回摆系数
REBOUND_EXTREME = 1.00   # U3：极值触发后的回摆系数
EXTREME_STREAK = 3
MOM_GAIN = 0.40          # 动量修正（沿用 v1）
W_PULL, W_DEFICIT, W_MISS = 0.45, 0.30, 0.25
SUM_WINDOW = 100         # U4：和值带窗口
SUM_Q = (0.20, 0.80)     # U4：首选分位带
SUM_Q_WIDE = (0.10, 0.90)
PER_POS = (3, 3, 2)
MAX_NOTES = 20
DIVERSITY_MIN = 1 / 3    # U5：三区互异注数占比下限

DISCLAIMER = (
    "> ⚠️ **性质声明**：以下号码为按历史分布**随机采样**生成，**等同投注站机选、无预测力**。\n"
    "> 福彩3D 直选单注中奖概率恒为 0.1%（奖金1040元/成本2元，ROI≈52%），"
    "v2 的升级只改变候选结构与可解释性，**不改变任何一注的中奖概率**。\n"
    "> 仅供学习研究，不构成投注建议；任何收费荐号均属诈骗。"
)


def _quantile(sorted_vals, q):
    if not sorted_vals:
        return 0.0
    idx = q * (len(sorted_vals) - 1)
    lo, hi = int(idx), min(int(idx) + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (idx - lo)


# =====================================================
# U1 多窗口融合
# =====================================================
def fused_profile(vals: list) -> dict:
    """把 10/30/60 三窗口的单位置画像加权融合为一个。"""
    profs = [P.position_profile(vals, w) for w in WINDOWS]
    # 有效样本量（各窗口加权后的等效独立样本）
    inv = sum(w * w / pr["window"] for w, pr in zip(WINDOW_W, profs))
    n_eff = 1.0 / inv if inv else 1.0

    center = sum(w * pr["center"] for w, pr in zip(WINDOW_W, profs))
    freq_p = {d: sum(w * pr["freq"][d] / pr["window"]
                     for w, pr in zip(WINDOW_W, profs)) for d in range(10)}
    sd = (0.1 * 0.9 / n_eff) ** 0.5
    z_freq = {d: (freq_p[d] - 0.1) / sd for d in range(10)}

    zone_deficit = {z: sum(w * pr["zone_deficit"][z]
                           for w, pr in zip(WINDOW_W, profs)) for z in ZONES}
    zone_miss = {z: sum(w * pr["zone_miss"][z]
                        for w, pr in zip(WINDOW_W, profs)) for z in ZONES}
    digit_miss = {d: sum(w * pr["digit_miss"][d]
                         for w, pr in zip(WINDOW_W, profs)) for d in range(10)}

    # 动量：近5期 vs 前5期（沿用 v1 口径）
    momentum = P.position_profile(vals, max(vals and 30 or 30, 30))["momentum"]
    extreme_streak = profs[0]["extreme_streak"]          # 短窗连出，更敏感
    extreme_side = profs[0]["extreme_side"]

    return {
        "n_eff": round(n_eff, 1),
        "center": center,
        "offset": center - P.AXIS_CENTER,
        "amplitude": abs(center - P.AXIS_CENTER) / P.AXIS_CENTER,
        "momentum": momentum,
        "freq_p": freq_p,
        "z_freq": z_freq,
        "zone_deficit": zone_deficit,
        "zone_miss": zone_miss,
        "digit_miss": digit_miss,
        "extreme_streak": extreme_streak,
        "extreme_side": extreme_side,
        "last": vals[-1],
        "last_is_edge": vals[-1] in (0, 9),
    }


# =====================================================
# U2/U3 打分
# =====================================================
def score_zones_v2(prof: dict) -> tuple:
    extreme = prof["last_is_edge"] or prof["extreme_streak"] >= EXTREME_STREAK  # U3
    rebound = REBOUND_EXTREME if extreme else REBOUND_BASE
    target = prof["center"] - rebound * prof["offset"] - MOM_GAIN * prof["momentum"]
    target = P._clip(target, 0.0, 9.0)
    out = {}
    for z in ZONES:
        pull = P._clip(1 - abs(ZONE_CENTER[z] - target) / P.AXIS_CENTER)
        deficit = P._clip(prof["zone_deficit"][z], 0.0, 1.0)
        miss = P._clip(prof["zone_miss"][z] / (2 * 10.0 / ZONE_SIZE[z]))
        out[z] = {"score": round(100 * (W_PULL * pull + W_DEFICIT * deficit + W_MISS * miss), 1),
                  "pull": round(pull, 3), "deficit": round(deficit, 3), "miss": round(miss, 3)}
    return out, round(target, 2), extreme, rebound


def pick_digits_v2(prof: dict, zone_scores: dict, zone_rank: list, n_digit: int) -> list:
    """U2：区域分 × 热度(z标准化后封顶) × 遗漏。"""
    ranked = []
    rank_idx = {z: i for i, z in enumerate(zone_rank)}
    for d in range(10):
        z = P.zone_of(d)
        heat = prof["freq_p"][d] / max(prof["freq_p"].values())
        zf = prof["z_freq"][d]
        if zf > HOT_CAP:
            heat *= HOT_PENALTY          # 过热降权，抑制追高
        elif zf < -HOT_CAP:
            heat *= COLD_PENALTY         # 过冷也不盲目追
        miss_n = P._clip(prof["digit_miss"][d] / 20.0)
        s = 0.45 * (zone_scores[z]["score"] / 100.0) + 0.30 * heat + 0.25 * miss_n
        ranked.append((d, s, z))
    ranked.sort(key=lambda x: (-x[1], rank_idx[x[2]], x[0]))
    picked = [d for d, _, _ in ranked[:n_digit]]
    # 多样性：候选数 ≥3 时，强制至少跨 2 个区（用次高分区的最优数字替换得分最低者）
    if n_digit >= 3:
        zs_in = {P.zone_of(d) for d in picked}
        if len(zs_in) < 2:
            for d, _, z in ranked[n_digit:]:
                if z not in zs_in:
                    picked[-1] = d
                    break
    return sorted(picked)


# =====================================================
# 主分析
# =====================================================
def analyze_v2(records_asc: list, per_pos=PER_POS, max_notes=MAX_NOTES) -> dict:
    vals = {p: [int(r[p]) for r in records_asc] for p, _ in POSITIONS}

    per_pos = list(per_pos)
    while P.math.prod(per_pos) > max_notes:
        cand = [j for j, v in enumerate(per_pos) if v > 1]
        if not cand:
            per_pos = [1, 1, 1]
            break
        per_pos[max(cand)] -= 1

    positions = {}
    for (p, label), nd in zip(POSITIONS, per_pos):
        prof = fused_profile(vals[p])
        zs, target, extreme, rebound = score_zones_v2(prof)
        rank = sorted(ZONES, key=lambda z: -zs[z]["score"])
        digits = pick_digits_v2(prof, zs, rank, nd)
        positions[p] = {"label": label, "profile": prof, "zone_scores": zs,
                        "rank": rank, "digits": digits, "rebound_target": target,
                        "extreme": extreme, "rebound": rebound,
                        "swing_score": P.swing_score(prof),
                        "direction": P.direction_text(prof)}

    # U4 和值分位带
    sums = sorted(int(r.get("sum_val", sum(int(r[p]) for p, _ in POSITIONS)))
                  for r in records_asc[-SUM_WINDOW:])
    band = (round(_quantile(sums, SUM_Q[0])), round(_quantile(sums, SUM_Q[1])))
    band_wide = (round(_quantile(sums, SUM_Q_WIDE[0])), round(_quantile(sums, SUM_Q_WIDE[1])))

    combos = [{"nums": [b, s, g],
               "zones": [P.zone_of(b), P.zone_of(s), P.zone_of(g)],
               "sum_val": b + s + g}
              for b, s, g in product(positions["bai"]["digits"],
                                     positions["shi"]["digits"],
                                     positions["ge"]["digits"])]

    def _keep1(c):
        return band[0] <= c["sum_val"] <= band[1]

    def _keep2(c):
        return len(set(c["zones"])) >= 2  # U5 禁止三位同区

    notes = [c for c in combos if _keep1(c) and _keep2(c)] or \
            [c for c in combos if (band_wide[0] <= c["sum_val"] <= band_wide[1]) and _keep2(c)] or \
            [c for c in combos if _keep2(c)] or combos
    notes = notes[:max_notes]

    # U5 多样性：若三区互异占比不足，补入该类注
    diverse = [c for c in combos if len(set(c["zones"])) == 3]
    if notes and len([c for c in notes if len(set(c["zones"])) == 3]) < DIVERSITY_MIN * len(notes):
        need = int(DIVERSITY_MIN * len(notes)) - len([c for c in notes if len(set(c["zones"])) == 3])
        extra = [c for c in diverse if c not in notes][:need]
        notes = (notes + extra)[:max_notes]

    latest = records_asc[-1]
    return {"mode": "v2", "windows": WINDOWS, "window_w": WINDOW_W,
            "latest_qihao": latest.get("qihao"), "latest_date": latest.get("date"),
            "latest_nums": [int(latest[p]) for p, _ in POSITIONS],
            "positions": positions, "notes": notes, "note_count": len(notes),
            "sum_band": band, "sum_band_wide": band_wide, "candidate_pool": len(combos)}


# =====================================================
# 分布统计（U6）
# =====================================================
def dist_stats(notes: list) -> dict:
    def _cnt(vals):
        return {"odd": sum(1 for v in vals if v % 2), "even": sum(1 for v in vals if v % 2 == 0)}
    all_d = [d for n in notes for d in n["nums"]]
    odd_even = _cnt(all_d)
    big_small = {"big(5-9)": sum(1 for d in all_d if d >= 5), "small(0-4)": sum(1 for d in all_d if d < 5)}
    zone_cnt = {}
    for z in ZONES:
        zone_cnt[ZONE_LABEL[z]] = sum(1 for n in notes for zz in n["zones"] if zz == z)
    sums = [n["sum_val"] for n in notes]
    return {"digits": len(all_d), "odd_even": odd_even, "big_small": big_small,
            "zone": zone_cnt, "sum_range": (min(sums), max(sums)),
            "sum_mean": round(sum(sums) / len(sums), 1)}


# =====================================================
# 渲染
# =====================================================
def render(res: dict, dist: dict, val1: dict | None = None, val2: dict | None = None) -> str:
    L = []
    L.append("# 福彩3D 钟摆走势分析 v2（v1 升级版）")
    L.append("")
    L.append(f"> 数据截至：{res['latest_qihao']}（{res['latest_date']}）开奖 "
             f"{' '.join(map(str, res['latest_nums']))} | 生成日：{datetime.date.today()}")
    L.append("")
    L.append(DISCLAIMER)
    L.append("")
    L.append("## 升级点（v1 → v2）")
    L.append("")
    L.append("| # | 升级项 | v1 | v2 |")
    L.append("|---|---|---|---|")
    L.append("| U1 | 窗口 | 单一 30 期 | 10/30/60 三窗口加权 0.25/0.50/0.25 |")
    L.append(f"| U2 | 热度度量 | 原始出现次数 | z 值标准化，\\|z\\|>{HOT_CAP} 过热降权{HOT_PENALTY}、过冷降权{COLD_PENALTY} |")
    L.append(f"| U3 | 极值回撤 | 回摆系数固定 {REBOUND_BASE} | 边界值/同侧连出≥{EXTREME_STREAK} 时提至 {REBOUND_EXTREME} |")
    L.append(f"| U4 | 和值带 | 峰值±2 窄带 | 近{SUM_WINDOW}期 P{SUM_Q[0]:.0%}–P{SUM_Q[1]:.0%} 动态带（不足时放宽 P{SUM_Q_WIDE[0]:.0%}–P{SUM_Q_WIDE[1]:.0%}） |")
    L.append(f"| U5 | 多样性 | 无约束（曾出现三注全中区） | 禁止三位同区，三区互异占比 ≥{DIVERSITY_MIN:.0%} |")
    L.append("| U6 | 输出 | 仅列号码 | 增列奇偶/大小/区间分布便于人工核对 |")
    L.append("")

    L.append("## 一、各位置摆动状态（多窗口融合）")
    L.append("")
    L.append("| 位置 | 融合重心 | 偏移 | 振幅 | 动量 | 连出(短窗) | 回摆系数 | 回摆目标 | 回摆强度 | 候选数字 |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    for p, _ in POSITIONS:
        pos = res["positions"][p]
        pr = pos["profile"]
        L.append(f"| {pos['label']} | {pr['center']:.2f} | {pr['offset']:+.2f} | {pr['amplitude']:.2f} | "
                 f"{pr['momentum']:+.2f} | {pr['extreme_streak']}期({pr['extreme_side'] or '—'}) | "
                 f"{pos['rebound']} | {pos['rebound_target']:.2f} | {pos['swing_score']}/100 | "
                 f"{pos['digits']} |")
    L.append("")
    L.append("区域排序：")
    for p, _ in POSITIONS:
        pos = res["positions"][p]
        L.append(f"- **{pos['label']}**：" + " > ".join(
            f"{ZONE_LABEL[z]}({pos['zone_scores'][z]['score']})" for z in pos["rank"]))
    L.append("")

    L.append(f"## 二、候选直选号码（{res['note_count']} 注 · 随机采样·等同机选·无预测力）")
    L.append("")
    L.append(f"- 候选池 {res['candidate_pool']} 注 → 和值带 {res['sum_band']} + 禁止三位同区 → "
             f"保留 {res['note_count']} 注，成本 {res['note_count']*2} 元")
    L.append("")
    L.append("| # | 百 | 十 | 个 | 区域 | 和值 | 奇偶 |")
    L.append("|---|---|---|---|---|---|---|")
    for i, n in enumerate(res["notes"], 1):
        b, s, g = n["nums"]
        oe = "".join("奇" if x % 2 else "偶" for x in n["nums"])
        L.append(f"| {i} | {b} | {s} | {g} | {'/'.join(n['zones'])} | {n['sum_val']} | {oe} |")
    L.append("")
    L.append("### 分布说明")
    L.append("")
    L.append(f"- **奇偶**：奇 {dist['odd_even']['odd']} / 偶 {dist['odd_even']['even']}"
             f"（共 {dist['digits']} 个数字）")
    L.append(f"- **大小**：大(5-9) {dist['big_small']['big(5-9)']} / 小(0-4) {dist['big_small']['small(0-4)']}")
    L.append("- **区间**：" + "、".join(f"{k} {v}" for k, v in dist["zone"].items()))
    L.append(f"- **和值**：{dist['sum_range'][0]}–{dist['sum_range'][1]}，均值 {dist['sum_mean']}")
    L.append("")

    if val1 and val2 and val1.get("ok") and val2.get("ok"):
        L.append("## 三、v1 vs v2 walk-forward 对比（含置换检验）")
        L.append("")
        L.append("| 口径 | v1 直选命中 | v2 直选命中 | v1 置换基准 | v2 置换基准 | v1 z | v2 z |")
        L.append("|---|---|---|---|---|---|---|")
        d1, d2 = val1["direct"], val2["direct"]
        L.append(f"| 直选 | {d1['hit']}/{val1['trials']} = {d1['rate']*100:.3f}% | "
                 f"{d2['hit']}/{val2['trials']} = {d2['rate']*100:.3f}% | "
                 f"{d1['ctrl_mean_rate']*100:.3f}% | {d2['ctrl_mean_rate']*100:.3f}% | "
                 f"{d1['z']} | {d2['z']} |")
        L.append("")
        L.append("| 位置 | v1 首选区命中 | v2 首选区命中 | 理论基准 | v1 z | v2 z |")
        L.append("|---|---|---|---|---|---|")
        for p, _ in POSITIONS:
            a, b = val1["by_pos"][p], val2["by_pos"][p]
            L.append(f"| {a['label']} | {a['top1_rate']*100:.2f}% | {b['top1_rate']*100:.2f}% | "
                     f"{a['baseline']*100:.2f}% | {a['z']} | {b['z']} |")
        L.append("")
        sp = val2.get("split", {})
        if sp:
            r1 = sp["前半段"]["direct_hit"] / sp["前半段"]["trials"]
            r2 = sp["后半段"]["direct_hit"] / sp["后半段"]["trials"]
            L.append(f"- v2 前后半段：{r1*100:.2f}% vs {r2*100:.2f}%"
                     f"（差异 {abs(r2-r1)/max(r1,1e-9)*100:.0f}%）")
        L.append("- 解读口径：|z| < 2 视为与随机无显著差异；即便某项 z > 2，也需排除多重比较"
                 "（多项指标取最大值）与分段不稳定后才可能采信。")
        L.append("")
    L.append("## 四、风险提示")
    L.append("")
    L.append("1. 每次开奖独立同分布，历史摆动不构成下期信息；钟摆是对已发生序列的事后描述。")
    L.append("2. 直选单注中奖概率恒 0.1%、ROI≈52%，区域/和值/多样性筛选只改结构，不改期望值。")
    L.append("3. 多窗口、z 值、和值带都是**描述性加工**，样本外的稳定性以上节校验为准。")
    L.append("4. 仅供学习研究，不构成投注建议。")
    return "\n".join(L)


# =====================================================
# 校验：复用 v1 框架，替换低成本/pick 逻辑为 v2
# =====================================================
def _hook_v2():
    """让 pendulum.walk_forward 用 v2 的 analyze/ USERanker 来跑（不改 v1 源码）。"""
    orig = P.analyze

    def analyze_v2_shim(records_asc, window=P.DEFAULT_WINDOW, per_pos=PER_POS, max_notes=MAX_NOTES):
        return analyze_v2(records_asc, per_pos=per_pos, max_notes=max_notes)

    P.analyze = analyze_v2_shim
    return orig


def validate_v2(records_asc, per_pos=PER_POS, max_notes=MAX_NOTES, rounds=30, seed=20260927):
    orig = _hook_v2()
    try:
        return P.validate(records_asc, window=30, per_pos=per_pos, max_notes=max_notes,
                          rounds=rounds, seed=seed)
    finally:
        P.analyze = orig


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="福彩3D 钟摆 v2")
    ap.add_argument("--per-pos", default="3,3,2")
    ap.add_argument("--max-notes", type=int, default=MAX_NOTES)
    ap.add_argument("--history", default=P.HISTORY_FILE)
    ap.add_argument("--validate-history", default=P.LONG_HISTORY_FILE)
    ap.add_argument("--no-validate", action="store_true")
    ap.add_argument("--sim-rounds", type=int, default=30)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    try:
        per_pos = tuple(int(x) for x in args.per_pos.split(","))
        assert len(per_pos) == 3 and all(x >= 1 for x in per_pos)
    except Exception:
        per_pos = PER_POS

    recs = P.load_records(args.history)
    res = analyze_v2(recs, per_pos=per_pos, max_notes=args.max_notes)
    dist = dist_stats(res["notes"])

    val1 = val2 = None
    if not args.no_validate:
        try:
            vrecs = P.load_records(args.validate_history)
            val1 = P.validate(vrecs, window=30, per_pos=per_pos,
                              max_notes=args.max_notes, rounds=args.sim_rounds)
            val2 = validate_v2(vrecs, per_pos=per_pos, max_notes=args.max_notes,
                               rounds=args.sim_rounds)
        except FileNotFoundError as e:
            print(f"[warn] 校验跳过：{e}")

    md = render(res, dist, val1, val2)
    print(md)
    out = args.out or os.path.join(REPORT_DIR, f"pendulum_v2_{datetime.date.today()}.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"\n📄 报告已写入：{out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
