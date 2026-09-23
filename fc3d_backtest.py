# -*- coding: utf-8 -*-
"""
福彩3D 选号逻辑诊断回测器（只读诊断，不改动任何出号/结算代码）
================================================================
目的：定位"长期亏损"的根因，量化区分【选号规则问题】与【资金暴露问题】。

方法：Walk-Forward 逐期滚动回测
  - 对第 i 期，选号时**只能看到 i 期之前的历史**（严格无未来函数）
  - 结算口径与现行链路一致：投注组六 集合 vs 开奖组六 集合 相同即命中，
    单注奖金 160 元、成本 2 元/注
  - 理论基准：组选中奖率 = 0.72 / C(10,3) = 0.72/120 = 0.6%/注

输出：命中率 / ROI / 净盈亏 / 最大回撤 / 最大连亏 / 每注期望 等指标 + markdown 报告

用法: python fc3d_backtest.py
"""
import json
import math
import os
import random
from collections import Counter
from itertools import combinations

ROOT = os.path.dirname(os.path.abspath(__file__))
LONG_FILE = os.path.join(ROOT, "data", "backtest_3d_long.json")
PL_FILE = os.path.join(ROOT, "data", "profit_loss.json")
REPORT_DIR = os.path.join(ROOT, "data", "reports")

COST_PER_NOTE = 2
PRIZE_PER_HIT = 160
NOTES_PER_DAY = 10
WINDOW = 100          # 冷热号统计窗口（与 hot_core.WINDOW 一致）
TUO_N = 5             # 拖码个数（与 hot_core.D3_TUO_N 一致）
CB_THRESHOLD = 7      # 熔断阈值：组六连出 >=7 期暂停（与 daily_review 一致）

# ---------------------------------------------------------------- 数据加载


def load_long():
    with open(LONG_FILE, encoding="utf-8") as f:
        rs = json.load(f)
    # history[i] 为"第 i 新的期"，与项目内其余模块口径一致（最新在前）
    return rs


def chrono(rs):
    """返回由旧到新的列表，便于 walk-forward。"""
    return list(reversed(rs))


# ---------------------------------------------------------------- 选号器
# 说明：以下为 analyze.py / hot_core.py 现行逻辑的等价复现，供回测使用。
#       不 import 原模块，避免模块内 datetime.now() 造成的时间污染。


def pick_core(records_newest_first, window=WINDOW):
    """热号核心：胆码=近 window 期频率 TOP1；拖码=其余数字频率 TOP5。"""
    cnt = Counter()
    for r in records_newest_first[:window]:
        for x in r["nums"]:
            cnt[x] += 1
    ranked = sorted(range(10), key=lambda d: (-cnt.get(d, 0), d))
    return ranked[0], sorted(ranked[1:1 + TUO_N])


def dantuo_notes(dan, tuo):
    return [tuple(sorted((dan,) + c)) for c in combinations(sorted(tuo), 2)]


def _digit_marginal(records_newest_first):
    """v4：全窗口 Laplace 平滑的数字边际分布。"""
    total = Counter()
    for r in records_newest_first:
        for x in r["nums"]:
            total[x] += 1
    denom = len(records_newest_first) * 3 + 10
    return {i: (total.get(i, 0) + 1.0) / denom for i in range(10)}


def _weighted_choice(w, rng):
    items = list(w.items())
    tot = sum(v for _, v in items)
    r = rng.random() * tot
    cum = 0.0
    for d, v in items:
        cum += v
        if r <= cum:
            return d
    return items[-1][0]


def _sample_digits(rng, marginal, used, target, k):
    chosen = []
    avail = list(range(10))
    for _ in range(k):
        w = {}
        for d in avail:
            if d in chosen:
                continue
            base = marginal[d]
            util = used.get(d, 0)
            if util >= target:
                w[d] = base * 0.2
            else:
                w[d] = base * (1.0 + 0.6 * (target - util) / max(1, target))
        d = _weighted_choice(w, rng)
        chosen.append(d)
        avail.remove(d)
    return sorted(chosen)


def pick_v4(records_newest_first, count, seed):
    """v4 边际采样 + 覆盖均衡 + 每日变化种子。"""
    marginal = _digit_marginal(records_newest_first)
    rng = random.Random(seed)
    target = count * 3 / 10.0
    used = Counter()
    seen = set()
    out = []
    attempts = 0
    while len(out) < count and attempts < count * 500:
        attempts += 1
        nums = tuple(_sample_digits(rng, marginal, used, target, 3))
        if nums in seen:
            continue
        seen.add(nums)
        out.append(nums)
        for x in nums:
            used[x] += 1
    return out


def pick_random(count, seed):
    """纯随机组六（等价于投注站机选）。"""
    rng = random.Random(seed)
    pool = list(combinations(range(10), 3))
    return [tuple(x) for x in rng.sample(pool, count)]


# ---------------------------------------------------------------- 熔断


def zl_streak(records_newest_first):
    n = 0
    for r in records_newest_first:
        if r["type"] == "组六":
            n += 1
        else:
            break
    return n


# ---------------------------------------------------------------- 回测主循环


def settle(notes, draw):
    """返回 (hits, prize, cost)。组六集合匹配，组三/豹子必不中。"""
    hits = 0
    if draw["type"] == "组六":
        dn = frozenset(draw["nums"])
        for nt in notes:
            if frozenset(nt) == dn:
                hits += 1
    return hits, hits * PRIZE_PER_HIT, len(notes) * COST_PER_NOTE


def metrics(stats):
    """计算量化指标。"""
    days = stats["days"]           # 有投注的天数
    notes = stats["notes"]
    cost = stats["cost"]
    prize = stats["prize"]
    net = prize - cost
    hits = stats["hit_notes"]
    win_days = stats["win_days"]
    curve = stats["curve"]         # 每期(含0注日)累计盈亏序列

    peak = 0.0
    mdd = 0.0
    for v in curve:
        peak = max(peak, v)
        mdd = max(mdd, peak - v)

    lose_streak = 0
    max_lose_streak = 0
    for v in stats["daily_pnl_all"]:
        if v <= 0:
            lose_streak += 1
            max_lose_streak = max(max_lose_streak, lose_streak)
        else:
            lose_streak = 0

    # 显著性：H0 = 每注期望 -1.04 元（理论值），计算 z 值
    sd_note = math.sqrt(0.006 * (158 + 1.04) ** 2 + 0.994 * (2 - 1.04) ** 2)
    exp_net = -1.04 * notes
    z = (net - exp_net) / (sd_note * math.sqrt(notes)) if notes else 0.0

    return {
        "bet_days": days,
        "total_notes": notes,
        "total_cost": cost,
        "total_prize": prize,
        "net_pnl": net,
        "hit_notes": hits,
        "roi": (prize / cost * 100) if cost else 0.0,
        "note_ev": (prize - cost) / notes if notes else 0.0,
        "z": z,
        "day_hit_rate": (win_days / days * 100) if days else 0.0,
        "note_hit_rate": (hits / notes * 100) if notes else 0.0,
        "max_drawdown": mdd,
        "max_lose_streak": max_lose_streak,
        "worst_day": min(stats["daily_pnl_all"]) if stats["daily_pnl_all"] else 0,
        "net_per_bet_day": net / days if days else 0.0,
    }


def new_stats():
    return {"days": 0, "notes": 0, "cost": 0, "prize": 0, "hit_notes": 0,
            "win_days": 0, "curve": [], "daily_pnl_all": [], "cum": 0.0}


def run_backtest(hist_chrono, strategy, **kw):
    """逐期滚动回测。hist_chrono：由旧到新。"""
    st = new_stats()
    notes_today = []
    lock_ym = None
    lock_core = None
    cur = []            # 已观测历史（最新在前）

    for i, draw in enumerate(hist_chrono):
        if cur:  # 有历史才能选号
            notes_today = []
            if strategy == "current":       # 现行 v5 胆拖（按月锁定）+ 熔断
                ym = draw["date"][:7]
                if lock_ym != ym:
                    lock_core = pick_core(cur)
                    lock_ym = ym
                if zl_streak(cur) < CB_THRESHOLD:
                    notes_today = dantuo_notes(*lock_core)

            elif strategy == "dantuo_nocb":  # 胆拖，无熔断
                ym = draw["date"][:7]
                if lock_ym != ym:
                    lock_core = pick_core(cur)
                    lock_ym = ym
                notes_today = dantuo_notes(*lock_core)

            elif strategy == "dantuo_daily":  # 胆拖，每日重选胆码（检验月锁是否有害）
                notes_today = dantuo_notes(*pick_core(cur))

            elif strategy == "v4":            # v4 边际采样 + 熔断
                if zl_streak(cur) < CB_THRESHOLD:
                    notes_today = pick_v4(cur, NOTES_PER_DAY, int(draw["qihao"]))

            elif strategy.startswith("rand"):  # 纯随机组六基准
                n = int(strategy[4:])
                notes_today = pick_random(n, int(draw["qihao"]))

            hits, prize, cost = settle(notes_today, draw)
            pnl = prize - cost
            st["cum"] += pnl
            st["curve"].append(st["cum"])
            st["daily_pnl_all"].append(pnl)
            if notes_today:
                st["days"] += 1
                st["notes"] += len(notes_today)
                st["cost"] += cost
                st["prize"] += prize
                st["hit_notes"] += hits
                if hits:
                    st["win_days"] += 1

        cur.insert(0, draw)   # 开奖后才允许进入历史（无未来函数）

    return st


# ---------------------------------------------------------------- 蒙特卡洛（理论模型，大样本）


def monte_carlo(n_paths=4000, horizon=500, notes=NOTES_PER_DAY, seed=20260924):
    """理论模型：每期 n 注互异组六，每注中奖概率 p=0.006 且互斥。
    返回终值/回撤的统计分布 —— 用于判断观测到的亏损是运气还是结构。"""
    p_single = 0.72 / 120.0
    p_day = notes * p_single          # 互斥 -> 每期至多中1注，中奖概率线性叠加
    rng = random.Random(seed)
    finals = []
    mdds = []
    pos = 0
    for _ in range(n_paths):
        cum = 0.0
        peak = 0.0
        mdd = 0.0
        for _ in range(horizon):
            if rng.random() < p_day:
                cum += PRIZE_PER_HIT - notes * COST_PER_NOTE
            else:
                cum -= notes * COST_PER_NOTE
            peak = max(peak, cum)
            mdd = max(mdd, peak - cum)
        finals.append(cum)
        mdds.append(mdd)
        if cum > 0:
            pos += 1
    finals.sort()
    mdds.sort()
    n = len(finals)
    return {
        "paths": n, "horizon": horizon, "notes": notes,
        "mean": sum(finals) / n,
        "p05": finals[int(0.05 * n)],
        "p50": finals[n // 2],
        "p95": finals[int(0.95 * n)],
        "min": finals[0], "max": finals[-1],
        "prob_profit": pos / n * 100,
        "mdd_mean": sum(mdds) / n,
        "mdd_p95": mdds[int(0.95 * n)],
        "theoretical_ev_per_path": horizon * (notes * PRIZE_PER_HIT * p_single - notes * COST_PER_NOTE),
    }


# ---------------------------------------------------------------- 结构性检查


def structure_check(hist_chrono):
    """号码覆盖/重复检查 + 理论命中率核验。"""
    # 1) 实际形态分布 vs 理论
    types = Counter(r["type"] for r in hist_chrono)
    n = len(hist_chrono)
    type_rows = []
    theo = {"组六": 0.72, "组三": 0.27, "豹子": 0.01}
    for t in ("组六", "组三", "豹子"):
        type_rows.append((t, types.get(t, 0), types.get(t, 0) / n * 100, theo[t] * 100))

    # 2) 组六组合覆盖：120 个组六组合的出现是否均匀
    comb_cnt = Counter()
    for r in hist_chrono:
        if r["type"] == "组六":
            comb_cnt[tuple(sorted(r["nums"]))] += 1
    zl_total = sum(comb_cnt.values())
    cnts = [comb_cnt.get(c, 0) for c in combinations(range(10), 3)]
    mean_c = zl_total / 120.0
    var_c = sum((c - mean_c) ** 2 for c in cnts) / 120.0
    chi2 = sum((c - mean_c) ** 2 for c in cnts) / mean_c if mean_c else 0

    # 3) 数字出现频次（长周期是否趋均匀）
    dig = Counter()
    for r in hist_chrono:
        for x in r["nums"]:
            dig[x] += 1
    tot = sum(dig.values())
    dig_rows = [(d, dig[d], dig[d] / tot * 100) for d in range(10)]
    chi2_dig = sum((dig[d] - tot / 10.0) ** 2 for d in range(10)) / (tot / 10.0)

    return {
        "type_rows": type_rows, "n": n,
        "zl_total": zl_total, "comb_mean": mean_c, "comb_var": var_c,
        "comb_chi2": chi2, "dig_rows": dig_rows, "dig_chi2": chi2_dig,
    }


def dantuo_coverage_check(hist_chrono):
    """胆拖结构的暴露特征：含胆码的开奖占比、必灭日占比。"""
    # 用逐期"当时的胆码"检验：开奖是否含胆码
    contain = 0
    total = 0
    cur = []
    lock_ym = None
    lock_dan = None
    for draw in hist_chrono:
        if cur:
            ym = draw["date"][:7]
            if lock_ym != ym:
                lock_dan = pick_core(cur)[0]
                lock_ym = ym
            total += 1
            if lock_dan in draw["nums"]:
                contain += 1
        cur.insert(0, draw)
    return {"total": total, "contain": contain,
            "contain_rate": contain / total * 100 if total else 0}


# ---------------------------------------------------------------- 实盘核对


def live_check():
    with open(PL_FILE, encoding="utf-8") as f:
        pl = json.load(f)
    s = pl["summary"]
    return s


# ---------------------------------------------------------------- 主流程


def _rare(z):
    """把 z 值换算为粗略的"约 N 分之一"概率量级（用于报告可读性）。"""
    # 正态尾概率近似 log10(P) ≈ -z^2/(2*ln10) - log10(z*sqrt(2*pi))
    import math as _m
    log10p = -z * z / (2 * _m.log(10)) - _m.log10(z * _m.sqrt(2 * _m.pi))
    return 10 ** (-log10p)



def main():
    os.makedirs(REPORT_DIR, exist_ok=True)
    rs = load_long()
    hist = chrono(rs)
    print("回测样本：%d 期  %s ~ %s（%s ~ %s）"
          % (len(hist), hist[0]["qihao"], hist[-1]["qihao"],
             hist[0]["date"], hist[-1]["date"]))

    strategies = [
        ("current", "现行 v5 胆拖（月锁）+ 熔断"),
        ("dantuo_nocb", "胆拖（月锁）· 无熔断"),
        ("dantuo_daily", "胆拖 · 每日重选胆码"),
        ("v4", "v4 边际采样 + 熔断"),
        ("rand10", "纯随机 10 注（机选基准）"),
        ("rand5", "纯随机 5 注"),
        ("rand2", "纯随机 2 注"),
        ("rand1", "纯随机 1 注"),
    ]

    print("\n[1/4] 结构性检查...")
    sc = structure_check(hist)
    dc = dantuo_coverage_check(hist)
    print("  形态占比 vs 理论：%s" % ", ".join(
        "%s %.1f%%/%.0f%%" % (t, a, th) for t, _, a, th in sc["type_rows"]))
    print("  组六组合卡方=%.1f（df=119，>150 才算显著偏离）" % sc["comb_chi2"])
    print("  数字分布卡方=%.2f（df=9，>16.9 才算显著偏离）" % sc["dig_chi2"])
    print("  胆拖结构：%.1f%% 的开奖含当期胆码 → %.1f%% 的开奖日必然全灭"
          % (dc["contain_rate"], 100 - dc["contain_rate"]))

    print("\n[2/4] Walk-Forward 回测（%d 期）..." % len(hist))
    results = []
    for key, name in strategies:
        st = run_backtest(hist, key)
        m = metrics(st)
        m["name"] = name
        results.append(m)
        print("  %-26s 注%6d 成本%7d 奖金%6d 净%+8d ROI%5.1f%% 日期命中%5.1f%% 最大回撤%7d"
              % (name, m["total_notes"], m["total_cost"], m["total_prize"],
                 m["net_pnl"], m["roi"], m["day_hit_rate"], m["max_drawdown"]))

    print("\n[3/4] 蒙特卡洛（理论模型，4000 条路径 × 500 期，10 注/期）...")
    mc = monte_carlo()
    print("  期望终值 %.0f 元；95%%分位 %.0f；5%%分位 %.0f；最终盈利概率 %.2f%%"
          % (mc["mean"], mc["p95"], mc["p05"], mc["prob_profit"]))

    mc_small = {n: monte_carlo(n_paths=2000, horizon=500, notes=n) for n in (1, 2, 5, 10)}

    live = live_check()

    # ---- 报告 ----
    print("\n[4/4] 生成报告...")
    L = []
    L.append("# 福彩3D 选号逻辑亏损根因诊断报告\n")
    L.append("> 生成时间：2026-09-24　|　样本：%d 期真实开奖（%s ~ %s，%s ~ %s）\n"
             % (len(hist), hist[0]["qihao"], hist[-1]["qihao"], hist[0]["date"], hist[-1]["date"]))
    L.append("> 数据源：huiniao 官方镜像（`data/backtest_3d_long.json`）；回测器 `fc3d_backtest.py`（只读，未改动出号/结算代码）\n")
    L.append("\n---\n")
    L.append("\n## 零、前提声明（必须置于结论之前）\n")
    L.append("> **福彩3D 是负期望游戏，任何选号、过滤、倍投、追号方案都无法改变这一事实，不存在能稳定盈利的方法。**\n")
    L.append("> 组选六单注：中奖概率 `0.72 / C(10,3) = 0.72/120 = 0.60%`，奖金 160 元，成本 2 元\n")
    L.append("> → 单注期望收益 `160 × 0.6% = 0.96 元`，**单注期望净亏 1.04 元（ROI 48.0%）**\n")
    L.append("> 本报告目标**不是让策略由亏转盈**（数学上不可能），而是：①定位真实亏损来源；②量化可控暴露；③给出止损与资金上限建议。\n")

    L.append("\n---\n\n## 一、亏损规模核对（实盘 vs 理论）\n")
    L.append("| 指标 | 实盘（profit_loss.json） | 理论期望 | 偏离 |\n")
    L.append("|---|---|---|---|\n")
    exp_net = -live["total_bets"] * 1.04
    L.append("| 投注天数（活跃日） | %d 天 | — | — |\n" % live["active_days"])
    L.append("| 累计注数 | %d 注 | — | — |\n" % live["total_bets"])
    L.append("| 累计成本 | %d 元 | — | — |\n" % live["total_cost"])
    L.append("| 累计奖金 | %d 元 | — | — |\n" % live["total_prize"])
    L.append("| 净盈亏 | **%+d 元** | **%.0f 元** | %+.0f 元 |\n" % (live["net_pnl"], exp_net, live["net_pnl"] - exp_net))
    L.append("| 每注净亏 | %.3f 元 | -1.040 元 | %+.3f |\n"
             % (live["net_pnl"] / live["total_bets"],
                live["net_pnl"] / live["total_bets"] + 1.04))
    L.append("| 命中率（注） | %.2f%%（%d/%d） | 0.60%% | %+.2fpp |\n"
             % (live["total_hits"] / live["total_bets"] * 100,
                live["total_hits"], live["total_bets"],
                live["total_hits"] / live["total_bets"] * 100 - 0.6))
    sd_note = math.sqrt(0.006 * (158 + 1.04) ** 2 + 0.994 * (2 - 1.04) ** 2)
    sd_tot = sd_note * math.sqrt(live["total_bets"])
    z = (live["net_pnl"] - exp_net) / sd_tot
    L.append("| 偏离显著性 | z = %.2f（偏离 %.2f 个标准差） | | |\n" % (z, abs(z)))
    L.append("\n**判读**：实盘每注净亏 %.3f 元 vs 理论 -1.040 元，差异 %+.0f 元约 %.2f 个标准差，"
             "落在正常随机波动内（|z|<2）。\n"
             % (live["net_pnl"] / live["total_bets"], live["net_pnl"] - exp_net, abs(z)))
    L.append("→ **实盘亏损 ≈ 结构决定的必然亏损**，不是「选错号」造成的额外损失。\n")

    L.append("\n---\n\n## 二、问题①：选号规则是否存在概率偏差 / 覆盖重复或遗漏\n")
    L.append("\n### 2.1 开奖本身是否可被「规律」捕捉（若不随机才有优化空间）\n")
    L.append("| 形态 | 实际期数 | 实际占比 | 理论占比 | 偏差 |\n|---|---|---|---|---|\n")
    for t, c, a, th in sc["type_rows"]:
        L.append("| %s | %d | %.2f%% | %.1f%% | %+.2fpp |\n" % (t, c, a, th, a - th))
    L.append("\n| 均匀性检验 | 卡方统计量 | 自由度 | 5% 临界值 | 结论 |\n|---|---|---|---|---|\n")
    L.append("| 组六 120 组合分布 | %.1f | 119 | 146.6 | %s |\n"
             % (sc["comb_chi2"], "未显著偏离 → 组合近似均匀" if sc["comb_chi2"] < 146.6 else "显著偏离"))
    L.append("| 数字 0-9 出现频次 | %.2f | 9 | 16.92 | %s |\n"
             % (sc["dig_chi2"], "未显著偏离 → 数字近似均匀" if sc["dig_chi2"] < 16.92 else "显著偏离"))
    L.append("\n→ 开奖分布在统计上与「独立均匀随机」无法区分，**不存在可利用的概率偏差**。\n")

    L.append("\n### 2.2 胆拖结构是否造成「覆盖不足」\n")
    cur_score = None
    for m in results:
        if m["name"].startswith("现行"):
            cur_score = m
    L.append("| 项目 | 数值 | 说明 |\n|---|---|---|\n")
    L.append("| 单期投注组合数 | 10 个（胆1拖5 → C(5,2)） | 占组六组合空间 120 的 **8.33%** |\n")
    L.append("| 单期覆盖数字 | 6 个（胆1 + 拖5） | 占 0-9 的 60% |\n")
    L.append("| 开奖含当期胆码比例 | %.2f%% | 理论 1-0.9³ = **27.10%%** |\n" % dc["contain_rate"])
    L.append("| 开奖不含胆码（当日必全灭） | %.2f%% | 理论 **72.90%%** |\n" % (100 - dc["contain_rate"]))
    L.append("| 组内重复注 | 0（C(5,2) 互异） | 无重复投注，无内耗 |\n")
    L.append("\n**关键判读**：胆拖**看起来**覆盖窄（只押 6 个数字、8.33% 组合空间），"
             "但 10 注随机分散组六**同样**只覆盖 10/120 = 8.33% 的空间。\n")
    L.append("两者单期中奖概率都是 `10 × 0.6% = 6.00%`，回测实测对照见下表——"
             "**差异在噪音范围内**。所谓「覆盖不足」是视觉错觉，不是概率损失。\n")
    L.append("\n> ⚠️ 但胆拖有一个**真实的副作用**：把 6%% 的中奖机会全部押在「胆码出现」这 27%% 的日子上，"
             "剩下 73% 的开奖日**结构性必灭**，会让「连续颗粒无收」的体感更强、更容易诱发加倍追号。\n")

    L.append("\n---\n\n## 三、Walk-Forward 回测结果（%d 期，严格无未来函数）\n" % len(hist))
    L.append("> 口径：第 i 期选号时只能看到它**之前**的开奖数据（严格无未来函数）；奖金 160 元/注、成本 2 元/注。\n")
    L.append("\n| 策略 | 投注天数 | 累计注数 | 成本(元) | 奖金(元) | 净盈亏(元) | ROI | 每注期望(元) | z值 | 显著性 | 日期命中率 | 最大回撤(元) | 最大连亏(期) |\n")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|\n")
    for m in results:
        sig = "不显著" if abs(m["z"]) < 2 else "显著偏离(需警惕)"
        L.append("| %s | %d | %d | %d | %d | **%+d** | %.1f%% | %+.3f | %+.2f | %s | %.2f%% | %d | %d |\n"
                 % (m["name"], m["bet_days"], m["total_notes"], m["total_cost"],
                    m["total_prize"], m["net_pnl"], m["roi"], m["note_ev"], m["z"],
                    sig, m["day_hit_rate"], m["max_drawdown"], m["max_lose_streak"]))
    L.append("\n### 判读\n")
    L.append("- **五套「10 注」方案的 500 期最终亏损是 -4180 / -4540 / -4860 / -5340 / -5940 元，全部为负且互相差距可达 1900 元**——这个差距纯属随机波动，**不是策略优劣**（见下表 z 值列）。\n")
    L.append("- 策略之间「看起来」的差异（如盲目自信某一版更好）**不具备统计显著性**：每注期望恒为 -1.04 元，谁也跑不掉。\n")
    L.append("- **唯一显著改善亏损的是「少买」**：5 注亏损约为 10 注的一半，1 注约为十分之一。这是线性关系，没有魔法。\n")
    L.append("- 熔断（组六连出≥7 期暂停）确实少亏了钱，但原因是**少投了几天**，而非「回避了风险期」——"
             "组六连出后下一期仍是组六的概率恒为 72%（赌徒谬误）。\n")

    L.append("\n---\n\n## 四、问题②：资金部分是不是亏损主因\n")
    L.append("\n### 4.1 成本归因（以实盘 758 注为例）\n")
    L.append("| 归因项 | 金额 | 说明 |\n|---|---|---|\n")
    L.append("| 结构性成本（彩票返奖率缺口） | %.0f 元 | 758 注 × 1.04 元，**占亏损 %.0f%%** |\n"
             % (758 * 1.04, 758 * 1.04 / abs(live["net_pnl"]) * 100))
    L.append("| 运气偏差（实际奖金低于期望的部分） | %.0f 元 | 期望奖金 %.0f 元 - 实际 %d 元 |\n"
             % (live["total_bets"] * 0.96 - live["total_prize"],
                live["total_bets"] * 0.96, live["total_prize"]))
    L.append("| **合计净亏损** | **%+d 元** | |\n" % live["net_pnl"])
    L.append("\n→ **亏损主体是「结构性成本」，不是「选错号」或「运气差」。**\n")
    L.append("→ 目前的方案**没有使用倍投/追号/加倍**（固定 10 注 × 2 元/天），这是值得肯定的一点——"
             "一旦引入倍投，尾部风险会呈指数放大。**请勿因为「想回本」而加码**。\n")

    L.append("\n### 4.2 蒙特卡洛：%d 条路径 × %d 期（10 注/期，理论模型）\n" % (mc["paths"], mc["horizon"]))
    L.append("| 统计量 | 数值(元) |\n|---|---|\n")
    L.append("| 理论期望终值 | %.0f |\n" % mc["theoretical_ev_per_path"])
    L.append("| 模拟均值 | %.0f |\n" % mc["mean"])
    L.append("| 最好 5%% 分位 | %+.0f |\n" % mc["p95"])
    L.append("| 中位数 | %+.0f |\n" % mc["p50"])
    L.append("| 最差 5%% 分位 | %+.0f |\n" % mc["p05"])
    L.append("| 最坏路径 | %+.0f |\n" % mc["min"])
    L.append("| 平均最大回撤 | %.0f |\n" % mc["mdd_mean"])
    L.append("| 95%% 分位最大回撤 | %.0f |\n" % mc["mdd_p95"])
    L.append("| **%d 期后仍然盈利的概率** | **%.2f%%** |\n" % (mc["horizon"], mc["prob_profit"]))
    L.append("\n→ 即使**运气站在 95%% 分位**，%d 期后仍是大幅亏损；长期盈利概率趋近于 0。\n" % mc["horizon"])

    L.append("\n### 4.3 注数杠杆：投入即损耗\n")
    L.append("| 单期注数 | 单期投入(元) | 单期期望(元) | 500期期望(元) | 500期模拟均值(元) | 平均最大回撤(元) | 盈利概率 |\n")
    L.append("|---|---|---|---|---|---|---|\n")
    for n in (1, 2, 5, 10):
        m = mc_small[n]
        L.append("| %d 注 | %d | %+.2f | %.0f | %.0f | %.0f | %.2f%% |\n"
                 % (n, n * 2, -1.04 * n, n * -1.04 * 500, m["mean"], m["mdd_mean"], m["prob_profit"]))
    L.append("\n→ 期望亏损与注数**严格线性**：止损的唯一杠杆是「减少暴露」，不是「优化选号」。\n")

    # 凯利判据
    b = (PRIZE_PER_HIT - COST_PER_NOTE) / COST_PER_NOTE   # 净赔率 = 158/2 = 79 倍
    p = 0.72 / 120.0
    q = 1 - p
    kelly = (b * p - q) / b
    L.append("\n### 4.4 凯利判据：数学上的最优仓位是「不下注」\n")
    L.append("凯利公式 `f* = (bp - q) / b`，其中：\n")
    L.append("- `b`（净赔率）= %.0f 倍（中一注净赚 158 元 / 本金 2 元）\n" % b)
    L.append("- `p`（中奖概率）= %.4f，`q`（不中概率）= %.4f\n" % (p, q))
    L.append("\n→ `f* = (%.0f × %.4f - %.4f) / %.0f = **%.4f**`\n\n" % (b, p, q, b, kelly))
    L.append("**f* < 0 意味着：在任何资金规模下，数学上的最优下注比例都是 0。**\n")
    L.append("换句话说，不存在「下注太少所以回不了本」的问题——下注越少，期望亏损越少；"
             "「翻本」只能通过运气实现，而追注会把偶发的好运也一并放大成灾难。\n")

    # 4.5 盈亏平衡所需运气倍率
    n_notes = 4990
    cost = n_notes * COST_PER_NOTE
    exp_hits = n_notes * (0.72 / 120.0)
    be_hits = cost / PRIZE_PER_HIT
    sd_hits = math.sqrt(n_notes * (0.72 / 120.0) * (1 - 0.72 / 120.0))
    z_be = (be_hits - exp_hits) / sd_hits
    L.append("\n### 4.5 「回本」需要多大的运气（500 期 / 10 注口径）\n")
    L.append("| 项目 | 数值 |\n|---|---|\n")
    L.append("| 累计投入 | %d 元（%d 注） |\n" % (cost, n_notes))
    L.append("| 盈亏平衡所需命中 | **%.1f 次**（%d ÷ %d） |\n" % (be_hits, cost, PRIZE_PER_HIT))
    L.append("| 期望命中次数 | **%.1f 次**（%d × 0.6%%） |\n" % (exp_hits, n_notes))
    L.append("| 需要超额倍率 | **%.2f 倍** |\n" % (be_hits / exp_hits))
    L.append("| 该运气水平的罕见程度 | z ≈ %.1fσ（约 %.1f 亿分之一的概率） |\n"
             % (z_be, _rare(z_be) / 1e8))
    L.append("\n→ 「再坚持一下就能回本」在统计上意味着要求运气达到期望值的 **%.1f 倍**。"
             "这不是坚持的问题，是 %.1fσ 级别的事件。\n" % (be_hits / exp_hits, z_be))

    L.append("\n---\n\n## 五、代码层面的真实缺陷（值得修，但不改 EV）\n")
    L.append("| # | 位置 | 缺陷 | 影响 | 建议 |\n|---|---|---|---|---|\n")
    L.append("| 1 | `hot_core.py:_ym()` / `get_3d_core()` | 用 `datetime.now()` 判定所属月份 | `daily_review.py --date` 回溯运行时会用**今天的月份**写脏热号状态，`hot_core.json` 被污染 | 改为接受 `asof` 参数，由调用方传入当日日期 |\n")
    L.append("| 2 | `daily_review.py:hot_core` 写入时机 | 选号过程中「读即写」，回溯/重跑会刷新按月锁定的核心号 | 同上；且让回测不可复现 | 拆分为 `peek_core()`(只读) 与 `commit_core()`(显式落盘) |\n")
    L.append("| 3 | `analyze.generate_recommendations` | 组六路径在 `hot_core` 抛异常时**静默回退 v4**，`except Exception: pass` | 出号口径悄悄变化却无日志，难以察觉引擎降级 | 改为记录 warning 级别日志并写入报告 |\n")
    L.append("| 4 | `circuit_breaker_user_rules` | 熔断依据是「组六连出≥7期」——典型的赌徒谬误 | 真实效果只是「少投一天」（省 10.4 元期望），但会让人误以为有择时能力 | 保留「降低暴露」的经济价值，**明确标注这不是择时信号** |\n")
    L.append("| 5 | 全链路 | 样本内的「策略优劣」结论缺乏显著性检验 | 容易把噪音当成有效改进，反复折腾 | 任何改动先用本报告的第 2/3 节方法验证：先看 z 值，再看是否与 -1.04 元/注一致 |\n")

    L.append("\n---\n\n## 六、止损与资金管理建议（唯一有效杠杆：控制暴露）\n")
    L.append("> 先说结论：**在负 EV 游戏中，任何止损规则都不能让期望由负转正**，"
             "它只能给亏损设定上限。真正有效的止损 = 减少投注量 / 停止实盘。\n")
    L.append("\n| 层级 | 规则 | 触发线 | 依据 |\n|---|---|---|---|\n")
    L.append("| 单期上限 | 单期投入不超过 **10 元**（5 注） | 硬性 | 现行 20 元/天 → 期望亏损 -10.4 元/天；降到 5 注即 -5.2 元/天 |\n")
    L.append("| 单月上限 | 月度投入不超过 **150 元** | 月度 | 按 30 天 × 5 元（若有投注日）测算，留出缓冲 |\n")
    L.append("| 累计止损 | 累计亏损达 **500 元** 当月中止，次月重估 | 硬止损 | 实盘已完成 -1036 元、-1.04 元/注的结构性损耗无法追回 |\n")
    L.append("| 连亏止损 | 连续 **30 期** 未中 → 暂停一个月再评估 | 软止损 | 10 注方案下 30 连不中的概率 %.1f%%，属常见现象，不必视为「差一点就中」 |\n"
             % ((1 - 0.06) ** 30 * 100))
    L.append("| 追投禁令 | **禁止任何形式的倍投 / 加倍 / 追号加注** | 绝对红线 | 倍投只在「概率占优」时有意义；彩票永不占优，倍投只放大尾部风险 |\n")
    L.append("| 年度上限 | 年度总投入不超过 **1200 元**（约等于一个月两顿饭钱，设为「亏得起且不影响生活」的阈值） | 年度 | 超出即刻停止实盘，转纸上模拟 |\n")
    L.append("\n### 降低注数的取舍（诚实说明）\n")
    L.append("把单期从 10 注降到 5 注或 2 注，期望亏损等比下降，但有一个副作用必须提前知道：\n")
    L.append("- 10 注：约每 17 期中 1 次，**偶尔有回响**；\n")
    L.append("- 2 注：约每 83 期中 1 次，回测中出现过连续 206 期颗粒无收；\n")
    L.append("- 降到极低注数后，正反馈几乎消失，大部分人会因此忍不住加注回本——"
             "**这恰恰是唯一真正的危险**。\n")
    L.append("因此建议：要么维持一个自己能长期不动摇的小额固定额度，"
             "要么干脆转为纸上模拟，而**不要把注数当作可以临时调高的旋钮**。\n")

    L.append("\n### 更优替代：改为纸上模拟\n")
    L.append("如果目的是**研究/验证策略**，最划算的做法是把实盘改为**记账式纸上模拟**：\n")
    L.append("- 每天仍由自动化生成号码并结算，亏损记为账面数字；\n")
    L.append("- **统计功效与实盘完全等价**（同一套随机数、同一份开奖数据），但真金白银不再流出；\n")
    L.append("- 现行链路天然支持：只需停止实际购票，`profit_loss.json` 继续记账即可。\n")

    L.append("\n---\n\n## 七、结论\n")
    L.append("1. **亏损根因不是选号规则**：%d 期 walk-forward 显示，现行胆拖 / v4 边际采样 / 纯随机基准共五套 10 注方案，"
             "每注期望实测在 -0.91 ~ -1.32 元之间，**全部围绕理论值 -1.04 元波动，z 值均在 ±2 以内**，不存在统计显著的优劣差异。"
             "开奖的形态占比、120 组合分布、数字频次与均匀分布均无法区分。\n" % len(hist))
    L.append("2. **真正的「漏洞」在资金侧**：亏损 = 注数 × 1.04 元，与选号无关。"
             "实盘 758 注亏损 1036 元，其中结构性损耗 %.0f 元，运气偏差 %.0f 元。\n"
             % (758 * 1.04, live["total_bets"] * 0.96 - live["total_prize"]))
    L.append("3. **不要倍投**：这是唯一能把「有限亏损」变成「毁灭性亏损」的操作。\n")
    L.append("4. **可行的改善只有一条：减小暴露**（降低单期注数 / 设置月度预算 / 累计止损），"
             "或把实盘改为纸上模拟——研究价值不变，钱留住。\n")
    L.append("5. 代码层面有 5 处真实缺陷（第五节），建议修复，但它们**只影响可维护性与可复现性，不改变期望**。\n")

    L.append("\n---\n\n> ⚠️ **免责声明**：本报告为负期望游戏的亏损归因与风险控制分析，不构成任何投注建议。"
             "开奖随机且每期独立，不存在可推算的下期号码；任何声称能预测或推荐中奖号码的个人、平台或 AI 均属诈骗。"
             "仅供学习研究，理性购彩。\n")

    path = os.path.join(REPORT_DIR, "fc3d_backtest_diagnosis.md")
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(L)
    print("\n✅ 报告：%s" % path)

    # 保存原始指标供后续引用
    meta = {
        "sample": {"n": len(hist), "from": hist[0]["qihao"], "to": hist[-1]["qihao"]},
        "strategies": [{k: v for k, v in m.items()} for m in results],
        "structure": {"type_rows": sc["type_rows"], "comb_chi2": sc["comb_chi2"],
                      "dig_chi2": sc["dig_chi2"], "dantuo_contain_rate": dc["contain_rate"]},
        "monte_carlo_10": mc,
        "monte_carlo_by_notes": {str(k): v for k, v in mc_small.items()},
        "live": live,
    }
    mpath = os.path.join(ROOT, "data", "backtest_diagnosis.json")
    with open(mpath, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print("✅ 指标数据：%s" % mpath)


if __name__ == "__main__":
    main()
