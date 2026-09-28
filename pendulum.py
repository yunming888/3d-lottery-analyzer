# -*- coding: utf-8 -*-
"""
福彩3D「钟摆原理」直选走势分析
=====================================================
只读诊断工具：对百/十/个三个位置分别做分布统计，把 0-9 划成
左区(0-3) / 中区(4-6) / 右区(7-9)，依据"摆向一端后存在回摆倾向"的
钟摆假设，给出各位置的摆动方向、回摆强度评分、区域排序，
并由高分区域交叉组合生成候选直选号码（默认 ≤20 注）。

⚠️ 性质：候选号码为**随机采样**，等同投注站机选、无预测力。
   开奖随机且每期独立，直选单注中奖概率恒为 0.1%，本工具只做
   历史分布的描述性统计，不改变任何一注的中奖概率。

不接每日链路（unified_review.py 不调用本模块），不写出号/结算逻辑。

用法
----
    python pendulum.py                       # 默认 30 期窗口
    python pendulum.py --window 50 --per-pos 3,3,2
    python pendulum.py --no-validate         # 跳过 walk-forward 校验
    python pendulum.py --json                # 额外输出结构化 JSON

API
---
    from pendulum import analyze, render_markdown
    res = analyze(records_asc, window=30)    # records_asc: 时间升序
    print(render_markdown(res))
"""
from __future__ import annotations

import argparse
import datetime
import json
import math
import os
import random
import statistics
import sys
from collections import Counter
from itertools import product

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HISTORY_FILE = os.path.join(BASE_DIR, "data", "3d_history.json")
LONG_HISTORY_FILE = os.path.join(BASE_DIR, "data", "backtest_3d_long.json")
REPORT_DIR = os.path.join(BASE_DIR, "data", "reports")

# ---------------- 区域划分 ----------------
ZONES = ["左区", "中区", "右区"]
ZONE_RANGE = {"左区": (0, 3), "中区": (4, 6), "右区": (7, 9)}
ZONE_LABEL = {"左区": "左区(0-3)", "中区": "中区(4-6)", "右区": "右区(7-9)"}
ZONE_CENTER = {"左区": 1.5, "中区": 5.0, "右区": 8.0}   # 区域重心（轴上位置）
ZONE_SIZE = {"左区": 4, "中区": 3, "右区": 3}           # 区内数字个数
AXIS_CENTER = 4.5                                       # 0-9 轴心

# ---------------- 模型参数（可在此调参） ----------------
DEFAULT_WINDOW = 30      # 默认统计窗口
MOMENTUM_SHORT = 5       # 动量窗口（近 N 期 vs 前 N 期）
REBOUND = 0.80           # 回摆幅度系数：回摆目标点 = 重心 - REBOUND * 偏移
MOM_GAIN = 0.40          # 动量修正系数（动量越强，回摆目标越反向）
W_PULL = 0.45            # 权重：回摆目标匹配度
W_DEFICIT = 0.30         # 权重：区域欠账（实际频次低于期望）
W_MISS = 0.25            # 权重：区域遗漏
EXTREME_BOOST = 8.0      # 极值加成（振幅大 + 同侧连出 ≥2 时，给回摆目标区加分）
AMPLITUDE_EXTREME = 0.25 # 判定"已摆到极端"的振幅阈值
DEFAULT_PER_POS = (3, 3, 2)   # 百/十/个各取几个候选数字（乘积须 ≤ max_notes）
MAX_NOTES = 20           # 候选直选注数上限

POSITIONS = [("bai", "百位"), ("shi", "十位"), ("ge", "个位")]

DISCLAIMER = (
    "> ⚠️ **性质声明**：以下候选号码均为程序按历史分布**随机采样**生成，"
    "**等同投注站机选、不具备预测能力**。\n"
    "> 福彩3D 开奖完全随机、每期独立，直选单注中奖概率恒为 0.1%（ROI 约 52%）；"
    "钟摆原理仅是对历史摆动形态的**描述性统计**，不改变任何一注的中奖概率。\n"
    "> 任何声称能预测、推算或推荐中奖号码的个人、平台或 AI 均属诈骗。"
    "本工具仅供学习研究，不构成投注建议。"
)


# =====================================================
# 基础工具
# =====================================================
def load_records(path: str = HISTORY_FILE) -> list:
    """读取历史，返回**时间升序**列表（最后一条为最新）。"""
    with open(path, encoding="utf-8") as f:
        recs = json.load(f)
    # 文件为倒序（最新在前），翻转为升序
    return list(reversed(recs))


def zone_of(digit: int) -> str:
    for z in ZONES:
        lo, hi = ZONE_RANGE[z]
        if lo <= digit <= hi:
            return z
    return "中区"


def _clip(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


# =====================================================
# 单位置画像
# =====================================================
def position_profile(vals: list, window: int, short: int = MOMENTUM_SHORT) -> dict:
    """vals: 该位置按时间升序的数字序列（末尾为最新）。"""
    win = vals[-window:]
    n = len(win)
    freq = Counter(win)
    center = sum(win) / n
    offset = center - AXIS_CENTER
    amplitude = abs(offset) / AXIS_CENTER

    # 动量：近 short 期重心 - 前 short 期重心
    if len(vals) >= 2 * short:
        recent = vals[-short:]
        prev = vals[-2 * short:-short]
        momentum = sum(recent) / short - sum(prev) / short
    else:
        momentum = 0.0

    # 区域频次 / 期望 / 欠账 / 遗漏
    zone_cnt = Counter(zone_of(v) for v in win)
    zone_miss = {}
    for z in ZONES:
        m = n
        for idx in range(n - 1, -1, -1):
            if zone_of(win[idx]) == z:
                m = n - 1 - idx
                break
        zone_miss[z] = m
    zone_expect = {z: ZONE_SIZE[z] / 10.0 * n for z in ZONES}
    zone_deficit = {
        z: (zone_expect[z] - zone_cnt.get(z, 0)) / zone_expect[z] for z in ZONES
    }

    # 数字遗漏（距上次出现的期数）
    digit_miss = {}
    for d in range(10):
        m = n
        for idx in range(n - 1, -1, -1):
            if win[idx] == d:
                m = n - 1 - idx
                break
        digit_miss[d] = m

    # 同侧极端连出（中区打断）
    side, streak = None, 0
    for v in reversed(win):
        z = zone_of(v)
        if z == "中区":
            break
        if side is None:
            side, streak = z, 1
        elif z == side:
            streak += 1
        else:
            break

    # 极值 / 边界占比
    vmax, vmin = max(win), min(win)
    edge_ratio = sum(1 for v in win if v <= 1 or v >= 8) / n

    return {
        "window": n,
        "freq": {d: freq.get(d, 0) for d in range(10)},
        "center": center,
        "offset": offset,
        "amplitude": amplitude,
        "momentum": momentum,
        "zone_cnt": dict(zone_cnt),
        "zone_miss": zone_miss,
        "zone_expect": zone_expect,
        "zone_deficit": zone_deficit,
        "digit_miss": digit_miss,
        "extreme_side": side,
        "extreme_streak": streak,
        "vmax": vmax,
        "vmin": vmin,
        "edge_ratio": edge_ratio,
        "last": win[-1],
    }


def score_zones(prof: dict) -> dict:
    """给三个区域打分（0-100），返回 {zone: {score, pull, deficit, miss, boost}}。"""
    center, offset, momentum = prof["center"], prof["offset"], prof["momentum"]
    # 回摆目标点：重心 - 回摆幅度*偏移 - 动量修正
    target = center - REBOUND * offset - MOM_GAIN * momentum
    target = _clip(target, 0.0, 9.0)

    extreme = (prof["amplitude"] >= AMPLITUDE_EXTREME) and (prof["extreme_streak"] >= 2)

    out = {}
    for z in ZONES:
        pull = _clip(1 - abs(ZONE_CENTER[z] - target) / AXIS_CENTER)
        deficit = _clip(prof["zone_deficit"][z], 0.0, 1.0)
        exp_miss = 10.0 / ZONE_SIZE[z]
        miss = _clip(prof["zone_miss"][z] / (2 * exp_miss))
        boost = 0.0
        if extreme and abs(ZONE_CENTER[z] - target) <= 2.5:
            boost = EXTREME_BOOST
        score = 100 * (W_PULL * pull + W_DEFICIT * deficit + W_MISS * miss) + boost
        out[z] = {
            "score": round(score, 1),
            "pull": round(pull, 3),
            "deficit": round(deficit, 3),
            "miss": round(miss, 3),
            "boost": round(boost, 1),
        }
    return out, target, extreme


def swing_score(prof: dict) -> float:
    """该位置整体回摆强度评分（0-100）：越极端、连出越久、欠账越大 → 回摆压力越大。"""
    amp_part = _clip(prof["amplitude"] / 0.5)
    streak_part = _clip(prof["extreme_streak"] / 3.0)
    deficit_part = _clip(max(prof["zone_deficit"].values()))
    return round(100 * (0.5 * amp_part + 0.3 * streak_part + 0.2 * deficit_part), 1)


def direction_text(prof: dict) -> str:
    off, mom = prof["offset"], prof["momentum"]
    side = "偏右(高位)" if off > 0.15 else ("偏左(低位)" if off < -0.15 else "居中震荡")
    if abs(mom) < 0.4:
        mv = "动量走平"
    else:
        mv = "动量向右(继续上行)" if mom > 0 else "动量向左(继续下探)"
    return f"{side}｜{mv}"


def pick_digits(prof: dict, zone_scores: dict, zone_rank: list, n_digit: int) -> list:
    """按「区域得分 × 区内热度/遗漏」加权取候选数字，允许跨区（高分区域优先但不止一区）。"""
    max_f = max(prof["freq"].values()) or 1
    scored = []
    for d in range(10):
        z = zone_of(d)
        zone_n = zone_scores[z]["score"] / 100.0
        freq_n = prof["freq"][d] / max_f
        miss_n = _clip(prof["digit_miss"][d] / 20.0)   # 单数字理论间隔 10 期，20 期封顶
        scored.append((d, 0.5 * zone_n + 0.3 * freq_n + 0.2 * miss_n, z))
    rank_idx = {z: i for i, z in enumerate(zone_rank)}
    scored.sort(key=lambda x: (-x[1], rank_idx[x[2]], x[0]))
    return sorted(d for d, _, _ in scored[:n_digit])


# =====================================================
# 主分析
# =====================================================
def analyze(records_asc: list, window: int = DEFAULT_WINDOW,
            per_pos=DEFAULT_PER_POS, max_notes: int = MAX_NOTES) -> dict:
    vals = {p: [int(r[p]) for r in records_asc] for p, _ in POSITIONS}

    # 候选数字数：保证乘积 ≤ max_notes，否则从后往前逐个缩减
    per_pos = list(per_pos)
    while math.prod(per_pos) > max_notes:
        cand = [j for j, v in enumerate(per_pos) if v > 1]
        if not cand:
            per_pos = [1, 1, 1]
            break
        per_pos[max(cand)] -= 1

    positions = {}
    for (p, label), nd in zip(POSITIONS, per_pos):
        prof = position_profile(vals[p], window)
        zscores, target, extreme = score_zones(prof)
        rank = sorted(ZONES, key=lambda z: -zscores[z]["score"])
        digits = pick_digits(prof, zscores, rank, nd)
        positions[p] = {
            "label": label,
            "profile": prof,
            "zone_scores": zscores,
            "rebound_target": round(target, 2),
            "extreme": extreme,
            "swing_score": swing_score(prof),
            "direction": direction_text(prof),
            "rank": rank,
            "digits": digits,
        }

    notes = []
    for combo in product(positions["bai"]["digits"],
                         positions["shi"]["digits"],
                         positions["ge"]["digits"]):
        b, s, g = combo
        notes.append({
            "nums": [b, s, g],
            "zones": [zone_of(b), zone_of(s), zone_of(g)],
            "sum_val": b + s + g,
        })
    notes = notes[:max_notes]

    latest = records_asc[-1]
    return {
        "window": window,
        "latest_qihao": latest.get("qihao"),
        "latest_date": latest.get("date"),
        "latest_nums": [int(latest[p]) for p, _ in POSITIONS],
        "positions": positions,
        "notes": notes,
        "note_count": len(notes),
        "max_notes": max_notes,
    }


# =====================================================
# walk-forward 校验（钟摆假设是否真有统计优势）
# =====================================================
def walk_forward(records_asc: list, window: int = DEFAULT_WINDOW,
                 per_pos=DEFAULT_PER_POS, max_notes: int = MAX_NOTES) -> dict:
    """滚动前推：用截至每期之前的数据跑钟摆规则，预测下一期，统计命中。"""
    n = len(records_asc)
    if n < window + 60:
        return {"ok": False, "reason": f"样本不足（{n} 期，需 ≥ {window + 60}）"}

    trials = 0
    per_pos_eff = list(per_pos)
    hit1 = Counter()        # 首选区命中
    hit2 = Counter()        # Top2 区命中
    hitd = Counter()        # 候选数字集命中（该位数字落在候选集内）
    direct_hit = 0
    zone_actual = Counter()
    notes_used = []
    flags = []

    for i in range(window, n):
        train = records_asc[:i]
        actual = records_asc[i]
        res = analyze(train, window=window, per_pos=per_pos, max_notes=max_notes)
        notes_used.append(res["note_count"])
        per_pos_eff = [len(res["positions"][p]["digits"]) for p, _ in POSITIONS]
        for p, _ in POSITIONS:
            pos = res["positions"][p]
            av = int(actual[p])
            az = zone_of(av)
            zone_actual[(p, az)] += 1
            if pos["rank"][0] == az:
                hit1[p] += 1
            if az in pos["rank"][:2]:
                hit2[p] += 1
            if av in pos["digits"]:
                hitd[p] += 1
        a = [int(actual[p]) for p, _ in POSITIONS]
        dh = any(note["nums"] == a for note in res["notes"])
        if dh:
            direct_hit += 1
        flags.append({"direct": dh, "pos": {p: pos["rank"][0] == zone_of(int(actual[p]))
                                            for p, _ in POSITIONS}})
        trials += 1

    avg_notes = sum(notes_used) / len(notes_used)
    out = {"ok": True, "trials": trials, "avg_notes": round(avg_notes, 2),
           "per_pos_eff": per_pos_eff, "by_pos": {}}
    for p, label in POSITIONS:
        share = {z: zone_actual[(p, z)] / trials for z in ZONES}
        out["by_pos"][p] = {
            "label": label,
            "top1_hit": hit1[p],
            "top1_rate": round(hit1[p] / trials, 4),
            "baseline": round(sum(share[z] * share[z] for z in ZONES), 4),
            "top2_hit": hit2[p],
            "top2_rate": round(hit2[p] / trials, 4),
            "top2_baseline": round(1 - min(share.values()), 4),
            "digit_hit_rate": round(hitd[p] / trials, 4),
            "digit_random": round(per_pos_eff[POSITIONS.index((p, label))] / 10.0, 4),
            "zone_share": {z: round(share[z], 4) for z in ZONES},
        }
    mid = trials // 2
    out["split"] = {}
    for name, seg in (("前半段", flags[:mid]), ("后半段", flags[mid:])):
        out["split"][name] = {
            "trials": len(seg),
            "direct_hit": sum(1 for f in seg if f["direct"]),
            "top1_hit": {p: sum(1 for f in seg if f["pos"][p]) for p, _ in POSITIONS},
        }
    out["direct_hit"] = direct_hit
    out["direct_rate"] = round(direct_hit / trials, 5)
    out["direct_expected"] = round(avg_notes / 1000.0, 5)
    return out


def permutation_test(records_asc: list, window: int, per_pos, max_notes: int,
                     rounds: int = 30, seed: int = 20260927) -> dict:
    """置换检验：打乱期序（保留每期内部三位结构、破坏期与期之间的时序依赖），
    用**同一套钟摆规则**重跑 walk_forward，得到零假设下的命中数经验分布。

    该基准同时包含了两类偏差：① 滚动窗口重叠造成的自相关；
    ② 同一段历史内的频率波动被规则反复利用（in-sample 频率偏差）。
    """
    rng = random.Random(seed)
    base = list(records_asc)
    pos_samples = {p: [] for p, _ in POSITIONS}
    direct_samples = []
    for _ in range(rounds):
        shuffled = base[:]
        rng.shuffle(shuffled)
        w = walk_forward(shuffled, window=window, per_pos=per_pos, max_notes=max_notes)
        if not w.get("ok"):
            continue
        for p, _ in POSITIONS:
            pos_samples[p].append(w["by_pos"][p]["top1_hit"])
        direct_samples.append(w["direct_hit"])
    rounds_ok = len(direct_samples)
    return {
        "rounds": rounds_ok,
        "pos_samples": pos_samples,
        "pos_mean": {p: (sum(pos_samples[p]) / rounds_ok if rounds_ok else 0) for p, _ in POSITIONS},
        "pos_sd": {p: (statistics.pstdev(pos_samples[p]) if rounds_ok > 1 else 0.0) for p, _ in POSITIONS},
        "direct_samples": direct_samples,
        "direct_mean": (sum(direct_samples) / rounds_ok if rounds_ok else 0),
        "direct_sd": (statistics.pstdev(direct_samples) if rounds_ok > 1 else 0.0),
    }


def validate(records_asc: list, window: int = DEFAULT_WINDOW,
             per_pos=DEFAULT_PER_POS, max_notes: int = MAX_NOTES,
             rounds: int = 30, seed: int = 20260927) -> dict:
    """walk-forward + 置换检验，输出对照口径的 z 值与经验分位。"""
    out = walk_forward(records_asc, window, per_pos, max_notes)
    if not out.get("ok"):
        return out
    trials = out["trials"]
    for p, _ in POSITIONS:
        out["by_pos"][p]["naive_z"] = round(
            (out["by_pos"][p]["top1_hit"] - trials * out["by_pos"][p]["baseline"])
            / (math.sqrt(trials * out["by_pos"][p]["baseline"] * (1 - out["by_pos"][p]["baseline"])) or 1), 2)
    sd0 = math.sqrt(trials * out["direct_expected"] * (1 - out["direct_expected"])) or 1
    out["direct_naive_z"] = round((out["direct_hit"] - trials * out["direct_expected"]) / sd0, 2)

    out["perm"] = permutation_test(records_asc, window, per_pos, max_notes, rounds=rounds, seed=seed)
    pm = out["perm"]
    if pm["rounds"]:
        for p, _ in POSITIONS:
            d = out["by_pos"][p]
            m, sdv = pm["pos_mean"][p], pm["pos_sd"][p] or 1
            d["ctrl_mean_rate"] = round(m / trials, 4)
            d["z"] = round((d["top1_hit"] - m) / sdv, 2)
            d["pct_ge"] = round(sum(1 for x in pm["pos_samples"][p] if x >= d["top1_hit"]) / pm["rounds"], 3)
        dsd = pm["direct_sd"] or 1
        out["direct"] = {
            "hit": out["direct_hit"],
            "rate": out["direct_rate"],
            "expected": out["direct_expected"],
            "ctrl_mean_rate": round(pm["direct_mean"] / trials, 5),
            "z": round((out["direct_hit"] - pm["direct_mean"]) / dsd, 2),
            "pct_ge": round(sum(1 for x in pm["direct_samples"] if x >= out["direct_hit"]) / pm["rounds"], 3),
        }
    return out


def out_div(val: dict) -> float:
    """理论直选命中率（注数/1000）。"""
    prod = 1.0
    for k in val["per_pos_eff"]:
        prod *= k / 10.0
    return prod


# =====================================================
# 渲染
# =====================================================
def render_markdown(res: dict, val: dict | None = None) -> str:
    L = []
    L.append(f"# 福彩3D「钟摆原理」直选走势分析（窗口 {res['window']} 期）")
    L.append("")
    L.append(f"> 数据截至：{res['latest_qihao']}（{res['latest_date']}）开奖 "
             f"{' '.join(str(x) for x in res['latest_nums'])}")
    L.append("")
    L.append(DISCLAIMER)
    L.append("")

    # 1. 各位置画像
    L.append("## 一、各位置摆动方向与回摆强度")
    L.append("")
    L.append("| 位置 | 重心 | 偏移 | 振幅 | 动量 | 摆动方向 | 同侧连出 | 极值(最小-最大) | 边界占比 | 回摆强度 |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    for p, label in POSITIONS:
        pos = res["positions"][p]
        pr = pos["profile"]
        L.append(
            f"| {label} | {pr['center']:.2f} | {pr['offset']:+.2f} | {pr['amplitude']:.2f} | "
            f"{pr['momentum']:+.2f} | {pos['direction']} | "
            f"{pr['extreme_streak']}期({pr['extreme_side'] or '—'}) | "
            f"{pr['vmin']}-{pr['vmax']} | {pr['edge_ratio']*100:.0f}% | "
            f"**{pos['swing_score']}/100** |"
        )
    L.append("")

    # 2. 区域排序
    L.append("## 二、各位置区域排序（Top3 = 三区全排序）")
    L.append("")
    L.append("| 位置 | 排名 | 区域 | 得分 | 回摆匹配 | 欠账 | 遗漏 | 极值加成 | 该区实际/期望 |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for p, label in POSITIONS:
        pos = res["positions"][p]
        pr = pos["profile"]
        for i, z in enumerate(pos["rank"], 1):
            zs = pos["zone_scores"][z]
            L.append(
                f"| {label} | {i} | {ZONE_LABEL[z]} | **{zs['score']}** | {zs['pull']} | "
                f"{zs['deficit']} | {zs['miss']} | {zs['boost']} | "
                f"{pr['zone_cnt'].get(z,0)}/{pr['zone_expect'][z]:.0f} "
                f"(遗漏{pr['zone_miss'][z]}期) |"
            )
    L.append("")
    L.append("> 回摆目标点（0-9 轴）：" + "；".join(
        f"{res['positions'][p]['label']} {res['positions'][p]['rebound_target']:.2f}"
        for p, _ in POSITIONS))
    L.append("")

    # 3. 候选号码
    L.append(f"## 三、候选直选号码（{res['note_count']} 注，随机采样·等同机选·无预测力）")
    L.append("")
    L.append("候选数字来源：" + "；".join(
        f"{res['positions'][p]['label']} {res['positions'][p]['digits']}"
        for p, _ in POSITIONS))
    L.append("")
    L.append("| # | 百 | 十 | 个 | 区域组合 | 和值 |")
    L.append("|---|---|---|---|---|---|")
    for i, note in enumerate(res["notes"], 1):
        b, s, g = note["nums"]
        L.append(f"| {i} | {b} | {s} | {g} | "
                 f"{'/'.join(note['zones'])} | {note['sum_val']} |")
    L.append("")
    L.append(f"> 成本口径：{res['note_count']} 注 × 2 元 = {res['note_count']*2} 元；"
             f"直选单注中奖 1040 元，中奖概率恒 0.1%，与机选完全一致。")
    L.append("")

    # 4. 判断依据
    L.append("## 四、关键判断依据")
    L.append("")
    for p, label in POSITIONS:
        pos = res["positions"][p]
        pr = pos["profile"]
        top = pos["rank"][0]
        zs = pos["zone_scores"][top]
        miss_txt = "、".join(
            f"{ZONE_LABEL[z]}遗漏{pr['zone_miss'][z]}期" for z in ZONES)
        swing_state = ""
        if pr["extreme_side"] and pr["extreme_streak"] >= 2:
            same_dir = (pr["extreme_side"] == "右区" and pr["offset"] > 0) or \
                       (pr["extreme_side"] == "左区" and pr["offset"] < 0)
            swing_state = "；与重心同向 → 仍在向极端摆动，回摆尚未发生" if same_dir \
                else "；与重心反向 → 回摆已在途中（近端已反向）"
        L.append(
            f"- **{label}**：重心 {pr['center']:.2f}（偏移 {pr['offset']:+.2f}，"
            f"振幅 {pr['amplitude']:.2f}），{pos['direction']}；"
            f"同侧极端连出 {pr['extreme_streak']} 期（{pr['extreme_side'] or '无'}）{swing_state}；"
            f"{miss_txt}；区域欠账最高 {max(pr['zone_deficit'], key=pr['zone_deficit'].get)}"
            f"（{max(pr['zone_deficit'].values()):.2f}）。"
            f"回摆目标点 {pos['rebound_target']:.2f} → 首选 **{ZONE_LABEL[top]}**"
            f"（得分 {zs['score']}），回摆强度 {pos['swing_score']}/100"
            f"{'；已判定为「摆到极端」，触发回摆加成' if pos['extreme'] else ''}。"
        )
    L.append("")
    L.append("评分公式：`得分 = 100 × (0.45×回摆匹配 + 0.30×区域欠账 + 0.25×区域遗漏) + 极值加成`，"
             f"回摆目标点 = 重心 − {REBOUND}×偏移 − {MOM_GAIN}×动量。")
    L.append("")

    # 5. 风险提示
    L.append("## 五、风险提示（走势分析不具备确定性）")
    L.append("")
    L.append("1. **独立性**：每期开奖独立同分布，历史摆动形态不携带下期信息；"
             "「钟摆回摆」是对已发生序列的**事后描述**，不是可提前利用的因果规律。")
    L.append("2. **等价性**：直选单注中奖概率恒为 1/1000，奖金 1040 元、成本 2 元，"
             "ROI 约 52%；任何区域筛选都只改变号码结构，不改变期望值。")
    L.append("3. **样本幻觉**：30 期窗口下每个数字仅约 3 次观测，"
             "频次/遗漏的波动大多在随机噪声范围内（σ 不小），容易把噪声读成信号。")
    L.append("4. **区域占比固定**：左区理论 40%、中区 30%、右区 30%；"
             "「欠账必补」是赌徒谬误的常见变体，不存在物理意义上的回补压力。")
    if val and val.get("ok"):
        L.append("5. **历史校验**：见下节 walk-forward 结果——若 z 值落在 ±2 内，"
                 "说明该规则与随机猜测无统计差异。")
    L.append("")

    # 6. 校验
    if val:
        L.append("## 六、钟摆假设 walk-forward 校验（含置换检验）")
        L.append("")
        if not val.get("ok"):
            L.append(f"- 未执行：{val.get('reason')}")
        else:
            L.append(f"- 样本：{val['trials']} 次滚动前推预测，平均每期候选 {val['avg_notes']} 注"
                     f"（每位置候选数字数 {val['per_pos_eff']}）")
            L.append("")
            L.append("| 位置 | 首选区命中率 | 理论基准 | 置换基准 | 置换 z | P(置换≥观测) | 数字集命中 | 随机选号期望 |")
            L.append("|---|---|---|---|---|---|---|---|")
            for p, _ in POSITIONS:
                d = val["by_pos"][p]
                L.append(f"| {d['label']} | {d['top1_rate']*100:.2f}% | "
                         f"{d['baseline']*100:.2f}% | {d['ctrl_mean_rate']*100:.2f}% | "
                         f"{d['z']} | {d['pct_ge']} | {d['digit_hit_rate']*100:.2f}% | "
                         f"{d['digit_random']*100:.0f}% |")
            dv = val["direct"]
            L.append("")
            L.append(f"- 直选号码命中：{dv['hit']}/{val['trials']} = {dv['rate']*100:.3f}%"
                     f"（理论期望 {dv['expected']*100:.3f}%，置换基准 {dv['ctrl_mean_rate']*100:.3f}%，"
                     f"置换 z = {dv['z']}，P(置换≥观测) = {dv['pct_ge']}）")
            sp = val.get("split", {})
            if sp:
                txt = []
                for name in ("前半段", "后半段"):
                    d = sp[name]
                    txt.append(f"{name} 直选 {d['direct_hit']}/{d['trials']}="
                               f"{d['direct_hit']/d['trials']*100:.2f}%")
                L.append("- **稳健性（前后半段）**：" + "；".join(txt)
                         + f"（理论 {out_div(val)*100:.2f}%）—— 两段差异大说明结果不稳定、不可外推。")
            L.append(f"- 对照方法：把历史**期序打乱**后重跑**同一套钟摆规则** {val['perm']['rounds']} 轮，"
                     f"用其命中数经验分布作零假设基准 —— 该基准已包含滚动窗口自相关与"
                     f"「同一段历史内的频率波动被规则反复利用」两类偏差，比朴素二项 z 更严。")
            zs_pos = [val["by_pos"][p]["z"] for p, _ in POSITIONS]
            if min(zs_pos) < -2:
                v_zone = (f"区域层面：最低 z = {min(zs_pos)}（< -2），钟摆首选区命中率**显著低于**"
                          f"随机基准，「押欠账区/冷区」这一偏好在本样本上呈**负向**，应视为无效规则。")
            elif max(zs_pos) > 2:
                v_zone = (f"区域层面：最高 z = {max(zs_pos)}（> 2），疑似正向边际，"
                          f"但置换轮数与样本量均有限，需更长历史复验。")
            else:
                v_zone = (f"区域层面：三个位置的 z 为 {zs_pos}，均落在 ±2 内，"
                          f"钟摆选区与随机**无统计差异**。")
            sp = val.get("split", {})
            r1 = sp["前半段"]["direct_hit"] / sp["前半段"]["trials"] if sp else 0
            r2 = sp["后半段"]["direct_hit"] / sp["后半段"]["trials"] if sp else 0
            gap = abs(r2 - r1) / r1 if r1 else 0
            if dv["z"] > 2:
                if gap > 0.4:
                    v_dir = (f"直选层面：z = {dv['z']} 看似显著，但它是 4 项指标中的最大值（多重比较），"
                             f"且前后半段 {r1*100:.2f}% vs {r2*100:.2f}% 相差 {gap*100:.0f}%，"
                             f"稳定性不足 → **倾向判为样本噪声，不作为外推依据**。")
                else:
                    v_dir = (f"直选层面：z = {dv['z']}，前后半段 {r1*100:.2f}% vs {r2*100:.2f}% 较一致，"
                             f"但样本仅 {val['trials']} 期、单一数据源，需更长历史复验后才可采信。")
            elif dv["z"] < -2:
                v_dir = f"直选层面：z = {dv['z']}（< -2），命中率**显著低于**随机，规则无效。"
            else:
                v_dir = f"直选层面：z = {dv['z']}（±2 内），与随机无显著差异。"
            L.append(f"- **结论（区域）**：{v_zone}")
            L.append(f"- **结论（直选）**：{v_dir}")
            L.append("- 判定口径：|z| < 2 → 与随机无显著差异；|z| ≥ 2 才值得怀疑存在边际优势"
                     "（仍需更大样本复验）。")
        L.append("")
    return "\n".join(L)
# =====================================================
# CLI
# =====================================================
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="福彩3D 钟摆原理直选走势分析")
    ap.add_argument("--window", type=int, default=DEFAULT_WINDOW, help="统计窗口期数（默认30）")
    ap.add_argument("--per-pos", default="3,3,2", help="百/十/个候选数字个数，默认 3,3,2")
    ap.add_argument("--max-notes", type=int, default=MAX_NOTES, help="候选注数上限（默认20）")
    ap.add_argument("--history", default=HISTORY_FILE, help="历史数据文件")
    ap.add_argument("--validate-history", default=LONG_HISTORY_FILE, help="校验用长历史文件")
    ap.add_argument("--no-validate", action="store_true", help="跳过 walk-forward 校验")
    ap.add_argument("--sim-rounds", type=int, default=30, help="置换检验轮数（默认30，越大越稳但越慢）")
    ap.add_argument("--seed", type=int, default=20260927, help="置换检验随机种子")
    ap.add_argument("--json", action="store_true", help="额外输出结构化 JSON")
    ap.add_argument("--out", default=None, help="报告输出路径（默认 data/reports/pendulum_日期.md）")
    args = ap.parse_args(argv)

    try:
        per_pos = tuple(int(x) for x in args.per_pos.split(","))
        assert len(per_pos) == 3 and all(x >= 1 for x in per_pos)
    except Exception:
        per_pos = DEFAULT_PER_POS

    recs = load_records(args.history)
    res = analyze(recs, window=args.window, per_pos=per_pos, max_notes=args.max_notes)

    val = None
    if not args.no_validate:
        try:
            vrecs = load_records(args.validate_history)
            val = validate(vrecs, window=args.window, per_pos=per_pos,
                           max_notes=args.max_notes, rounds=args.sim_rounds, seed=args.seed)
        except FileNotFoundError:
            val = {"ok": False, "reason": f"长历史文件不存在：{args.validate_history}"}

    md = render_markdown(res, val)
    print(md)

    os.makedirs(REPORT_DIR, exist_ok=True)
    today = datetime.date.today().isoformat()
    out = args.out or os.path.join(REPORT_DIR, f"pendulum_{today}.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"\n📄 报告已写入：{out}")

    if args.json:
        print("\n--- JSON ---")
        print(json.dumps(res, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
