# -*- coding: utf-8 -*-
"""
福彩3D「大小形态两组」每日复盘（2026-11-05 起生效）
=====================================================
云明 2026-11-04 指令：「明天开始，3d就按昨天的来，加两组按大小形态的号码，并每天复盘」。

设计原则（重要，勿改）：
  1) **独立模块 + 独立台账**，由 unified_review.py 在 3D 主线之后调用。
     `daily_review.py` / `profit_loss.json` 一行不动 —— 主台账每条记录的
     notes/cost/hits 强耦合，塞进去会污染 139 条历史记录口径。
  2) 两组形态固定：A「大大小」、B「大小小」（沿用 2026-11-02 那两组）。
     每天按各位该侧近 100 期频率 TOP2 重算数字，各 8 注，合计 16 注 / 32 元/天。
     复用 position_pattern.build_notes，规则与 11-02 完全一致。
  3) 结算按**直选精确命中**（三位同位同值），1040 元/注；组选集合相同不算中奖
     （组六玩法已于 2026-09-28 移除）。盈亏记入独立台账，不并入四品种合计。
  4) EFFECTIVE_FROM = 2026-11-05，生效前 run_daily 直接跳过、不写任何文件
     （保证「明天开始」，今天重跑 unified_review.py 也不会提前建仓）。
  5) 幂等：按 date 判重建仓、按 hits is None 判重结算，可重复运行。

⚠️ 出号性质红线（勿删、勿回退）：
  本模块所有号码一律称「随机采样」，等同投注站机选、无预测力；
  开奖随机且每期独立，不存在可推算的下期号码；声称能预测或收费荐号者均属诈骗；
  仅供学习研究，不构成投注建议。禁止出现「推荐/预测/荐号」字样。
  形态只决定钱花在哪一块，命中率恒 = 注数/1000，直选单注 0.1%、ROI 52%。

用法：
  python size_pattern_daily.py                # 正常每日跑（生效日前自动跳过）
  python size_pattern_daily.py --dry-run      # 只打印今日两组号码，不写台账/报告
  python size_pattern_daily.py --selftest     # 临时目录下验证建仓/结算/幂等
  python size_pattern_daily.py --date 2026-11-05
"""
import os
import sys
import json
import tempfile
import argparse
from datetime import datetime, date, timedelta

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import position_pattern as pp
import period_util
from trading_day import is_trading_day
from atomic_io import save_json_atomic, load_json_checked
from alerts import ALERTS

DATA_DIR = os.path.join(ROOT, "data")
REPORT_DIR = os.path.join(DATA_DIR, "reports")
HIST = os.path.join(DATA_DIR, "3d_history.json")
LONG = os.path.join(DATA_DIR, "backtest_3d_long.json")
STATE = os.path.join(DATA_DIR, "size_pattern_state.json")

ENGINE_VERSION = "大小形态v1"
EFFECTIVE_FROM = "2026-11-05"          # 云明指令「明天开始」
GROUP_PATTERNS = (("A", "大大小"), ("B", "大小小"))
PER_POS = (2, 2, 2)                    # 各位候选数 → 2×2×2 = 8 注/组
COST_PER_NOTE = 2
PRIZE_PER_HIT = 1040                   # 直选奖金，与开奖形态无关
WINDOW_FREQ = 100                      # 频率统计窗口
MERGE_WINDOW = 500                     # 与 position_pattern 一致

DISCLAIMER = (
    "⚠️ 本节号码均为程序按历史分布随机采样生成，等同投注站机选、无预测力；"
    "开奖随机且每期独立，不存在可推算的下期号码；任何声称能预测或收费荐号者均属诈骗。"
    "仅供学习研究，不构成投注建议。"
)


def _today_str():
    return datetime.now().strftime("%Y-%m-%d")


def _load_recs():
    """合并长历史 + 每日抓取数据（qihao 去重），返回从旧到新的最近 500 期。"""
    short = pp.load(HIST)
    long_ = pp.load(LONG)
    merged = {r["qihao"]: r for r in long_}
    merged.update({r["qihao"]: r for r in short})
    return sorted(merged.values(), key=lambda r: r["qihao"])[-MERGE_WINDOW:]


def _new_state():
    return {
        "version": 1,
        "engine": ENGINE_VERSION,
        "effective_from": EFFECTIVE_FROM,
        "patterns": [p for _, p in GROUP_PATTERNS],
        "notes_per_group": 8,
        "cost_per_note": COST_PER_NOTE,
        "prize_per_hit": PRIZE_PER_HIT,
        "records": [],
        "summary": {"net_pnl": 0, "total_hits": 0, "total_bets": 0,
                    "rounds": 0, "pending_rounds": 0},
    }


def _load_state(path):
    try:
        return load_json_checked(path)
    except FileNotFoundError:
        return _new_state()


def _recalc_summary(state):
    settled = [r for r in state["records"] if r.get("hits") is not None]
    pending = [r for r in state["records"] if r.get("hits") is None]
    state["summary"] = {
        "net_pnl": sum(r.get("daily_pnl", 0) or 0 for r in settled),
        "total_hits": sum(r.get("hits", 0) or 0 for r in settled),
        "total_bets": sum(r.get("notes", 0) or 0 for r in settled),
        "rounds": len(settled),
        "pending_rounds": len(pending),
    }
    return state["summary"]


def _gen_groups(recs):
    """按固定两种形态各生成 8 注（各位取该侧近100期频率 TOP2）。"""
    out = {}
    for key, pat in GROUP_PATTERNS:
        nt = pp.build_notes(None, PER_POS, recs, WINDOW_FREQ, pat)
        notes = [list(n) for n in nt["notes"]]
        if len(notes) != 8:
            raise RuntimeError("组 %s(%s) 注数异常：%d（应为 8）" % (key, pat, len(notes)))
        out[key] = {"pattern": pat, "notes": notes,
                    "digits": {k: v for k, v in nt["digits"].items()}}
    return out


def _all_notes(rec):
    return [n for g in rec["groups"].values() for n in g["notes"]]


def _settle(state, recs, today):
    """结算所有到期 pending：按 target_qihao 精确匹配开奖，直选精确比对。"""
    settled = []
    by_qihao = {str(h["qihao"]): h for h in recs}
    for rec in state["records"]:
        if rec.get("hits") is not None or rec.get("date", "") >= today:
            continue
        target = str(rec.get("target_qihao") or "")
        draw = by_qihao.get(target)
        if draw is None:
            print("  ⏸ 目标期号 %s 尚未抓到，暂缓结算（下期再试），不污染数据" % target)
            continue
        nums = tuple(draw["nums"])
        all_notes = _all_notes(rec)
        hit_notes = [n for n in all_notes if tuple(n) == nums]
        hits = len(hit_notes)
        rec["draw"] = draw["qihao"]
        rec["draw_date"] = draw.get("date", "")
        rec["draw_nums"] = list(nums)
        rec["hits"] = hits
        rec["prize"] = hits * PRIZE_PER_HIT
        rec["daily_pnl"] = rec["prize"] - rec["cost"]
        rec["hit_notes"] = hit_notes
        rec["reason"] = "直选%d注->%d命中 开奖%s" % (
            rec["notes"], hits, "".join(str(x) for x in nums))
        settled.append({
            "date": rec["date"], "target_qihao": target,
            "draw_issue": draw["qihao"], "draw_nums": list(nums),
            "win_notes": hits, "prize": rec["prize"], "daily_pnl": rec["daily_pnl"],
        })
        print("  结算 %s期 → %d命中，奖金%d元，日盈亏%+d元" % (
            target, hits, rec["prize"], rec["daily_pnl"]))
    return settled


def _write_report(today, state, settled, groups, target, skipped_reason=""):
    os.makedirs(REPORT_DIR, exist_ok=True)
    path = os.path.join(REPORT_DIR, "size_pattern_%s.md" % today)
    s = state["summary"]
    L = []
    L.append("# 福彩3D 大小形态两组（独立台账）%s\n" % today)
    L.append("\n> ⚠️ **性质声明**：号码均为程序按历史分布随机采样生成，"
             "**等同投注站机选，不具备预测能力**。\n")
    L.append("> 彩票开奖完全随机、每期独立，不存在可推算的下期号码；"
             "任何声称能预测或收费荐号的个人、平台或 AI 均属诈骗。\n")
    L.append("> 本报告仅供学习研究与盈亏记录，不构成投注建议。\n")
    L.append("\n- 引擎：%s｜形态固定 大大小 / 大小小｜每日按各位该侧近100期频率 TOP2 重算数字\n"
             % ENGINE_VERSION)
    L.append("- 成本：2组 × 8注 × 2元 = **32元/天**；直选精确命中 1040 元/注\n")
    L.append("- 台账：`data/size_pattern_state.json`（独立，不并入四品种合计，主台账零改动）\n")
    if skipped_reason:
        L.append("\n- 本日状态：%s\n" % skipped_reason)
    L.append("\n## 昨日结算\n")
    if settled:
        for x in settled:
            L.append("- 押%s期（开奖 %s）→ %d命中，奖金%d元，日盈亏%+d元\n" % (
                x["target_qihao"], "".join(str(d) for d in x["draw_nums"]),
                x["win_notes"], x["prize"], x["daily_pnl"]))
    else:
        L.append("- 无待结算（首日建仓或目标期号尚未抓到）\n")
    L.append("\n## 今日随机采样（押%s期，共16注）｜等同机选·无预测力【选号引擎 %s】\n"
             % (target or "—", ENGINE_VERSION))
    L.append("\n> %s\n" % DISCLAIMER)
    for key, pat in GROUP_PATTERNS:
        g = (groups or {}).get(key)
        if not g:
            continue
        L.append("\n### %s 组（形态 %s，8注）\n" % (key, pat))
        for i, n in enumerate(g["notes"], 1):
            L.append("  %d. %s\n" % (i, " ".join(str(x) for x in n)))
    L.append("\n## 独立台账累计\n")
    L.append("- 净盈亏：**%+d元**（%d命中 / %d注 / 已结算%d轮，待结算%d轮）\n" % (
        s["net_pnl"], s["total_hits"], s["total_bets"], s["rounds"], s["pending_rounds"]))
    L.append("\n---\n*仅供学习研究，不构成投注建议。生成时间 %s*\n"
             % datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(L)
    return path


def run_daily(today=None, state_path=None, write_report=True, dry_run=False):
    """每日入口。返回结构化 dict 供 unified_review.wechat_block 使用。"""
    today = today or _today_str()
    state_path = state_path or STATE
    empty = {"game": "3D大小形态两组", "today": today, "failed": False,
             "skipped": False, "settled": [], "groups": {}, "target": None,
             "summary": {"net_pnl": 0, "total_hits": 0, "total_bets": 0,
                         "rounds": 0, "pending_rounds": 0},
             "report_path": None}

    if today < EFFECTIVE_FROM:
        print("  ⏭ 3D大小形态两组：%s 起生效，本日(%s)跳过，不写台账" % (EFFECTIVE_FROM, today))
        r = dict(empty)
        r["skipped"] = True
        r["skip_reason"] = "%s 起生效" % EFFECTIVE_FROM
        return r

    recs = _load_recs()
    if not recs:
        ALERTS.add("ERROR", "3D大小形态两组", "历史数据为空，无法出号")
        r = dict(empty)
        r["failed"] = True
        return r
    latest = recs[-1]

    if dry_run:
        groups = _gen_groups(recs)
        print("  [dry-run] 最新开奖 %s = %s" % (
            latest["qihao"], "".join(str(x) for x in latest["nums"])))
        for key, pat in GROUP_PATTERNS:
            print("  [dry-run] %s组(%s) 8注：%s" % (
                key, pat, " / ".join("".join(str(x) for x in n)
                                    for n in groups[key]["notes"])))
        r = dict(empty)
        r["groups"] = groups
        r["target"] = period_util.next_3d_qihao(latest["qihao"], latest.get("date"))
        return r

    state = _load_state(state_path)
    settled = _settle(state, recs, today)

    # 今日是否已建仓（幂等）
    today_rec = next((x for x in state["records"] if x.get("date") == today), None)
    today_dt = datetime.strptime(today, "%Y-%m-%d").date()
    if today_rec is None:
        if not is_trading_day(today_dt):
            state["records"].append({
                "date": today, "target_qihao": None, "draw": "休市",
                "draw_nums": [], "groups": {}, "notes": 0, "cost": 0,
                "hits": 0, "prize": 0, "daily_pnl": 0, "reason": "官方休市期，无出号",
            })
            groups, target, skip_reason = {}, None, "官方休市期，无出号"
            print("  ⏸ 休市：今日无出号")
        else:
            target = period_util.next_3d_qihao(latest["qihao"], latest.get("date"))
            dup = next((r for r in state["records"]
                        if r.get("hits") is None
                        and str(r.get("target_qihao")) == str(target)), None)
            if dup is not None:
                # 数据源滞后时 target 不变 → 复用已挂 pending，绝不重复建仓/重复计费
                groups = dup.get("groups", {})
                state["records"].append({
                    "date": today, "target_qihao": None, "draw": "沿用pending",
                    "draw_nums": [], "groups": {}, "notes": 0, "cost": 0,
                    "hits": 0, "prize": 0, "daily_pnl": 0,
                    "reason": "目标期号 %s 已有 pending，沿用不重复建仓（数据滞后保护）" % target,
                })
                skip_reason = "目标期号 %s 已有 pending，沿用不重复建仓（数据滞后保护）" % target
                target = None
                print("  ⏸ %s" % skip_reason)
            else:
                groups = _gen_groups(recs)
                state["records"].append({
                    "date": today, "target_qihao": target, "draw": "待开奖",
                    "draw_nums": [], "groups": groups,
                    "notes": sum(len(g["notes"]) for g in groups.values()),
                    "cost": sum(len(g["notes"]) for g in groups.values()) * COST_PER_NOTE,
                    "hits": None, "prize": None, "daily_pnl": None,
                    "reason": "大小形态两组随机采样（形态固定 大大小/大小小，各位该侧近100期频率TOP2）",
                })
                skip_reason = ""
                print("  今日随机采样：2组各8注（押%s期），成本32元" % target)
                for key, pat in GROUP_PATTERNS:
                    print("    %s组(%s)：%s" % (
                        key, pat, " ".join("".join(str(x) for x in n)
                                          for n in groups[key]["notes"])))
        today_rec = state["records"][-1]
    else:
        groups = today_rec.get("groups", {})
        target = today_rec.get("target_qihao")
        skip_reason = ""
        print("  今日(%s)已建仓，跳过重复生成" % today)

    summary = _recalc_summary(state)
    save_json_atomic(state_path, state)
    report_path = None
    if write_report:
        report_path = _write_report(today, state, settled, groups, target, skip_reason)

    return {"game": "3D大小形态两组", "today": today, "failed": False,
            "skipped": False, "settled": settled, "groups": groups,
            "target": target, "summary": summary, "report_path": report_path,
            "patterns": [p for _, p in GROUP_PATTERNS]}


def _selftest():
    """临时目录验证：建仓 → 幂等 → 结算命中计数。不触碰真实台账。"""
    tmp = tempfile.mkdtemp(prefix="szp_selftest_")
    sp = os.path.join(tmp, "state.json")
    print("selftest state:", sp)

    r1 = run_daily(today="2026-11-05", state_path=sp, write_report=False)
    assert len(r1["groups"]) == 2, "两组缺失"
    for key, pat in GROUP_PATTERNS:
        assert len(r1["groups"][key]["notes"]) == 8, "%s组注数错" % key
        assert all(pp.pattern_of({"bai": n[0], "shi": n[1], "ge": n[2]}) == pat
                   for n in r1["groups"][key]["notes"]), "%s组形态错" % key
    print("  ✅ 建仓：2组各8注，形态全对，target=%s" % r1["target"])

    r2 = run_daily(today="2026-11-05", state_path=sp, write_report=False)
    st = _load_state(sp)
    assert len(st["records"]) == 1, "重复运行产生了重复记录"
    assert r2["summary"]["pending_rounds"] == 1
    print("  ✅ 幂等：重复运行记录数仍为 1")

    # 把 pending 的 target 改成已开奖的 2026293=185，验证结算（A组 851 集合同但直选不中）
    st["records"][0]["target_qihao"] = "2026293"
    save_json_atomic(sp, st)
    r3 = run_daily(today="2026-11-06", state_path=sp, write_report=False)
    assert len(r3["settled"]) == 1, "结算未发生"
    assert r3["settled"][0]["draw_nums"] == [1, 8, 5], "开奖号错配"
    assert r3["settled"][0]["win_notes"] == 0, "直选口径不应把 851 算中奖"
    assert r3["settled"][0]["daily_pnl"] == -32, "日盈亏应为 -32"
    print("  ✅ 结算：2026293=185 → 0命中（851 集合相同不计），日 -32 元")

    # 再构造一次必然命中：把某注改成开奖号
    st = _load_state(sp)
    st["records"][0]["groups"]["A"]["notes"][0] = [1, 8, 5]
    st["records"][0]["hits"] = None
    st["records"][0]["prize"] = None
    st["records"][0]["daily_pnl"] = None
    save_json_atomic(sp, st)
    r4 = run_daily(today="2026-11-06", state_path=sp, write_report=False)
    assert r4["settled"][0]["win_notes"] == 1, "精确命中未计"
    assert r4["settled"][0]["daily_pnl"] == 1040 - 32, "命中奖金计算错"
    print("  ✅ 命中：1注直选 → 奖金1040，日 +1008 元")
    print("SELFTEST PASS")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="指定日期 YYYY-MM-DD")
    ap.add_argument("--dry-run", action="store_true", help="只打印号码，不写台账")
    ap.add_argument("--selftest", action="store_true", help="临时目录自测")
    a = ap.parse_args()
    if a.selftest:
        _selftest()
    else:
        run_daily(today=a.date, dry_run=a.dry_run)
