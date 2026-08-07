# -*- coding: utf-8 -*-
"""
彩票每日复盘（统一编排器）
------------------------
每日 07:00 运行：
  1) 福彩3D 复盘 + 结算 + 选号 (daily_review.main)：每天10组组六，组六连出>6期熔断暂停
  2) 大乐透 结算 + 选号 (dlt.settle.run_daily)：5组组合持有，每2周周五轮换最冷2组
  3) 双色球 结算 + 选号 (ssq.settle.run_daily)：5组组合持有，每2周周五轮换最冷2组
汇总三品种「昨日数据摘要 / 复盘结论 / 具体盈亏」，写 unified_YYYY-MM-DD.md，
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

REPORT_DIR = os.path.join(ROOT, "data", "reports")
PL_FILE = os.path.join(ROOT, "data", "profit_loss.json")


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


def build_summary():
    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")

    print("\n########## [1/3] 福彩3D 复盘 ##########")
    r3 = daily_review.main()
    print("\n########## [2/3] 大乐透 复盘 ##########")
    rd = dlt_run()
    print("\n########## [3/3] 双色球 复盘 ##########")
    rs = ssq_run()

    return today, yesterday, r3, rd, rs


def wechat_block(today, yesterday, r3, rd, rs):
    lines = []
    lines.append("【微信推送摘要】")
    lines.append("📊 彩票每日复盘 %s（福彩3D + 大乐透 + 双色球）" % today)
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
    if s3set:
        lines.append("结算：押%s(%s) %d命中，奖金%d元，日盈亏%+d元" % (
            s3set["draw_qihao"], _fmt_3d_nums(s3set["draw_nums"]),
            s3set["hits"], s3set["prize"], s3set["daily_pnl"]))
    else:
        lines.append("结算：昨日无新开奖/无待结算")
    s3 = r3["summary"]
    cb = r3.get("circuit", {})
    lines.append("复盘：%s" % ("；".join(cb.get("rules_fired", [])) if cb.get("rules_fired") else "常态推荐"))
    lines.append("累计净盈亏：%+d元（%d命中/%d注）" % (s3["net_pnl"], s3["total_hits"], s3["total_bets"]))
    recs3 = r3.get("recommendations", [])
    if recs3:
        lines.append("今日推荐：%d注%s（押%s）" % (len(recs3), cb.get("push_type", "组六"), r3.get("next_qihao")))
        lines.append("  " + " / ".join(_fmt_3d_nums(r["nums"]) for r in recs3[:5]) + (" ..." if len(recs3) > 5 else ""))
    else:
        lines.append("今日推荐：休市/熔断，0注")

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
    if sd:
        for x in sd:
            lines.append("结算：%s期 → %d命中，奖金%d元，日盈亏%+d元" % (
                x["draw_issue"], x["win_notes"], x["prize"], x["daily_pnl"]))
    else:
        lines.append("结算：今日无待结算（待%s期开奖）" % rd.get("target"))
    s_d = rd["summary"]
    rot_d = rd.get("rotation")
    lines.append("复盘：5组持有·每2周周五轮换最冷2组" + ("；" + rot_d if rot_d else "；热号为主+冷号补足，奇偶/大小均衡"))
    lines.append("累计净盈亏：%+d元（已结算%d轮，待结算%d轮）" % (
        s_d["net_pnl"], s_d["rounds"], s_d["pending_rounds"]))
    nd = rd.get("notes", [])
    if nd:
        lines.append("今日推荐：%d注（押%s期）" % (len(nd), rd.get("target")))
        lines.append("  " + " / ".join(_fmt_dlt(n) for n in nd[:3]) + (" ..." if len(nd) > 3 else ""))
        if rd.get("rotation"):
            lines.append("  🔄 %s" % rd["rotation"])
    else:
        lines.append("今日推荐：无")

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
    if ss:
        for x in ss:
            lines.append("结算：%s期 → %d命中，奖金%d元，日盈亏%+d元" % (
                x["draw_issue"], x["win_notes"], x["prize"], x["daily_pnl"]))
    else:
        lines.append("结算：今日无待结算（待%s期开奖）" % rs.get("target"))
    s_s = rs["summary"]
    rot_s = rs.get("rotation")
    lines.append("复盘：5组持有·每2周周五轮换最冷2组" + ("；" + rot_s if rot_s else "；热号为主+冷号补足，奇偶/大小均衡"))
    lines.append("累计净盈亏：%+d元（已结算%d轮，待结算%d轮）" % (
        s_s["net_pnl"], s_s["rounds"], s_s["pending_rounds"]))
    ns = rs.get("notes", [])
    if ns:
        lines.append("今日推荐：%d注（押%s期）" % (len(ns), rs.get("target")))
        lines.append("  " + " / ".join(_fmt_ssq(n) for n in ns[:3]) + (" ..." if len(ns) > 3 else ""))
        if rs.get("rotation"):
            lines.append("  🔄 %s" % rs["rotation"])
    else:
        lines.append("今日推荐：无")

    # ===== 合计 =====
    total = s3["net_pnl"] + s_d["net_pnl"] + s_s["net_pnl"]
    lines.append("")
    lines.append("━━ 🧾 三品种合计 ━━")
    lines.append("累计净盈亏合计：%+d元（福彩3D %+d + 大乐透 %+d + 双色球 %+d）" % (
        total, s3["net_pnl"], s_d["net_pnl"], s_s["net_pnl"]))
    lines.append("⚠️ 仅供学习研究，不构成投注建议。彩票为负EV，理性购彩。")
    return "\n".join(lines)


def write_unified_report(today, yesterday, r3, rd, rs, wechat):
    os.makedirs(REPORT_DIR, exist_ok=True)
    path = os.path.join(REPORT_DIR, "unified_%s.md" % today)
    s3 = r3["summary"]
    s_d = rd["summary"]
    s_s = rs["summary"]
    total = s3["net_pnl"] + s_d["net_pnl"] + s_s["net_pnl"]
    s3set = _resolve_3d_settlement(r3)

    L = []
    L.append("# 彩票每日复盘（统一）%s\n" % today)
    L.append("> 前一自然日：%s\n" % yesterday)

    L.append("\n## 福彩3D\n")
    L.append("- 昨日开奖：%s %s（%s）\n" % (
        r3["yesterday_draw"]["qihao"] if r3.get("yesterday_draw") else "—",
        _fmt_3d_nums(r3["yesterday_draw"]["nums"]) if r3.get("yesterday_draw") else "",
        r3["yesterday_draw"]["type"] if r3.get("yesterday_draw") else ""))
    if s3set:
        L.append("- 结算：押%s(%s) %d命中，日盈亏%+d元\n" % (
            s3set["draw_qihao"], _fmt_3d_nums(s3set["draw_nums"]), s3set["hits"], s3set["daily_pnl"]))
    L.append("- 累计净盈亏：%+d元（%d命中/%d注）\n" % (s3["net_pnl"], s3["total_hits"], s3["total_bets"]))

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

    L.append("\n## 三品种合计\n")
    L.append("- 累计净盈亏合计：**%+d元**\n" % total)

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
    return ym, {"3D": (pnl3, bets3, hits3), "dlt": (pnl_d, r_d), "ssq": (pnl_s, r_s)}


def write_monthly_report():
    ym, det = _monthly_pnl()
    path = os.path.join(REPORT_DIR, "%s-monthly.md" % ym)
    p3, b3, h3 = det["3D"]
    p_d, r_d = det["dlt"]
    p_s, r_s = det["ssq"]
    total = p3 + p_d + p_s
    L = []
    L.append("# 彩票月度盈亏报告 %s\n" % ym)
    L.append("\n## 福彩3D\n")
    L.append("- 净盈亏：**%+d元**（%d注/%d命中）\n" % (p3, b3, h3))
    L.append("\n## 大乐透\n")
    L.append("- 净盈亏：**%+d元**（已结算%d轮）\n" % (p_d, r_d))
    L.append("\n## 双色球\n")
    L.append("- 净盈亏：**%+d元**（已结算%d轮）\n" % (p_s, r_s))
    L.append("\n## 三品种合计\n")
    L.append("- 月度净盈亏合计：**%+d元**\n" % total)
    L.append("\n---\n*本报告由每日复盘自动化于次月1号汇总生成。仅供学习研究，不构成投注建议。*\n")
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(L)
    return path, ym, total


def main():
    today, yesterday, r3, rd, rs = build_summary()
    wechat = wechat_block(today, yesterday, r3, rd, rs)
    report_path = write_unified_report(today, yesterday, r3, rd, rs, wechat)
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
