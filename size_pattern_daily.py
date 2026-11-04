# -*- coding: utf-8 -*-
"""
福彩3D「大小形态两组」出号模块（2026-11-05 起生效）
=====================================================
云明 2026-11-04 指令链：
  ①「明天开始，3d就按昨天的来，加两组按大小形态的号码，并每天复盘」
  ②「并入 3D 主台账一起算」→ **本模块不再维护独立台账、不再单独结算**。

设计原则（重要，勿回退）：
  1) 本模块只负责**生成两组号码**，由 `daily_review.py` 把 16 注追加进
     `generate_recommendations()` 返回的 recs，写进 `profit_loss.json` **同一条记录**：
     notes = 12(钟摆) + 16(大小形态) = 28 注，cost = 56 元/天。
     结算由 `settle_pending()` 遍历整条 recommendations 完成，累计盈亏由
     `calc_summary()` 自动合并 —— 不搞跨模块写回、不产生第二份台账。
  2) 两组形态固定：A「大大小」、B「大小小」（沿用 2026-11-02 那两组）。
     每天按各位该侧近 100 期频率 TOP2 重算数字，各 8 注。
     复用 `position_pattern.build_notes`，规则与 11-02 完全一致。
  3) 结算口径（由主台账执行）：**直选精确命中** 1040 元/注；
     组选集合相同不算中奖（组六玩法已于 2026-09-28 移除）。
  4) `EFFECTIVE_FROM = 2026-11-05`，生效前 `build_extra_notes()` 返回 []，
     保证「明天开始」，今天重跑主链路也不会提前加注。
  5) 口径变更日 **2026-11-05**：此前 3D 每日 12 注/24 元，此后 28 注/56 元。
     历史 139 条记录不改写，回测/统计切勿把前后两段混用。

⚠️ 出号性质红线（勿删、勿回退）：
  所有号码一律称「随机采样」，等同投注站机选、无预测力；
  开奖随机且每期独立，不存在可推算的下期号码；声称能预测或收费荐号者均属诈骗；
  仅供学习研究，不构成投注建议。禁止出现「推荐/预测/荐号」字样。
  形态只决定钱花在哪一块，命中率恒 = 注数/1000，直选单注 0.1%、ROI 52%。

用法（只读，不写任何状态文件）：
  python size_pattern_daily.py --dry-run --date 2026-11-05   # 打印两组号码
  python size_pattern_daily.py --selftest                     # 校验注数/形态/生效日
"""
import os
import sys
import argparse
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import position_pattern as pp
from trading_day import is_trading_day

DATA_DIR = os.path.join(ROOT, "data")
HIST = os.path.join(DATA_DIR, "3d_history.json")

ENGINE_VERSION = "大小形态v1"
EFFECTIVE_FROM = "2026-11-05"          # 云明指令「明天开始」
GROUP_PATTERNS = (("A", "大大小"), ("B", "大小小"))
PER_POS = (2, 2, 2)                    # 各位候选数 → 2×2×2 = 8 注/组
NOTES_PER_GROUP = 8
TOTAL_NOTES = 16
COST_PER_NOTE = 2
WINDOW_FREQ = 100                      # 频率统计窗口

DISCLAIMER = (
    "⚠️ 本节号码均为程序按历史分布随机采样生成，等同投注站机选、无预测力；"
    "开奖随机且每期独立，不存在可推算的下期号码；任何声称能预测或收费荐号者均属诈骗。"
    "仅供学习研究，不构成投注建议。"
)


def is_active(today=None):
    today = today or datetime.now().strftime("%Y-%m-%d")
    return today >= EFFECTIVE_FROM


def _normalize(history):
    """统一为升序、且必含 bai/shi/ge（position_pattern.build_notes 依赖）。"""
    out = []
    for r in history or []:
        d = dict(r)
        if "bai" not in d and d.get("nums"):
            d["bai"], d["shi"], d["ge"] = d["nums"][0], d["nums"][1], d["nums"][2]
        out.append(d)
    out.sort(key=lambda x: x["qihao"])
    return out


def gen_groups(history, today=None):
    """返回 {"A": {"pattern","notes"}, "B": {...}}；未生效/休市/数据不足返回 {}。"""
    today = today or datetime.now().strftime("%Y-%m-%d")
    if not is_active(today):
        return {}
    try:
        if not is_trading_day(datetime.strptime(today, "%Y-%m-%d").date()):
            return {}
    except ValueError:
        return {}
    recs = _normalize(history)
    if len(recs) < 30:
        return {}
    out = {}
    for key, pat in GROUP_PATTERNS:
        nt = pp.build_notes(None, PER_POS, recs, WINDOW_FREQ, pat)
        notes = [list(n) for n in nt["notes"]]
        if len(notes) != NOTES_PER_GROUP:
            raise RuntimeError("组 %s(%s) 注数异常：%d（应为 8）" % (key, pat, len(notes)))
        out[key] = {"pattern": pat, "notes": notes}
    return out


def build_extra_notes(history, today=None):
    """供 daily_review.main() 追加到 recs 的 16 个 note dict；未生效返回 []。"""
    groups = gen_groups(history, today)
    if not groups:
        return []
    out = []
    for key, pat in GROUP_PATTERNS:
        for n in groups[key]["notes"]:
            out.append({
                "nums": list(n),
                "sum_val": sum(n),
                "span": max(n) - min(n),
                "logic": "大小形态v1 %s组/%s（随机采样·等同机选·无预测力）" % (key, pat),
            })
    if len(out) != TOTAL_NOTES:
        raise RuntimeError("大小形态两组总注数异常：%d（应为 16）" % len(out))
    return out


def groups_payload(extra_notes):
    """把追加的 16 注还原成展示用两组结构（供 unified_review 微信摘要/报告）。"""
    if not extra_notes or len(extra_notes) != TOTAL_NOTES:
        return {}
    return {
        "A": {"pattern": "大大小", "notes": [n["nums"] for n in extra_notes[:8]]},
        "B": {"pattern": "大小小", "notes": [n["nums"] for n in extra_notes[8:]]},
    }


def _selftest():
    recs = pp.load(HIST)
    g = gen_groups(recs, "2026-11-05")
    assert set(g) == {"A", "B"}, "生效日应产出两组"
    for key, pat in GROUP_PATTERNS:
        assert len(g[key]["notes"]) == 8, "%s组注数错" % key
        assert all(pp.pattern_of({"bai": n[0], "shi": n[1], "ge": n[2]}) == pat
                   for n in g[key]["notes"]), "%s组形态错" % key
    print("  ✅ 生效日：2组各8注，形态全对")

    notes = build_extra_notes(recs, "2026-11-05")
    assert len(notes) == 16, "追加注数应为 16"
    assert all(set(n) >= {"nums", "sum_val", "span", "logic"} for n in notes), "字段缺失"
    assert all(n["sum_val"] == sum(n["nums"]) and n["span"] == max(n["nums"]) - min(n["nums"])
               for n in notes), "和值/跨度计算错"
    print("  ✅ 追加注数：16 注，字段/和值/跨度全对")

    pl = groups_payload(notes)
    assert pl["A"]["notes"] == g["A"]["notes"] and pl["B"]["notes"] == g["B"]["notes"]
    print("  ✅ 展示结构还原一致（A前8 / B后8）")

    assert gen_groups(recs, "2026-11-04") == {}, "生效前不应出号"
    assert build_extra_notes(recs, "2026-11-04") == [], "生效前不应追加"
    print("  ✅ 生效前(11-04)：返回空，不提前加注")
    print("SELFTEST PASS")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="指定日期 YYYY-MM-DD")
    ap.add_argument("--dry-run", action="store_true", help="打印两组号码（只读）")
    ap.add_argument("--selftest", action="store_true", help="自测")
    a = ap.parse_args()
    if a.selftest:
        _selftest()
    else:
        today = a.date or datetime.now().strftime("%Y-%m-%d")
        g = gen_groups(pp.load(HIST), today)
        if not g:
            print("本日(%s)不出号：%s" % (today, "尚未生效" if not is_active(today) else "休市/数据不足"))
        else:
            print("本日(%s) 大小形态两组（并入 3D 主台账，共16注/32元）：" % today)
            for key, pat in GROUP_PATTERNS:
                print("  %s组(%s)：%s" % (
                    key, pat, " ".join("".join(str(x) for x in n) for n in g[key]["notes"])))
