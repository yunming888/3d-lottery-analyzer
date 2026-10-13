# -*- coding: utf-8 -*-
"""
七乐彩 结算与盈亏模块
-------------------
维护 data/qlc_state.json：记录每期选号(目标期号)及结算状态。
流程与 dlt/ssq/settle.py 完全一致：
  1) 抓取最新历史（含最近一次开奖）
  2) 结算 pending 记录（目标期号 <= 最新期号 的开奖）
  3) 选新号，目标 = 最新期号 + 1（跨年自动进位）
  4) 写 per-variety 报告 + 返回汇总
  5) 同日幂等 + 跨进程锁 + 原子写 + 损坏即停（审计修复）

七乐彩规则要点：
  - 每周一/三/五开奖（每周 3 期）；非开奖日不新增注（target 不变 → 复用已有 pending）
  - 每期 5 注 × 2 元 = 10 元/期 → 每周 30 元
  - 奖级：一/二/三等为浮动奖（记为「浮动奖」不计 PnL，保守）；四等 200、五等 50、
    六等 10、七等 5 为固定奖
  - 中奖判定：基本号码匹配个数 + 是否命中特别号码（特别号仅参与二/四/六等奖）
"""
import os
import json
from datetime import date, datetime, timedelta

from . import config
from .fetcher import fetch_history
from .analysis import load_history, hot_cold, latest
from .selector import generate_notes, ENGINE_VERSION
import period_util
from atomic_io import save_json_atomic, load_json_checked, file_lock
from alerts import ALERTS

STATE_FILE = os.path.join(config.BASE_DIR, "data", "qlc_state.json")
COST_PER_NOTE = 2  # 每注基本投注金额（元）

# ---- 七乐彩奖级（固定奖部分；一/二/三等为浮动奖池）----
QLC_PRIZE = {4: 200, 5: 50, 6: 10, 7: 5}


def _qlc_tier(basic_match, special_hit):
    """七乐彩奖级判定：传入(基本号码命中数, 是否命中特别号码)。

    官方规则：特别号码只参与二、四、六等奖的判定。
      一等：7个基本号全中
      二等：6个基本号 + 特别号
      三等：6个基本号
      四等：5个基本号 + 特别号      (200元)
      五等：5个基本号                (50元)
      六等：4个基本号 + 特别号      (10元)
      七等：4个基本号                (5元)
    """
    if basic_match == 7:
        return 1
    if basic_match == 6 and special_hit:
        return 2
    if basic_match == 6:
        return 3
    if basic_match == 5 and special_hit:
        return 4
    if basic_match == 5:
        return 5
    if basic_match == 4 and special_hit:
        return 6
    if basic_match == 4:
        return 7
    return 0


# ---------- 状态读写 ----------
def load_state() -> dict:
    """读取状态。损坏时备份为 *.corrupt-<ts> 并抛 RuntimeError，绝不静默清空。"""
    if os.path.exists(STATE_FILE):
        st = load_json_checked(STATE_FILE)
        st.setdefault("records", [])
        st.setdefault("summary", _empty_summary())
        st.setdefault("portfolio", [])
        st.setdefault("last_rotation_date", None)
        st.setdefault("core_ym", None)
        return st
    return {"game": "qlc", "records": [], "portfolio": [], "last_rotation_date": None,
            "core_ym": None, "summary": _empty_summary()}


def save_state(st: dict):
    save_json_atomic(STATE_FILE, st)


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
    basics = " ".join("%02d" % d for d in note["reds"])
    special = " ".join("%02d" % d for d in note.get("blues", []))
    return "基本号 %s  特别号 %s" % (basics, special)


# ---------- 结算 ----------
def _settle(st: dict, history: list):
    """结算 pending。防双计：target 已有 settled 记录的重复 pending 标记跳过。"""
    if not history:
        return []
    latest_issue = int(history[0]["issue"])
    settled_targets = set()
    for rec in st["records"]:
        if rec.get("status") == "settled" and rec.get("target_issue") is not None:
            try:
                settled_targets.add(int(rec["target_issue"]))
            except (TypeError, ValueError):
                pass
    settled = []
    for rec in st["records"]:
        if rec.get("status") != "pending":
            continue
        tgt = int(rec["target_issue"])
        if tgt in settled_targets:
            rec["status"] = "skipped_duplicate"
            rec["_settle_note"] = "重复pending(已有同target已结算记录)，跳过以防奖金/成本双计"
            ALERTS.add("WARN", "七乐彩",
                       "期号 %s 出现重复 pending，已跳过第二条（防双计）" % tgt)
            continue
        if tgt > latest_issue:
            continue  # 目标开奖尚未发生
        draw = None
        for h in history:
            if int(h["issue"]) == tgt:
                draw = h
                break
        if draw is None:
            continue  # 缺少该期开奖数据，暂缓
        draw_basic = set(draw["reds"])
        draw_special = set(draw.get("blues", []))
        total_prize = 0
        win_notes = 0
        float_win = False
        best_tier = 0
        for note in rec["notes"]:
            bm = len(set(note["reds"]) & draw_basic)
            sh = bool(set(note.get("blues", [])) & draw_special)
            tier = _qlc_tier(bm, sh)
            if tier == 0:
                continue
            prize = QLC_PRIZE.get(tier)
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
        rec["draw_blues"] = draw.get("blues", [])
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
# 轮换锚点：与 dlt/ssq 一致（2026-08-14 周五），之后每 14 天一次（周五是七乐彩开奖日）
ROTATION_ANCHOR = date(2026, 8, 14)


def _is_rotation_day(d):
    """每2周的周五轮换（与 dlt/ssq 同锚点）。"""
    if d.weekday() != 4:  # Monday=0 ... Friday=4
        return False
    diff = (d - ROTATION_ANCHOR).days
    return diff >= 0 and diff % 14 == 0


def _is_draw_day(d):
    """七乐彩开奖日：周一 / 周三 / 周五。"""
    return d.weekday() in config.DRAW_DOWS


def _note_key(note):
    return (tuple(note["reds"]), tuple(note.get("blues", [])))


def _balance_of(notes):
    """一组注的奇偶/大小均衡统计（用于报告展示）。"""
    totals = {"r_odd": 0, "r_even": 0, "r_big": 0, "r_small": 0,
              "b_odd": 0, "b_even": 0, "b_big": 0, "b_small": 0}
    big = config.BASIC_BIG_THRESHOLD
    for n in notes:
        for d in n["reds"]:
            totals["r_odd"] += (d % 2 == 1)
            totals["r_even"] += (d % 2 == 0)
            totals["r_big"] += (d >= big)
            totals["r_small"] += (d < big)
        for d in n.get("blues", []):
            totals["b_odd"] += (d % 2 == 1)
            totals["b_even"] += (d % 2 == 0)
            totals["b_big"] += (d >= big)
            totals["b_small"] += (d < big)
    return totals


def _note_coldness(note, red_om):
    """一注的冷度：其基本号码的遗漏之和（特别号不计入轮换冷度）。"""
    return sum(red_om.get(d, config.WINDOW) for d in note["reds"])


def _rotate_portfolio(portfolio, records, n_notes, n_replace):
    """轮换最冷的 n_replace 组。返回 (新组合, 告警或None)。"""
    hc = hot_cold(records, config.WINDOW)
    red_om = hc["red_omission"]
    scored = []
    for i, note in enumerate(portfolio):
        scored.append((_note_coldness(note, red_om), i))
    scored.sort(key=lambda x: -x[0])
    replace_idx = set(i for _, i in scored[:n_replace])
    existing_keys = set(_note_key(n) for n in portfolio)
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
        if not extra:
            continue
        k = _note_key(extra[0])
        if k not in existing_keys:
            final_new.append(extra[0])
            existing_keys.add(k)
    warn = None
    if len(final_new) < n_replace:
        warn = "轮换新注不足(%d/%d组)，保留原组合补位" % (len(final_new), n_replace)
        ALERTS.add("WARN", "七乐彩", warn)
    new_map = {idx: n for idx, n in zip(sorted(replace_idx), final_new)}
    new_portfolio = []
    for i, note in enumerate(portfolio):
        new_portfolio.append(new_map.get(i, note))
    return new_portfolio, warn


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
        path = os.path.join(config.REPORT_DIR, "qlc_%s.md" % today)
        L = []
        src = "实时抓取(huiniao镜像)" if not meta.get("fallback") else "本地缓存(抓取失败回退)"
        last = latest(history)
        L.append("# 七乐彩 每日复盘 %s\n" % today)
        L.append("> 数据源：%s｜最新 %s｜窗口 %d 期\n" % (src, last.get("issue", "?"), meta.get("count", 0)))
        L.append("\n> ⚠️ **性质声明**：本报告中的号码均为程序随机采样生成，**等同机选，不具备预测能力**。\n")
        L.append("> 开奖完全随机、每期独立，不存在可推算的下期号码；任何声称能预测中奖号码者均属诈骗。\n")
        L.append("> 本报告仅供学习研究与盈亏记录，不构成投注建议。\n")

        L.append("\n## 一、昨日数据摘要\n")
        if yest_draw:
            L.append("- 昨日(%s)开奖：**%s 期** 基本号 %s 特别号 %s\n" % (
                yest_draw.get("date", ""), yest_draw["issue"],
                " ".join("%02d" % d for d in yest_draw["reds"]),
                " ".join("%02d" % d for d in yest_draw.get("blues", []))))
        else:
            L.append("- 昨日(%s) **无七乐彩开奖**（开奖日：周一 / 周三 / 周五）。\n" % _yesterday())
        if last:
            L.append("- 最新一期：%s 期 基本号 %s 特别号 %s（%s）\n" % (
                last.get("issue"), " ".join("%02d" % d for d in last["reds"]),
                " ".join("%02d" % d for d in last.get("blues", [])), last.get("date", "")))

        L.append("\n## 二、复盘结论\n")
        hc = hot_cold(history, config.WINDOW)
        L.append("- 基本号热号：%s；基本号冷号(高遗漏)：%s\n" % (
            " ".join("%02d" % d for d in hc["hot_red"]),
            " ".join("%02d" % d for d in hc["cold_red"])))
        L.append("- 特别号热号：%s\n" % " ".join("%02d" % d for d in hc["hot_blue"]))
        try:
            from hot_core import get_qlc_core, is_active
            if not is_active():
                raise ValueError("未到生效日")
            _core, _cmeta = get_qlc_core(history)
            L.append("- 🎯 本期热号核心（每注基本号必含，%s 锁定，每月1号重选）：**%s**\n" % (
                _cmeta.get("ym", ""), " / ".join("%02d" % d for d in _core)))
        except Exception:
            pass
        L.append("- 本期采样奇偶均衡：基本号 奇%d/偶%d（目标 3:4 或 4:3）。\n" % (
            bal["r_odd"], bal["r_even"]))
        L.append("- 本期采样大小均衡：基本号(16起为大号) 大%d/小%d。\n" % (
            bal["r_big"], bal["r_small"]))

        L.append("\n## 三、盈亏结算\n")
        if settled:
            for rec in settled:
                draw_str = "基本号 %s 特别号 %s" % (
                    " ".join("%02d" % d for d in rec["draw_reds"]),
                    " ".join("%02d" % d for d in rec["draw_blues"]))
                tag = "🎯 命中%d注" % rec["win_notes"] if rec["win_notes"] > 0 else "0命中"
                if rec["win_notes"] > 0 and rec["float_win"]:
                    tag += "（含浮动奖池）"
                L.append("- %s 期（目标%s）：%s｜成本%d元｜奖金%d元｜**日盈亏 %+d元**\n" % (
                    rec["draw_issue"], rec["target_issue"], tag, rec["cost"],
                    rec["prize"], rec["daily_pnl"]))
        else:
            L.append("- 今日无待结算记录（尚无历史选号或目标开奖未出）。\n")
        L.append("\n### 累计盈亏\n")
        L.append("- 已结算 %d 轮｜%d 注｜成本 %d 元｜奖金 %d 元｜**净盈亏 %+d 元**｜待结算 %d 轮\n" % (
            summary["rounds"], summary["total_notes"], summary["total_cost"],
            summary["total_prize"], summary["net_pnl"], summary["pending_rounds"]))

        L.append("\n## 四、今日随机采样（%d 注，押 %s 期）｜等同机选·无预测力【选号引擎 %s】\n" % (
            len(notes), target, ENGINE_VERSION))
        L.append("> ⚠️ 以下号码为程序随机采样生成，**与机选在统计上无区别，不具备预测能力**。\n")
        L.append("> 每注一等奖概率恒为 1/2,035,800；返奖率 50%，长期期望为负。\n")
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
    组合(portfolio)持久化持有：每2周周五替换最冷的2组。
    非开奖日（周二/四/六）latest_issue 不变 → target 不变 → 复用已有 pending，不新增注。
    """
    today = today or date.today().isoformat()
    n_notes = n_notes or config.NOTES
    records, meta = fetch_history(config.WINDOW)
    if not records:
        ALERTS.add("ERROR", "七乐彩", "未获取到历史数据（抓取失败且无缓存）")
        return {"game": "qlc", "name": "七乐彩", "today": today, "failed": True,
                "error": "未获取到历史数据", "notes": [], "target": None,
                "latest_issue": None, "yesterday_draw": None, "settled": [],
                "rotation": None, "trend": None, "meta": {},
                "summary": _empty_summary()}

    with file_lock(STATE_FILE):
        st = load_state()
        # 1) 结算
        settled = _settle(st, records)

        # 2) 轮换检查（每2周周五，且今日尚未轮换过）
        today_date = date.fromisoformat(today)
        rotation_happened = False
        rotation_note = ""
        rotation_warn = None
        if _is_rotation_day(today_date) and st.get("last_rotation_date") != today:
            portfolio = st.get("portfolio") or []
            if len(portfolio) >= n_notes:
                portfolio, rotation_warn = _rotate_portfolio(portfolio, records, n_notes, 2)
                rotation_note = "本期为每2周周五轮换日：已替换最冷的2组"
            else:
                portfolio = generate_notes(records, n_notes)[0]
                rotation_note = "本期为轮换日但组合不足，已重建%d组" % n_notes
            st["portfolio"] = portfolio
            st["last_rotation_date"] = today
            rotation_happened = True
            if rotation_warn:
                rotation_note = rotation_note + "；⚠️" + rotation_warn

        # 3) 确保组合存在
        portfolio = st.get("portfolio") or []
        if not portfolio:
            portfolio = generate_notes(records, n_notes)[0]
            st["portfolio"] = portfolio

        # 3.5) v3 热号追号：核心号校验（跨月重选 / 持仓缺核心号 → 重建）
        rebuild_happened = False
        try:
            from hot_core import get_qlc_core, is_active
            if not is_active():
                raise ValueError("未到生效日，跳过核心号校验")
            core, _meta = get_qlc_core(records)
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
        except Exception as _e:
            ALERTS.add("WARN", "七乐彩", "核心号校验跳过/失败：%s" % _e)

        # 4) 每个待开奖期仅保留一条 pending（按 target_issue 幂等）
        latest_issue = int(records[0]["issue"])
        # 跨年期号修复：跨年自动进位（2026155 → 2027001）
        next_target = period_util.next_qlc_qihao(str(latest_issue), records[0].get("date"))
        # 数据源滞后守卫：不给已开奖期号重复建仓
        stale_reuse = False
        _max_target = 0
        for _r in st["records"]:
            try:
                _max_target = max(_max_target, int(_r.get("target_issue") or 0))
            except (TypeError, ValueError):
                pass
        if int(next_target) < _max_target:
            stale_reuse = True
            next_target = str(_max_target)
            ALERTS.add("WARN", "七乐彩",
                       "数据源滞后：最新期 %s 推算目标 %s < 已挂 %s，复用已有 pending，未新增注"
                       % (latest_issue, _max_target, _max_target))
        existing = None
        for r in st["records"]:
            if r.get("status") == "pending" and r.get("target_issue") == next_target:
                existing = r
                break
        if existing is not None:
            if (rotation_happened or rebuild_happened) and not stale_reuse:
                existing["notes"] = portfolio
                existing["cost"] = len(existing["notes"]) * COST_PER_NOTE
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

    # 走势研判
    hc = hot_cold(records, config.WINDOW)
    trend = {
        "hot_red": " ".join("%02d" % d for d in hc["hot_red"]),
        "cold_red": " ".join("%02d" % d for d in hc["cold_red"]),
        "hot_blue": " ".join("%02d" % d for d in hc["hot_blue"]),
        "cold_blue": " ".join("%02d" % d for d in hc["cold_blue"]),
        "bal": bal,
    }

    print("  七乐彩 随机采样(等同机选) %d 注（押 %s 期）：" % (len(notes), target))
    for i, n in enumerate(notes, 1):
        print("    %2d. %s" % (i, _fmt_note(n)))

    return {
        "game": "qlc",
        "name": "七乐彩",
        "today": today,
        "meta": meta,
        "stale_reuse": stale_reuse,
        "warnings": [m for _, s, m, _t in ALERTS.items if s == "七乐彩"],
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
