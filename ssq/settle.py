# -*- coding: utf-8 -*-
"""
双色球 结算与盈亏模块
-------------------
维护 data/ssq_state.json：记录每期选号(目标期号)及结算状态。
建议每日 07:00 运行一次，流程同 dlt/settle.py（规则参考大乐透）。
  双色球：红球 1-33 选 6 不重复 + 蓝球 1-16 选 1；开奖日：周二 / 周四 / 周日。
奖级：使用 _ssq_tier 判定，固定奖金额取自 SSQ_PRIZE。
一等奖/二等奖为浮动奖池，本模块记为「浮动奖(奖池)」且不计入 PnL（保守）。
"""
import os
import json
from datetime import date, datetime, timedelta

from . import config
from .fetcher import fetch_history
from .analysis import load_history, hot_cold, latest
from .selector import generate_notes, ENGINE_VERSION

STATE_FILE = os.path.join(config.BASE_DIR, "data", "ssq_state.json")
COST_PER_NOTE = 2  # 每注基本投注金额（元）

# ---- 双色球奖级（固定奖部分）----
SSQ_PRIZE = {3: 3000, 4: 200, 5: 10, 6: 5}


def _ssq_tier(red_match, blue_match):
    """双色球奖级判定：传入(命中红球数, 命中蓝球数)。"""
    if red_match == 6 and blue_match == 1:
        return 1
    if red_match == 6 and blue_match == 0:
        return 2
    if red_match == 5 and blue_match == 1:
        return 3
    if (red_match == 5 and blue_match == 0) or (red_match == 4 and blue_match == 1):
        return 4
    if (red_match == 4 and blue_match == 0) or (red_match == 3 and blue_match == 1):
        return 5
    if (red_match in (0, 1, 2) and blue_match == 1):
        return 6
    return 0


# ---------- 状态读写 ----------
def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                st = json.load(f)
            st.setdefault("records", [])
            st.setdefault("summary", _empty_summary())
            st.setdefault("portfolio", [])
            st.setdefault("last_rotation_date", None)
            return st
        except Exception:
            pass
    return {"game": "ssq", "records": [], "portfolio": [], "last_rotation_date": None,
            "summary": _empty_summary()}


def save_state(st: dict):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)


def _empty_summary():
    return {
        "rounds": 0,
        "total_notes": 0,
        "total_cost": 0,
        "total_prize": 0,
        "net_pnl": 0,
        "total_win_notes": 0,
        "pending_rounds": 0,
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
    return "红球 %s  蓝球 %s" % (reds, blues)


# ---------- 结算 ----------
def _settle(st: dict, history: list):
    if not history:
        return []
    latest_issue = int(history[0]["issue"])
    settled = []
    for rec in st["records"]:
        if rec.get("status") != "pending":
            continue
        tgt = int(rec["target_issue"])
        if tgt > latest_issue:
            continue
        draw = None
        for h in history:
            if int(h["issue"]) == tgt:
                draw = h
                break
        if draw is None:
            continue
        total_prize = 0
        win_notes = 0
        float_win = False
        best_tier = 0
        for note in rec["notes"]:
            rm = len(set(note["reds"]) & set(draw["reds"]))
            bm = len(set(note["blues"]) & set(draw["blues"]))
            tier = _ssq_tier(rm, bm)
            if tier == 0:
                continue
            prize = SSQ_PRIZE.get(tier)
            if prize is None:
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


# ---------- 组合（portfolio）管理 ----------
# 轮换锚点：首次轮换日 = 2026-08-14（周五），之后每14天（每2周周五）轮换一次
ROTATION_ANCHOR = date(2026, 8, 14)

def _is_rotation_day(d):
    """每2周的周五轮换：以 2026-08-14 为锚点，每14天一次。"""
    if d.weekday() != 4:  # Monday=0 ... Friday=4
        return False
    diff = (d - ROTATION_ANCHOR).days
    return diff >= 0 and diff % 14 == 0


def _note_key(note):
    return (tuple(note["reds"]), tuple(note["blues"]))


def _balance_of(notes):
    """根据一组注计算奇偶/大小均衡统计（用于报告展示）。"""
    totals = {"r_odd": 0, "r_even": 0, "r_big": 0, "r_small": 0,
              "b_odd": 0, "b_even": 0, "b_big": 0, "b_small": 0}
    for n in notes:
        for d in n["reds"]:
            totals["r_odd"] += (d % 2 == 1)
            totals["r_even"] += (d % 2 == 0)
            totals["r_big"] += (d >= config.RED_BIG_THRESHOLD)
            totals["r_small"] += (d < config.RED_BIG_THRESHOLD)
        for d in n["blues"]:
            totals["b_odd"] += (d % 2 == 1)
            totals["b_even"] += (d % 2 == 0)
            totals["b_big"] += (d >= config.BLUE_BIG_THRESHOLD)
            totals["b_small"] += (d < config.BLUE_BIG_THRESHOLD)
    return totals


def _note_coldness(note, red_om, blue_om):
    """一注的冷度：其红/蓝号码的遗漏之和（越大越冷）。"""
    return (sum(red_om.get(d, config.WINDOW) for d in note["reds"])
            + sum(blue_om.get(d, config.WINDOW) for d in note["blues"]))


def _rotate_portfolio(portfolio, records, n_notes, n_replace):
    """轮换最冷的 n_replace 组：用遗漏和度量冷度，替换最冷的若干组为全新生成号。"""
    hc = hot_cold(records, config.WINDOW)
    red_om = hc["red_omission"]
    blue_om = hc["blue_omission"]
    scored = []
    for i, note in enumerate(portfolio):
        scored.append((_note_coldness(note, red_om, blue_om), i))
    scored.sort(key=lambda x: -x[0])  # 冷度降序（最冷在前）
    replace_idx = set(i for _, i in scored[:n_replace])
    remaining = [portfolio[i] for i in range(len(portfolio)) if i not in replace_idx]
    existing_keys = set(_note_key(n) for n in remaining)
    fresh, _ = generate_notes(records, n_replace)
    final_new = []
    for n in fresh:
        k = _note_key(n)
        if k not in existing_keys:
            final_new.append(n)
            existing_keys.add(k)
    guard = 0
    while len(final_new) < n_replace and guard < n_replace * 40:
        guard += 1
        extra, _ = generate_notes(records, 1)
        k = _note_key(extra[0])
        if k not in existing_keys:
            final_new.append(extra[0])
            existing_keys.add(k)
    new_map = {idx: n for idx, n in zip(sorted(replace_idx), final_new)}
    new_portfolio = []
    for i, note in enumerate(portfolio):
        new_portfolio.append(new_map.get(i, note))
    return new_portfolio


def _make_pending(today, target, portfolio):
    return {
        "date": today,
        "target_issue": target,
        "notes": portfolio,
        "cost": len(portfolio) * COST_PER_NOTE,
        "status": "pending",
        "draw_issue": None, "draw_date": "", "draw_reds": None, "draw_blues": None,
        "win_notes": 0, "best_tier": 0, "float_win": False,
        "prize": 0, "daily_pnl": None,
    }


# ---------- 报告 ----------
def _write_report(today, history, meta, notes, bal, n_notes, settled, summary, target, yest_draw, rotation_info=""):
    try:
        os.makedirs(config.REPORT_DIR, exist_ok=True)
        path = os.path.join(config.REPORT_DIR, "ssq_%s.md" % today)
        L = []
        src = "实时抓取(500彩票网)" if not meta.get("fallback") else "本地缓存(抓取失败回退)"
        last = latest(history)
        L.append("# 双色球 每日复盘 %s\n" % today)
        L.append("> 数据源：%s｜最新 %s｜窗口 %d 期\n" % (src, last.get("issue", "?"), meta.get("count", 0)))
        L.append("\n> ⚠️ **性质声明**：本报告中的号码均为程序随机采样生成，**等同机选，不具备预测能力**。\n")
        L.append("> 开奖完全随机、每期独立，不存在可推算的下期号码；任何声称能预测中奖号码者均属诈骗。\n")
        L.append("> 本报告仅供学习研究与盈亏记录，不构成投注建议。\n")

        L.append("\n## 一、昨日数据摘要\n")
        if yest_draw:
            L.append("- 昨日(%s)开奖：**%s 期** 红球 %s 蓝球 %s\n" % (
                yest_draw.get("date", ""), yest_draw["issue"],
                " ".join("%02d" % d for d in yest_draw["reds"]),
                " ".join("%02d" % d for d in yest_draw["blues"])))
        else:
            L.append("- 昨日(%s) **无双色球开奖**（开奖日：周二 / 周四 / 周日）。\n" % _yesterday())
        if last:
            L.append("- 最新一期：%s 期 红球 %s 蓝球 %s（%s）\n" % (
                last.get("issue"), " ".join("%02d" % d for d in last["reds"]),
                " ".join("%02d" % d for d in last["blues"]), last.get("date", "")))

        L.append("\n## 二、复盘结论\n")
        hc = hot_cold(history, config.WINDOW)
        L.append("- 红球热号：%s；红球冷号(高遗漏)：%s\n" % (
            " ".join("%02d" % d for d in hc["hot_red"]),
            " ".join("%02d" % d for d in hc["cold_red"])))
        L.append("- 蓝球热号：%s；蓝球冷号(高遗漏)：%s\n" % (
            " ".join("%02d" % d for d in hc["hot_blue"]),
            " ".join("%02d" % d for d in hc["cold_blue"])))
        # v3 热号追号：本期锁定的核心号
        try:
            from hot_core import get_ssq_core
            _core, _meta = get_ssq_core(history)
            L.append("- 🎯 本期热号核心（每注红球必含，%s 锁定，每月1号重选）：**%s**\n" % (
                _meta.get("ym", ""), " / ".join("%02d" % d for d in _core)))
        except Exception:
            pass
        L.append("- 本期采样奇偶均衡：红球 奇%d/偶%d，蓝球 奇%d/偶%d（目标≈50:50）。\n" % (
            bal["r_odd"], bal["r_even"], bal["b_odd"], bal["b_even"]))
        L.append("- 本期采样大小均衡：红球 大%d/小%d，蓝球 大%d/小%d。\n" % (
            bal["r_big"], bal["r_small"], bal["b_big"], bal["b_small"]))

        L.append("\n## 三、盈亏结算\n")
        if settled:
            for rec in settled:
                draw_str = "红球 %s 蓝球 %s" % (
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

        L.append("\n## 四、今日随机采样（%d 注，押 %s 期）｜等同机选·无预测力【选号引擎 %s】\n" % (len(notes), target, ENGINE_VERSION))
        L.append("> ⚠️ 以下号码为程序随机采样生成，**与机选在统计上无区别，不具备预测能力**。\n")
        L.append("> 开奖完全随机、每期独立；任何声称能预测中奖号码的人或平台均为诈骗。本节仅供学习研究与盈亏记录。\n")
        if rotation_info:
            L.append("> 🔄 %s（组合每2周周五轮换最冷2组，轮换前保持持有）\n" % rotation_info)
        else:
            L.append("> 当前持有组合：非轮换日保持不变，每2周周五自动替换最冷的2组。\n")
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
    组合(portfolio)持久化持有：每2周周五替换最冷的2组；非开奖日不重复堆积 pending。
    返回汇总 dict（供 unified_review 汇总）；写入 per-variety 报告。
    """
    today = today or date.today().isoformat()
    n_notes = n_notes or config.NOTES
    records, meta = fetch_history(config.WINDOW)
    if not records:
        return {"game": "ssq", "today": today, "error": "未获取到历史数据", "notes": []}

    st = load_state()
    # 1) 结算（按目标期号，pending -> settled）
    settled = _settle(st, records)

    # 2) 轮换检查（每2周周五，且今日尚未轮换过）
    today_date = date.fromisoformat(today)
    rotation_happened = False
    rotation_note = ""
    if _is_rotation_day(today_date) and st.get("last_rotation_date") != today:
        portfolio = st.get("portfolio") or []
        if len(portfolio) >= n_notes:
            portfolio = _rotate_portfolio(portfolio, records, n_notes, 2)
            rotation_note = "本期为每2周周五轮换日：已替换最冷的2组"
        else:
            portfolio = generate_notes(records, n_notes)[0]
            rotation_note = "本期为轮换日但组合不足，已重建%d组" % n_notes
        st["portfolio"] = portfolio
        st["last_rotation_date"] = today
        rotation_happened = True

    # 3) 确保组合存在（首跑或非轮换日但组合为空）
    portfolio = st.get("portfolio") or []
    if not portfolio:
        portfolio = generate_notes(records, n_notes)[0]
        st["portfolio"] = portfolio

    # 3.5) v3 热号追号：核心号校验
    #      - 核心号跨月重选 → 重建组合（让新规则立即生效，不必等轮换日）
    #      - 持仓中存在不含核心号的注 → 重建
    rebuild_happened = False
    try:
        from hot_core import get_ssq_core
        core, _meta = get_ssq_core(records)
        core_set = set(core)
        need = False
        if st.get("core_ym") != _meta.get("ym"):
            need = True
        elif portfolio and not all(core_set <= set(n["reds"]) for n in portfolio):
            need = True
        if need:
            portfolio = generate_notes(records, n_notes)[0]
            st["portfolio"] = portfolio
            st["core_ym"] = _meta.get("ym")
            rebuild_happened = True
            _msg = "热号追号·核心号%s，已重建%d组" % (
                "/".join("%02d" % d for d in core), n_notes)
            rotation_note = (rotation_note + "；" + _msg) if rotation_note else _msg
    except Exception:
        pass

    # 4) 每个待开奖期仅保留一条 pending（按 target_issue 幂等，避免非开奖日重复堆积导致重复结算）
    latest_issue = int(records[0]["issue"])
    next_target = str(latest_issue + 1)
    existing = None
    for r in st["records"]:
        if r.get("status") == "pending" and r.get("target_issue") == next_target:
            existing = r
            break
    if existing is not None:
        if rotation_happened or rebuild_happened:
            existing["notes"] = portfolio  # 组合变更当日，pending 跟随最新组合
        notes = existing["notes"]
        target = existing["target_issue"]
    else:
        st["records"].append(_make_pending(today, next_target, portfolio))
        notes = portfolio
        target = next_target

    bal = _balance_of(notes)
    _calc_summary(st)
    save_state(st)

    yest_draw = _find_draw_by_date(records, _yesterday())
    report_path = _write_report(today, records, meta, notes, bal, n_notes,
                                settled, st["summary"], target, yest_draw,
                                rotation_info=rotation_note)

    # 走势研判（透传给统一报告，避免被压缩丢失）
    hc = hot_cold(records, config.WINDOW)
    trend = {
        "hot_red": " ".join("%02d" % d for d in hc["hot_red"]),
        "cold_red": " ".join("%02d" % d for d in hc["cold_red"]),
        "hot_blue": " ".join("%02d" % d for d in hc["hot_blue"]),
        "cold_blue": " ".join("%02d" % d for d in hc["cold_blue"]),
        "bal": bal,
    }

    print("  双色球 随机采样(等同机选) %d 注（押 %s 期）：" % (len(notes), target))
    for i, n in enumerate(notes, 1):
        print("    %2d. %s" % (i, _fmt_note(n)))

    return {
        "game": "ssq",
        "name": "双色球",
        "today": today,
        "meta": meta,
        "latest_issue": latest(records).get("issue"),
        "yesterday_draw": yest_draw,
        "rotation": rotation_note,
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
        "trend": trend,
    }
