# -*- coding: utf-8 -*-
"""
彩票每日复盘（统一编排器）
------------------------
每日 07:00 运行：
  1) 福彩3D 复盘 + 结算 + 选号 (daily_review.main)：钟摆直选（钟摆引擎 v2，多窗口融合，动态~12注）；组六玩法与组六熔断已移除
  2) 大乐透 结算 + 选号 (dlt.settle.run_daily)：5组组合持有，每2周周五轮换最冷2组
  3) 双色球 结算 + 选号 (ssq.settle.run_daily)：5组组合持有，每2周周五轮换最冷2组
  4) 七乐彩 结算 + 选号 (qlc.settle.run_daily)：30选7+特别号，开奖日 周一/三/五，5组持有
汇总四品种「昨日数据摘要 / 复盘结论 / 具体盈亏」，写 unified_YYYY-MM-DD.md，
并打印唯一【微信推送摘要】供自动化抓取推送。
每月1号额外生成上月月度盈亏报告（替代已删除的月度盈亏自动化）。

用法: python unified_review.py
"""
import os
import sys
import json
from datetime import date, datetime, timedelta

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import daily_review
from dlt.settle import run_daily as dlt_run
from ssq.settle import run_daily as ssq_run
from qlc.settle import run_daily as qlc_run
from alerts import ALERTS
from analyze import ENGINE_VERSION as FCD_VERSION
from dlt.selector import ENGINE_VERSION as DLT_VERSION
from ssq.selector import ENGINE_VERSION as SSQ_VERSION
from qlc.selector import ENGINE_VERSION as QLC_VERSION

REPORT_DIR = os.path.join(ROOT, "data", "reports")
PL_FILE = os.path.join(ROOT, "data", "profit_loss.json")

# 热号核心号说明后缀：热号追号仅为投注结构偏好，不改变每注中奖概率（红线配套）
HOT_NOTE = "（热号仅为投注结构偏好，不改变每注中奖概率）"


def _fmt_3d_nums(nums):
    return " ".join(map(str, nums))


def _fmt_dlt(note):
    return "前区 %s  后区 %s" % (
        " ".join("%02d" % d for d in note["reds"]),
        " ".join("%02d" % d for d in note["blues"]))


def _fmt_ssq(note):
    return "红球 %s  蓝球 %s" % (
        " ".join("%02d" % d for d in note["reds"]),
        " ".join("%02d" % d for d in note["blues"]))


def _fmt_qlc(note):
    return "基本号 %s  特别号 %s" % (
        " ".join("%02d" % d for d in note["reds"]),
        " ".join("%02d" % d for d in note.get("blues", [])))


def _resolve_3d_settlement(r3):
    """返回规范化的 3D 昨日结算 dict；若本次未结算(已结算过)，则回查 profit_loss.json。"""
    st = r3.get("settlement")
    if st:
        rec, draw, hits, hit_list = st
        return {
            "draw_qihao": draw["qihao"], "draw_nums": draw["nums"], "draw_type": draw["type"],
            "hits": hits, "prize": rec["prize"], "daily_pnl": rec["daily_pnl"],
        }
    yd = r3.get("yesterday_draw")
    if not yd:
        return None
    try:
        with open(PL_FILE, encoding="utf-8") as f:
            pl = json.load(f)
    except Exception:
        return None
    for rec in pl["records"]:
        if rec.get("draw") == yd["qihao"] and rec.get("hits") is not None:
            return {
                "draw_qihao": rec["draw"], "draw_nums": rec.get("draw_nums", []),
                "draw_type": rec.get("draw_type", ""), "hits": rec["hits"],
                "prize": rec.get("prize", 0), "daily_pnl": rec.get("daily_pnl", 0),
            }
    return None


def _err(name):
    """品种运行失败时的占位结果：语义明确为"运行失败"，绝不复用"无待结算"（审计 P1-1）。
    带全 wechat_block / write_unified_report 所需键。"""
    return {"game": name, "failed": True, "today": date.today().isoformat(),
            "yesterday_draw": None, "settlement": None, "settled": [],
            "recommendations": [], "notes": [], "rotation": None, "trend": None,
            "latest_issue": None, "target": None,
            "summary": {"net_pnl": 0, "total_hits": 0, "total_bets": 0,
                        "rounds": 0, "pending_rounds": 0}}


def _stage(name, fn):
    """阶段化执行：单品种异常不再拖垮全局——旧版任一品种抛异常 → 整脚本非零退出，
    统一报告与微信摘要全部消失，形成"静默失联"（审计 P1-1）。"""
    try:
        return fn()
    except Exception as e:
        import traceback
        print("  ❌ %s 运行失败：%s: %s" % (name, type(e).__name__, e))
        traceback.print_exc()
        ALERTS.add("ERROR", name, "运行失败：%s: %s" % (type(e).__name__, e))
        return _err(name)


def build_summary():
    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")

    print("\n########## [1/4] 福彩3D 复盘 ##########")
    r3 = _stage("福彩3D", daily_review.main)
    print("\n########## [2/4] 大乐透 复盘 ##########")
    rd = _stage("大乐透", dlt_run)
    print("\n########## [3/4] 双色球 复盘 ##########")
    rs = _stage("双色球", ssq_run)
    print("\n########## [4/4] 七乐彩 复盘 ##########")
    rq = _stage("七乐彩", qlc_run)

    return today, yesterday, r3, rd, rs, rq


def wechat_block(today, yesterday, r3, rd, rs, rq):
    lines = []
    lines.append("【微信推送摘要】")
    lines.append("📊 彩票每日复盘 %s（福彩3D + 大乐透 + 双色球 + 七乐彩）" % today)
    lines.append("（前一自然日：%s）" % yesterday)

    # ===== 福彩3D =====
    lines.append("")
    lines.append("━━ 🎯 福彩3D ━━")
    y3 = r3.get("yesterday_draw")
    if y3:
        lines.append("昨日开奖：%s = %s（%s）" % (
            y3["qihao"], _fmt_3d_nums(y3["nums"]), y3["type"]))
    else:
        lines.append("昨日(%s)：无开奖（每日开奖）" % yesterday)
    s3set = _resolve_3d_settlement(r3)
    if r3.get("failed"):
        lines.append("结算：⚠️ 本品种运行失败，无法结算")
    elif s3set:
        lines.append("结算：押%s(%s) %d命中，奖金%d元，日盈亏%+d元" % (
            s3set["draw_qihao"], _fmt_3d_nums(s3set["draw_nums"]),
            s3set["hits"], s3set["prize"], s3set["daily_pnl"]))
    else:
        lines.append("结算：昨日无新开奖/无待结算")
    s3 = r3["summary"]
    cb = r3.get("circuit", {})
    lines.append("复盘：%s" % ("；".join(cb.get("rules_fired", [])) if cb.get("rules_fired") else "常态出号"))
    lines.append("累计净盈亏：%+d元（%d命中/%d注）" % (s3["net_pnl"], s3["total_hits"], s3["total_bets"]))
    try:
        import hot_core
        if "钟摆" in FCD_VERSION:
            # 钟摆引擎候选来自多窗口分区域融合，不锁月内热号，
            # 此处置不展示"每注必含热号"以免误导（与 v2 实际出号口径不一致）
            lines.append("选号依据：钟摆多窗口融合·分区域回摆评分（仅投注结构偏好，无预测力）")
        elif hot_core.is_active():
            _c3p = hot_core.peek("3d_pos")
            if _c3p and _c3p.get("pos"):
                _pos = _c3p["pos"]
                lines.append("热号核心：直选定位·百%s十%s个%s（每注必含，%s 锁定，每月1号重选）%s" % (
                    "/".join(str(x) for x in _pos.get("bai", [])),
                    "/".join(str(x) for x in _pos.get("shi", [])),
                    "/".join(str(x) for x in _pos.get("ge", [])), _c3p.get("ym", ""), HOT_NOTE))
    except Exception:
        pass
    recs3 = r3.get("recommendations", [])
    _3d_label = "钟摆直选" if "钟摆" in FCD_VERSION else "直选定位"
    if recs3:
        lines.append("今日随机采样：%d注%s（押%s）｜等同机选·无预测力【选号引擎 %s】" % (len(recs3), _3d_label, r3.get("next_qihao"), FCD_VERSION))
        for i, r in enumerate(recs3, 1):
            lines.append("  %d. %s" % (i, _fmt_3d_nums(r["nums"])))
    elif r3.get("failed"):
        lines.append("今日随机采样：⚠️ 运行失败，0注")
    else:
        lines.append("今日随机采样：休市/暂停，0注")

    tr = r3.get("trend") or {}
    if tr.get("conclusion"):
        lines.append("走势研判：%s" % tr["conclusion"])

    # ===== 大乐透 =====
    lines.append("")
    lines.append("━━ 🎲 大乐透 ━━")
    yd = rd.get("yesterday_draw")
    if yd:
        lines.append("昨日开奖：%s 前区 %s 后区 %s" % (
            yd["issue"], " ".join("%02d" % d for d in yd["reds"]),
            " ".join("%02d" % d for d in yd["blues"])))
    else:
        lines.append("昨日(%s)：无开奖（开奖日 周一/三/六）｜最新 %s 期" % (yesterday, rd.get("latest_issue")))
    sd = rd.get("settled") or []
    if rd.get("failed"):
        lines.append("结算：⚠️ 本品种运行失败，无法结算")
    elif sd:
        for x in sd:
            lines.append("结算：%s期 → %d命中，奖金%d元，日盈亏%+d元" % (
                x["draw_issue"], x["win_notes"], x["prize"], x["daily_pnl"]))
    else:
        lines.append("结算：今日无待结算（待%s期开奖）" % rd.get("target"))
    s_d = rd["summary"]
    rot_d = rd.get("rotation")
    lines.append("复盘：5组持有·每2周周五轮换最冷2组" + ("；" + rot_d if rot_d else "；热号为主+冷号补足，奇偶/大小均衡"))
    try:
        import hot_core
        _cd = hot_core.peek("dlt") if hot_core.is_active() else None
        if _cd:
            lines.append("热号核心：前区 %s（每注必含，%s 锁定，每月1号重选）%s" % (
                " / ".join("%02d" % d for d in _cd["core_red"]), _cd.get("ym", ""), HOT_NOTE))
    except Exception:
        pass
    lines.append("累计净盈亏：%+d元（已结算%d轮，待结算%d轮）" % (
        s_d["net_pnl"], s_d["rounds"], s_d["pending_rounds"]))
    nd = rd.get("notes", [])
    if nd:
        lines.append("今日随机采样：%d注（押%s期）｜等同机选·无预测力【选号引擎 %s】" % (len(nd), rd.get("target"), DLT_VERSION))
        for _i, n in enumerate(nd, 1):
            lines.append("  %d. %s" % (_i, _fmt_dlt(n)))
        if rd.get("rotation"):
            lines.append("  🔄 %s" % rd["rotation"])
    elif rd.get("failed"):
        lines.append("今日随机采样：⚠️ 运行失败，无")
    else:
        lines.append("今日随机采样：无")
    tr_d = rd.get("trend") or {}
    if tr_d:
        b_d = tr_d.get("bal", {})
        lines.append("走势研判：热号 前区[%s]/后区[%s]；冷号 前区[%s]/后区[%s]" % (
            tr_d.get("hot_red", ""), tr_d.get("hot_blue", ""),
            tr_d.get("cold_red", ""), tr_d.get("cold_blue", "")))
        lines.append("  采样均衡：前区奇%d/偶%d、大%d/小%d；后区奇%d/偶%d、大%d/小%d" % (
            b_d.get("r_odd", 0), b_d.get("r_even", 0), b_d.get("r_big", 0), b_d.get("r_small", 0),
            b_d.get("b_odd", 0), b_d.get("b_even", 0), b_d.get("b_big", 0), b_d.get("b_small", 0)))

    # ===== 双色球 =====
    lines.append("")
    lines.append("━━ 🔴 双色球 ━━")
    ys = rs.get("yesterday_draw")
    if ys:
        lines.append("昨日开奖：%s 红球 %s 蓝球 %s" % (
            ys["issue"], " ".join("%02d" % d for d in ys["reds"]),
            " ".join("%02d" % d for d in ys["blues"])))
    else:
        lines.append("昨日(%s)：无开奖（开奖日 周二/四/日）｜最新 %s 期" % (yesterday, rs.get("latest_issue")))
    ss = rs.get("settled") or []
    if rs.get("failed"):
        lines.append("结算：⚠️ 本品种运行失败，无法结算")
    elif ss:
        for x in ss:
            lines.append("结算：%s期 → %d命中，奖金%d元，日盈亏%+d元" % (
                x["draw_issue"], x["win_notes"], x["prize"], x["daily_pnl"]))
    else:
        lines.append("结算：今日无待结算（待%s期开奖）" % rs.get("target"))
    s_s = rs["summary"]
    rot_s = rs.get("rotation")
    lines.append("复盘：5组持有·每2周周五轮换最冷2组" + ("；" + rot_s if rot_s else "；热号为主+冷号补足，奇偶/大小均衡"))
    try:
        import hot_core
        _cs = hot_core.peek("ssq") if hot_core.is_active() else None
        if _cs:
            lines.append("热号核心：红球 %s（每注必含，%s 锁定，每月1号重选）%s" % (
                " / ".join("%02d" % d for d in _cs["core_red"]), _cs.get("ym", ""), HOT_NOTE))
    except Exception:
        pass
    lines.append("累计净盈亏：%+d元（已结算%d轮，待结算%d轮）" % (
        s_s["net_pnl"], s_s["rounds"], s_s["pending_rounds"]))
    ns = rs.get("notes", [])
    if ns:
        lines.append("今日随机采样：%d注（押%s期）｜等同机选·无预测力【选号引擎 %s】" % (len(ns), rs.get("target"), SSQ_VERSION))
        for _i, n in enumerate(ns, 1):
            lines.append("  %d. %s" % (_i, _fmt_ssq(n)))
        if rs.get("rotation"):
            lines.append("  🔄 %s" % rs["rotation"])
    elif rs.get("failed"):
        lines.append("今日随机采样：⚠️ 运行失败，无")
    else:
        lines.append("今日随机采样：无")
    tr_s = rs.get("trend") or {}
    if tr_s:
        b_s = tr_s.get("bal", {})
        lines.append("走势研判：热号 红球[%s]/蓝球[%s]；冷号 红球[%s]/蓝球[%s]" % (
            tr_s.get("hot_red", ""), tr_s.get("hot_blue", ""),
            tr_s.get("cold_red", ""), tr_s.get("cold_blue", "")))
        lines.append("  采样均衡：红球奇%d/偶%d、大%d/小%d；蓝球奇%d/偶%d、大%d/小%d" % (
            b_s.get("r_odd", 0), b_s.get("r_even", 0), b_s.get("r_big", 0), b_s.get("r_small", 0),
            b_s.get("b_odd", 0), b_s.get("b_even", 0), b_s.get("b_big", 0), b_s.get("b_small", 0)))

    # ===== 七乐彩 =====
    lines.append("")
    lines.append("━━ 🎱 七乐彩 ━━")
    yq = rq.get("yesterday_draw")
    if yq:
        lines.append("昨日开奖：%s 基本号 %s 特别号 %s" % (
            yq["issue"], " ".join("%02d" % d for d in yq["reds"]),
            " ".join("%02d" % d for d in yq.get("blues", []))))
    else:
        lines.append("昨日(%s)：无开奖（开奖日 周一/三/五）｜最新 %s 期" % (yesterday, rq.get("latest_issue")))
    sq_ = rq.get("settled") or []
    if rq.get("failed"):
        lines.append("结算：⚠️ 本品种运行失败，无法结算")
    elif sq_:
        for x in sq_:
            lines.append("结算：%s期 → %d命中，奖金%d元，日盈亏%+d元" % (
                x["draw_issue"], x["win_notes"], x["prize"], x["daily_pnl"]))
    else:
        lines.append("结算：今日无待结算（待%s期开奖）" % rq.get("target"))
    s_q = rq["summary"]
    rot_q = rq.get("rotation")
    lines.append("复盘：每周一/三/五开奖·5组持有·每2周周五轮换最冷2组" + ("；" + rot_q if rot_q else "；热号为主+冷号补足，奇偶/大小均衡"))
    try:
        import hot_core
        _cq = hot_core.peek("qlc") if hot_core.is_active() else None
        if _cq:
            lines.append("热号核心：基本号 %s（每注必含，%s 锁定，每月1号重选）%s" % (
                " / ".join("%02d" % d for d in _cq["core_red"]), _cq.get("ym", ""), HOT_NOTE))
    except Exception:
        pass
    lines.append("累计净盈亏：%+d元（已结算%d轮，待结算%d轮）" % (
        s_q["net_pnl"], s_q["rounds"], s_q["pending_rounds"]))
    nq = rq.get("notes", [])
    if nq:
        lines.append("今日随机采样：%d注（押%s期）｜等同机选·无预测力【选号引擎 %s】" % (len(nq), rq.get("target"), QLC_VERSION))
        for _i, n in enumerate(nq, 1):
            lines.append("  %d. %s" % (_i, _fmt_qlc(n)))
        if rq.get("rotation"):
            lines.append("  🔄 %s" % rq["rotation"])
    elif rq.get("failed"):
        lines.append("今日随机采样：⚠️ 运行失败，无")
    else:
        lines.append("今日随机采样：无")
    tr_q = rq.get("trend") or {}
    if tr_q:
        b_q = tr_q.get("bal", {})
        lines.append("走势研判：热号 基本号[%s]/特别号[%s]；冷号 基本号[%s]" % (
            tr_q.get("hot_red", ""), tr_q.get("hot_blue", ""), tr_q.get("cold_red", "")))
        lines.append("  采样均衡：基本号奇%d/偶%d、大%d/小%d" % (
            b_q.get("r_odd", 0), b_q.get("r_even", 0), b_q.get("r_big", 0), b_q.get("r_small", 0)))

    # ===== 合计 =====
    total = s3["net_pnl"] + s_d["net_pnl"] + s_s["net_pnl"] + s_q["net_pnl"]
    lines.append("")
    lines.append("━━ 🧾 四品种合计 ━━")
    lines.append("累计净盈亏合计：%+d元（福彩3D %+d + 大乐透 %+d + 双色球 %+d + 七乐彩 %+d）" % (
        total, s3["net_pnl"], s_d["net_pnl"], s_s["net_pnl"], s_q["net_pnl"]))
    _failed = [g.get("name") or g.get("game") for g in (r3, rd, rs, rq) if g.get("failed")]
    if _failed:
        lines.append("⚠️ 本日失败品种：%s（其数据未计入合计，合计偏低）" % "、".join(_failed))
    try:
        import hot_core
        lines.append("ℹ️ %s" % hot_core.effective_desc())
    except Exception:
        pass
    lines += ALERTS.render()   # 运行告警（审计 A2/A5）：数据源回退/核心号异常/失败品种等
    lines.append("⚠️ 上述号码均为随机采样，等同机选、无预测力；开奖随机且每期独立，不存在可推算的下期号码。")
    lines.append("⚠️ 仅供学习研究，不构成投注建议；任何收费荐号均属诈骗，切勿转账。彩票为负EV，理性购彩。")
    return "\n".join(lines)


def write_unified_report(today, yesterday, r3, rd, rs, rq, wechat):
    os.makedirs(REPORT_DIR, exist_ok=True)
    path = os.path.join(REPORT_DIR, "unified_%s.md" % today)
    s3 = r3["summary"]
    s_d = rd["summary"]
    s_s = rs["summary"]
    s_q = rq["summary"]
    total = s3["net_pnl"] + s_d["net_pnl"] + s_s["net_pnl"] + s_q["net_pnl"]
    s3set = _resolve_3d_settlement(r3)

    L = []
    L.append("# 彩票每日复盘（统一）%s\n" % today)
    L.append("> 前一自然日：%s\n" % yesterday)
    L.append("\n> ⚠️ **性质声明**：本报告中的号码均为程序按历史分布随机采样生成，**等同投注站机选，不具备预测能力**。\n")
    L.append("> 彩票开奖完全随机、每期独立，不存在可推算的下期号码；任何声称能预测或推荐中奖号码的个人、平台或 AI 均属诈骗。\n")
    L.append("> 本报告仅供学习研究与盈亏记录，不构成投注建议。\n")

    L.append("\n## 福彩3D\n")
    L.append("- 昨日开奖：%s %s（%s）\n" % (
        r3["yesterday_draw"]["qihao"] if r3.get("yesterday_draw") else "—",
        _fmt_3d_nums(r3["yesterday_draw"]["nums"]) if r3.get("yesterday_draw") else "",
        r3["yesterday_draw"]["type"] if r3.get("yesterday_draw") else ""))
    if s3set:
        L.append("- 结算：押%s(%s) %d命中，日盈亏%+d元\n" % (
            s3set["draw_qihao"], _fmt_3d_nums(s3set["draw_nums"]), s3set["hits"], s3set["daily_pnl"]))
    L.append("- 累计净盈亏：%+d元（%d命中/%d注）\n" % (s3["net_pnl"], s3["total_hits"], s3["total_bets"]))
    tr = r3.get("trend") or {}
    if tr.get("conclusion"):
        L.append("- 100期走势研判：%s\n" % tr["conclusion"])

    L.append("\n## 大乐透\n")
    if rd.get("yesterday_draw"):
        yd = rd["yesterday_draw"]
        L.append("- 昨日开奖：%s 前区 %s 后区 %s\n" % (
            yd["issue"], " ".join("%02d" % d for d in yd["reds"]), " ".join("%02d" % d for d in yd["blues"])))
    else:
        L.append("- 昨日：无开奖（开奖日 周一/三/六）｜最新 %s 期\n" % rd.get("latest_issue"))
    for x in (rd.get("settled") or []):
        L.append("- 结算：%s期 → %d命中，日盈亏%+d元\n" % (x["draw_issue"], x["win_notes"], x["daily_pnl"]))
    L.append("- 累计净盈亏：%+d元（已结算%d轮，待结算%d轮）\n" % (s_d["net_pnl"], s_d["rounds"], s_d["pending_rounds"]))
    tr_d = rd.get("trend") or {}
    if tr_d:
        b_d = tr_d.get("bal", {})
        L.append("- 走势研判：热号 前区[%s]/后区[%s]；冷号 前区[%s]/后区[%s]\n" % (
            tr_d.get("hot_red", ""), tr_d.get("hot_blue", ""),
            tr_d.get("cold_red", ""), tr_d.get("cold_blue", "")))
        L.append("- 选号均衡：前区奇%d/偶%d、大%d/小%d；后区奇%d/偶%d、大%d/小%d\n" % (
            b_d.get("r_odd", 0), b_d.get("r_even", 0), b_d.get("r_big", 0), b_d.get("r_small", 0),
            b_d.get("b_odd", 0), b_d.get("b_even", 0), b_d.get("b_big", 0), b_d.get("b_small", 0)))
    _nd = rd.get("notes", [])
    if _nd:
        L.append("- 今日随机采样（押%s期，%d注）｜等同机选·无预测力【选号引擎 %s】：\n" % (rd.get("target"), len(_nd), DLT_VERSION))
        for n in _nd:
            L.append("  - %s\n" % _fmt_dlt(n))

    L.append("\n## 双色球\n")
    if rs.get("yesterday_draw"):
        ys = rs["yesterday_draw"]
        L.append("- 昨日开奖：%s 红球 %s 蓝球 %s\n" % (
            ys["issue"], " ".join("%02d" % d for d in ys["reds"]), " ".join("%02d" % d for d in ys["blues"])))
    else:
        L.append("- 昨日：无开奖（开奖日 周二/四/日）｜最新 %s 期\n" % rs.get("latest_issue"))
    for x in (rs.get("settled") or []):
        L.append("- 结算：%s期 → %d命中，日盈亏%+d元\n" % (x["draw_issue"], x["win_notes"], x["daily_pnl"]))
    L.append("- 累计净盈亏：%+d元（已结算%d轮，待结算%d轮）\n" % (s_s["net_pnl"], s_s["rounds"], s_s["pending_rounds"]))
    tr_s = rs.get("trend") or {}
    if tr_s:
        b_s = tr_s.get("bal", {})
        L.append("- 走势研判：热号 红球[%s]/蓝球[%s]；冷号 红球[%s]/蓝球[%s]\n" % (
            tr_s.get("hot_red", ""), tr_s.get("hot_blue", ""),
            tr_s.get("cold_red", ""), tr_s.get("cold_blue", "")))
        L.append("- 选号均衡：红球奇%d/偶%d、大%d/小%d；蓝球奇%d/偶%d、大%d/小%d\n" % (
            b_s.get("r_odd", 0), b_s.get("r_even", 0), b_s.get("r_big", 0), b_s.get("r_small", 0),
            b_s.get("b_odd", 0), b_s.get("b_even", 0), b_s.get("b_big", 0), b_s.get("b_small", 0)))
    _ns = rs.get("notes", [])
    if _ns:
        L.append("- 今日随机采样（押%s期，%d注）｜等同机选·无预测力【选号引擎 %s】：\n" % (rs.get("target"), len(_ns), SSQ_VERSION))
        for n in _ns:
            L.append("  - %s\n" % _fmt_ssq(n))

    L.append("\n## 七乐彩\n")
    if rq.get("yesterday_draw"):
        yq = rq["yesterday_draw"]
        L.append("- 昨日开奖：%s 基本号 %s 特别号 %s\n" % (
            yq["issue"], " ".join("%02d" % d for d in yq["reds"]),
            " ".join("%02d" % d for d in yq.get("blues", []))))
    else:
        L.append("- 昨日：无开奖（开奖日 周一/三/五）｜最新 %s 期\n" % rq.get("latest_issue"))
    for x in (rq.get("settled") or []):
        L.append("- 结算：%s期 → %d命中，日盈亏%+d元\n" % (x["draw_issue"], x["win_notes"], x["daily_pnl"]))
    L.append("- 累计净盈亏：%+d元（已结算%d轮，待结算%d轮）\n" % (s_q["net_pnl"], s_q["rounds"], s_q["pending_rounds"]))
    _nq = rq.get("notes", [])
    if _nq:
        L.append("- 今日随机采样（押%s期，%d注）｜等同机选·无预测力【选号引擎 %s】：\n" % (rq.get("target"), len(_nq), QLC_VERSION))
        for n in _nq:
            L.append("  - %s\n" % _fmt_qlc(n))

    L.append("\n## 四品种合计\n")
    L.append("- 累计净盈亏合计：**%+d元**（3D %+d / 大乐透 %+d / 双色球 %+d / 七乐彩 %+d）\n" % (
        total, s3["net_pnl"], s_d["net_pnl"], s_s["net_pnl"], s_q["net_pnl"]))

    L.append("\n---\n*生成时间 %s*\n" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    L.append("\n## 微信推送摘要\n\n```\n%s\n```\n" % wechat)
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(L)
    return path


def _monthly_pnl():
    """聚合上月三品种盈亏，返回 (ym, details)。"""
    today_d = date.today()
    first = today_d.replace(day=1)
    prev_month = first - timedelta(days=1)
    ym = prev_month.strftime("%Y-%m")

    # 福彩3D：按建仓日期归属月份
    pnl3 = bets3 = hits3 = 0
    try:
        with open(PL_FILE, encoding="utf-8") as f:
            pl = json.load(f)
        for rec in pl["records"]:
            if rec.get("date", "").startswith(ym) and rec.get("hits") is not None:
                pnl3 += rec.get("daily_pnl", 0) or 0
                bets3 += rec.get("notes", 0)
                hits3 += rec.get("hits", 0)
    except Exception:
        pass

    def _agg_state(path):
        pnl = rounds = 0
        try:
            with open(path, encoding="utf-8") as f:
                st = json.load(f)
            for rec in st.get("records", []):
                if rec.get("status") == "settled" and str(rec.get("draw_date", "")).startswith(ym):
                    pnl += rec.get("daily_pnl", 0) or 0
                    rounds += 1
        except Exception:
            pass
        return pnl, rounds

    pnl_d, r_d = _agg_state(os.path.join(ROOT, "data", "dlt_state.json"))
    pnl_s, r_s = _agg_state(os.path.join(ROOT, "data", "ssq_state.json"))
    pnl_q, r_q = _agg_state(os.path.join(ROOT, "data", "qlc_state.json"))
    return ym, {"3D": (pnl3, bets3, hits3), "dlt": (pnl_d, r_d),
                "ssq": (pnl_s, r_s), "qlc": (pnl_q, r_q)}


def write_monthly_report():
    ym, det = _monthly_pnl()
    path = os.path.join(REPORT_DIR, "%s-monthly.md" % ym)
    p3, b3, h3 = det["3D"]
    p_d, r_d = det["dlt"]
    p_s, r_s = det["ssq"]
    p_q, r_q = det["qlc"]
    total = p3 + p_d + p_s + p_q
    L = []
    L.append("# 彩票月度盈亏报告 %s\n" % ym)
    L.append("\n## 福彩3D\n")
    L.append("- 净盈亏：**%+d元**（%d注/%d命中）\n" % (p3, b3, h3))
    L.append("\n## 大乐透\n")
    L.append("- 净盈亏：**%+d元**（已结算%d轮）\n" % (p_d, r_d))
    L.append("\n## 双色球\n")
    L.append("- 净盈亏：**%+d元**（已结算%d轮）\n" % (p_s, r_s))
    L.append("\n## 七乐彩\n")
    L.append("- 净盈亏：**%+d元**（已结算%d轮）\n" % (p_q, r_q))
    L.append("\n## 四品种合计\n")
    L.append("- 月度净盈亏合计：**%+d元**\n" % total)
    L.append("\n---\n*本报告由每日复盘自动化于次月1号汇总生成。仅供学习研究，不构成投注建议。*\n")
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(L)
    return path, ym, total


def main():
    today, yesterday, r3, rd, rs, rq = build_summary()
    wechat = wechat_block(today, yesterday, r3, rd, rs, rq)
    report_path = write_unified_report(today, yesterday, r3, rd, rs, rq, wechat)
    print("\n" + "=" * 60)
    print(wechat)
    print("=" * 60)
    print("\n📄 统一报告：%s" % report_path)

    # 每月1号额外生成上月月度盈亏报告
    if date.today().day == 1:
        try:
            mpath, mym, mtotal = write_monthly_report()
            print("📅 月度盈亏报告：%s（%s 净盈亏 %+d元）" % (mpath, mym, mtotal))
        except Exception as e:
            print("⚠️ 月度报告生成失败：%s" % e)


if __name__ == "__main__":
    main()
