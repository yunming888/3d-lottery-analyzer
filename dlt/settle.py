# -*- coding: utf-8 -*-
"""
大乐透 结算与盈亏模块
-------------------
维护 data/dlt_state.json：记录每期选号(目标期号)及结算状态。
建议每日 07:00 运行一次，流程：
  1) 抓取最新历史（包含昨日开奖）
  2) 结算 pending 记录（目标期号 <= 最新期号 的开奖）
  3) 选新号，目标 = 最新期号 + 1（下一期）
  4) 写 per-variety 报告 + 返回汇总（昨日摘要 / 复盘结论 / 具体盈亏）
  5) 同日幂等：若今日已存在记录，跳过选号（避免重复下单/重复结算）

奖级：使用 _dlt_tier 判定，固定奖金额取自 DLT_PRIZE。
一等奖/二等奖为浮动奖池，本模块记为「浮动奖(奖池)」且不计入 PnL（保守）。
"""
import os
import json
from datetime import date, datetime, timedelta

from . import config
from .fetcher import fetch_history
from .analysis import load_history, hot_cold, latest
from .selector import generate_notes

STATE_FILE = os.path.join(config.BASE_DIR, "data", "dlt_state.json")
COST_PER_NOTE = 2  # 每注基本投注金额（元）

# ---- 大乐透奖级（固定奖部分）----
DLT_PRIZE = {3: 10000, 4: 2000, 5: 300, 6: 200, 7: 100, 8: 15, 9: 5}


def _dlt_tier(red_match, blue_match):
    """大乐透奖级判定：传入(命中前区数, 命中后区数)。"""
    if red_match == 5 and blue_match == 2:
        return 1
    if red_match == 5 and blue_match == 1:
        return 2
    if red_match == 5 and blue_match == 0:
        return 3
    if red_match == 4 and blue_match == 2:
        return 4
    if red_match == 4 and blue_match == 1:
        return 5
    if red_match == 3 and blue_match == 2:
        return 6
    if red_match == 4 and blue_match == 0:
        return 7
    if (red_match == 3 and blue_match == 1) or (red_match == 2 and blue_match == 2):
        return 8
    if (red_match == 3 and blue_match == 0) or (red_match == 2 and blue_match == 1) \
            or (red_match == 1 and blue_match == 2) or (red_match == 0 and blue_match == 2):
        return 9
    return 0


# ---------- 状态读写 ----------
def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                st = json.load(f)
            st.setdefault("records", [])
            st.setdefault("summary", _empty_summary())
            return st
        except Exception:
            pass
    return {"game": "dlt", "records": [], "summary": _empty_summary()}


def save_state(st: dict):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)


def _empty_summary():
    return {
        "rounds": 0,          # 已结算轮次
        "total_notes": 0,     # 累计注数
        "total_cost": 0,      # 累计成本
        "total_prize": 0,     # 累计奖金
        "net_pnl": 0,         # 累计净盈亏
        "total_win_notes": 0, # 累计命中注数
        "pending_rounds": 0,  # 待结算轮次
    }


# ---------- 工具 ----------
def _yesterday() -> str:
    return (date.today() - timedelta(days=1)).isoformat()


def _find_draw_by_date(history, d):
    for h in history:
        if h.get("date") == d:
            return h
    return None


def _fmt_note(note):
    reds = " ".join("%02d" % d for d in note["reds"])
    blues = " ".join("%02d" % d for d in note["blues"])
    return "前区 %s  后区 %s" % (reds, blues)


# ---------- 结算 ----------
def _settle(st: dict, history: list):
    """结算所有 pending 且目标期号 <= 最新期号的记录。返回结算明细列表。"""
    if not history:
        return []
    latest_issue = int(history[0]["issue"])
    settled = []
    for rec in st["records"]:
        if rec.get("status") != "pending":
            continue
        tgt = int(rec["target_issue"])
        if tgt > latest_issue:
            continue  # 目标开奖尚未发生
        draw = None
        for h in history:
            if int(h["issue"]) == tgt:
                draw = h
                break
        if draw is None:
            continue  # 缺少该期开奖数据，暂缓
        total_prize = 0
        win_notes = 0
        float_win = False
        best_tier = 0
        for note in rec["notes"]:
            rm = len(set(note["reds"]) & set(draw["reds"]))
            bm = len(set(note["blues"]) & set(draw["blues"]))
            tier = _dlt_tier(rm, bm)
            if tier == 0:
                continue
            prize = DLT_PRIZE.get(tier)
            if prize is None:
                # 一/二等奖浮动奖池
                float_win = True
                win_notes += 1
                best_tier = max(best_tier, tier)
            else:
                total_prize += prize
                win_notes += 1
                best_tier = max(best_tier, tier)
        rec["status"] = "settled"
        rec["draw_issue"] = draw["issue"]
        rec["draw_date"] = draw.get("date", "")
        rec["draw_reds"] = draw["reds"]
        rec["draw_blues"] = draw["blues"]
        rec["win_notes"] = win_notes
        rec["best_tier"] = best_tier
        rec["float_win"] = float_win
        rec["prize"] = total_prize
        rec["daily_pnl"] = total_prize - rec["cost"]
        settled.append(rec)
    return settled


def _calc_summary(st: dict):
    s = _empty_summary()
    for rec in st["records"]:
        if rec.get("status") == "settled":
            s["rounds"] += 1
            s["total_notes"] += len(rec["notes"])
            s["total_cost"] += rec["cost"]
            s["total_prize"] += rec.get("prize", 0)
            s["total_win_notes"] += rec.get("win_notes", 0)
        elif rec.get("status") == "pending":
            s["pending_rounds"] += 1
    s["net_pnl"] = s["total_prize"] - s["total_cost"]
    st["summary"] = s
    return s


# ---------- 选号 ----------
def _select_new(today, history, n_notes):
    notes, bal = generate_notes(history, n_notes)
    target = str(int(history[0]["issue"]) + 1)
    rec = {
        "date": today,
        "target_issue": target,
        "notes": notes,
        "cost": n_notes * COST_PER_NOTE,
        "status": "pending",
        "draw_issue": None, "draw_date": "", "draw_reds": None, "draw_blues": None,
        "win_notes": 0, "best_tier": 0, "float_win": False,
        "prize": 0, "daily_pnl": None,
    }
    return rec, notes, bal, target


# ---------- 报告 ----------
def _write_report(today, history, meta, notes, bal, n_notes, settled, summary, target, yest_draw):
    try:
        os.makedirs(config.REPORT_DIR, exist_ok=True)
        path = os.path.join(config.REPORT_DIR, "dlt_%s.md" % today)
        L = []
        src = "实时抓取(500彩票网)" if not meta.get("fallback") else "本地缓存(抓取失败回退)"
        last = latest(history)
        L.append("# 大乐透 每日复盘 %s\n" % today)
        L.append("> 数据源：%s｜最新 %s｜窗口 %d 期\n" % (src, last.get("issue", "?"), meta.get("count", 0)))

        # 一、昨日数据摘要
        L.append("\n## 一、昨日数据摘要\n")
        if yest_draw:
            L.append("- 昨日(%s)开奖：**%s 期** 前区 %s 后区 %s\n" % (
                yest_draw.get("date", ""), yest_draw["issue"],
                " ".join("%02d" % d for d in yest_draw["reds"]),
                " ".join("%02d" % d for d in yest_draw["blues"])))
        else:
            L.append("- 昨日(%s) **无大乐透开奖**（开奖日：周一 / 周三 / 周六）。\n" % _yesterday())
        if last:
            L.append("- 最新一期：%s 期 前区 %s 后区 %s（%s）\n" % (
                last.get("issue"), " ".join("%02d" % d for d in last["reds"]),
                " ".join("%02d" % d for d in last["blues"]), last.get("date", "")))

        # 二、复盘结论（冷热/均衡）
        hc = hot_cold(history, config.WINDOW)
        L.append("\n## 二、复盘结论\n")
        L.append("- 前区热号：%s；前区冷号(高遗漏)：%s\n" % (
            " ".join("%02d" % d for d in hc["hot_red"]),
            " ".join("%02d" % d for d in hc["cold_red"])))
        L.append("- 后区热号：%s；后区冷号(高遗漏)：%s\n" % (
            " ".join("%02d" % d for d in hc["hot_blue"]),
            " ".join("%02d" % d for d in hc["cold_blue"])))
        L.append("- 本期选号奇偶均衡：前区 奇%d/偶%d，后区 奇%d/偶%d（目标≈50:50）。\n" % (
            bal["r_odd"], bal["r_even"], bal["b_odd"], bal["b_even"]))
        L.append("- 本期选号大小均衡：前区 大%d/小%d，后区 大%d/小%d。\n" % (
            bal["r_big"], bal["r_small"], bal["b_big"], bal["b_small"]))

        # 三、盈亏结算
        L.append("\n## 三、盈亏结算\n")
        if settled:
            for rec in settled:
                draw_str = "前区 %s 后区 %s" % (
                    " ".join("%02d" % d for d in rec["draw_reds"]),
                    " ".join("%02d" % d for d in rec["draw_blues"]))
                if rec["win_notes"] > 0:
                    tag = "🎯 命中%d注" % rec["win_notes"] + ("（含浮动奖池）" if rec["float_win"] else "")
                else:
                    tag = "0命中"
                L.append("- %s 期（目标%s）：%s｜成本%d元｜奖金%d元｜**日盈亏 %+d元**\n" % (
                    rec["draw_issue"], rec["target_issue"], tag, rec["cost"],
                    rec["prize"], rec["daily_pnl"]))
        else:
            L.append("- 今日无待结算记录（尚无历史选号或目标开奖未出）。\n")
        L.append("\n### 累计盈亏\n")
        L.append("- 已结算 %d 轮｜%d 注｜成本 %d 元｜奖金 %d 元｜**净盈亏 %+d 元**｜待结算 %d 轮\n" % (
            summary["rounds"], summary["total_notes"], summary["total_cost"],
            summary["total_prize"], summary["net_pnl"], summary["pending_rounds"]))

        # 四、今日推荐
        L.append("\n## 四、今日推荐（%d 注，押 %s 期）\n" % (n_notes, target))
        for i, n in enumerate(notes, 1):
            L.append("%d. %s\n" % (i, _fmt_note(n)))

        L.append("\n---\n*本报告仅供学习研究，不构成投注建议。生成时间 %s*\n" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(L)
        return path
    except Exception as e:
        return "⚠️ 报告写入失败：%s" % e


# ---------- 主流程 ----------
def run_daily(today=None, n_notes=None):
    """
    执行一次每日复盘+结算+选号。
    返回汇总 dict（供 unified_review 汇总）；写入 per-variety 报告。
    """
    today = today or date.today().isoformat()
    n_notes = n_notes or config.NOTES
    records, meta = fetch_history(config.WINDOW)
    if not records:
        return {"game": "dlt", "today": today, "error": "未获取到历史数据", "notes": []}

    st = load_state()
    # 1) 结算
    settled = _settle(st, records)
    # 2) 选号（同日幂等：今日已有记录则跳过）
    today_rec = None
    for r in st["records"]:
        if r.get("date") == today:
            today_rec = r
            break
    if today_rec is not None:
        notes = today_rec["notes"]
        target = today_rec["target_issue"]
        bal = {"r_odd": 0, "r_even": 0, "r_big": 0, "r_small": 0,
               "b_odd": 0, "b_even": 0, "b_big": 0, "b_small": 0}
        print("  [dlt] 今日(%s)记录已存在，跳过重复选号（幂等）" % today)
    else:
        today_rec, notes, bal, target = _select_new(today, records, n_notes)
        st["records"].append(today_rec)

    _calc_summary(st)
    save_state(st)

    yest_draw = _find_draw_by_date(records, _yesterday())
    report_path = _write_report(today, records, meta, notes, bal, n_notes,
                                settled, st["summary"], target, yest_draw)

    # 打印选号明细（便于日志查看）
    print("  大乐透 推荐 %d 注（押 %s 期）：" % (len(notes), target))
    for i, n in enumerate(notes, 1):
        print("    %2d. %s" % (i, _fmt_note(n)))

    return {
        "game": "dlt",
        "name": "大乐透",
        "today": today,
        "meta": meta,
        "latest_issue": latest(records).get("issue"),
        "yesterday_draw": yest_draw,
        "settled": [
            {"draw_issue": r["draw_issue"], "target_issue": r["target_issue"],
             "win_notes": r["win_notes"], "float_win": r["float_win"],
             "prize": r["prize"], "cost": r["cost"], "daily_pnl": r["daily_pnl"]}
            for r in settled
        ],
        "summary": st["summary"],
        "notes": notes,
        "target": target,
        "report_path": report_path,
    }
