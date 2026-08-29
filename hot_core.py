# -*- coding: utf-8 -*-
"""
热号锁定（固定追）模块 v1（2026-08-29 新增）
============================================
用户规则：从近 100 期热号中选出「胆码 / 核心号」，**每月 1 号重选一次，月内固定不动**。

三品种落地方式（成本维持不变）：
  福彩3D  : 胆1拖5 -> C(5,2) = 10 注，每注必含胆码      （20 元/天）
  大乐透  : 每注前区必含 2 个核心热号，后区不锁          （10 元/期）
  双色球  : 每注红球必含 2 个核心热号，蓝球不锁          （10 元/期）

⚠️ 诚实边界（勿删）：
  热号追号与随机选号**在数学上完全等价**——每注中奖概率恒定，期望不变。
  锁定热号只是「围绕看好的号码组织投注」，属于投注结构偏好，不提升任何概率优势。
  对外输出一律保持「随机采样·等同机选·无预测力」标注。

生效日期（用户 2026-08-29 定）：
  **2026-09-01 起**才启用热号追号；2026-08-30 ~ 08-31 仍走旧逻辑（3D v4 边际采样 /
  大乐透·双色球 v2 无核心号）。到点自动切换，无需再改代码。
  此后**每月 1 号**按最新近 100 期热号重选胆码/核心号。

状态文件：data/hot_core.json（按 年-月 判定是否需要重选）
"""
import os
import json
from datetime import datetime, date
from collections import Counter
from itertools import combinations

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(BASE_DIR, "data", "hot_core.json")

WINDOW = 100          # 冷热号统计窗口（近 N 期）
D3_TUO_N = 5          # 3D 拖码个数：C(5,2)=10 注
CORE_RED_N = 2        # 大乐透/双色球 锁定的红球（前区）热号个数

EFFECTIVE_FROM = "2026-09-01"   # 热号追号的生效日期（含当日）


def is_active(today=None) -> bool:
    """是否已到生效日期。未生效时三品种一律走旧逻辑（v4 / v2）。"""
    d = today or datetime.now().date()
    return d >= date.fromisoformat(EFFECTIVE_FROM)


def effective_desc():
    """给报告/推送用的一句话状态说明。"""
    if is_active():
        return "热号追号已生效（%s 起）" % EFFECTIVE_FROM
    return "热号追号将于 %s 生效，当前仍按原随机采样出号" % EFFECTIVE_FROM


def _load():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _ym():
    return datetime.now().strftime("%Y-%m")


def _fresh(game, state):
    """本月尚未锁定（或跨月）→ 需要重选。"""
    rec = state.get(game)
    return (not rec) or rec.get("ym") != _ym()


MIN_RECORDS = 10      # 少于此期数视为数据异常，不计算（交由上层回退）


# ---------------- 福彩3D：胆1拖5 ----------------
def _compute_3d(records, window=WINDOW):
    """胆码 = 近 window 期频率 TOP1；拖码 = 其余数字中频率 TOP5。"""
    if not records or len(records) < MIN_RECORDS:
        raise ValueError("历史数据不足(%d期)，拒绝计算热号" % (len(records or []),))
    win = records[:window]
    cnt = Counter()
    for r in win:
        for x in r["nums"]:
            cnt[x] += 1
    ranked = sorted(range(10), key=lambda d: (-cnt.get(d, 0), d))
    dan = ranked[0]
    tuo = sorted(ranked[1:1 + D3_TUO_N])
    return {"dan": dan, "tuo": tuo,
            "freq": {str(d): cnt.get(d, 0) for d in ranked}}


def get_3d_core(records, window=WINDOW):
    """返回 (dan, tuo_list, meta)。按月缓存，月内固定。"""
    state = _load()
    if _fresh("3d", state):
        core = _compute_3d(records, window)
        state["3d"] = {"ym": _ym(), "updated": datetime.now().strftime("%Y-%m-%d"),
                       **core}
        _save(state)
    rec = state["3d"]
    return rec["dan"], rec["tuo"], rec


def dantuo_notes(dan, tuo):
    """胆1拖t：C(t,2) 注，每注 = [dan] + 拖码中取 2 个（升序）。"""
    return [sorted([dan] + list(c)) for c in combinations(sorted(tuo), 2)]


# ---------------- 大乐透 / 双色球：红球（前区）核心 ----------------
def _compute_red(records, key, red_max, window=WINDOW, n=CORE_RED_N):
    """core = 近 window 期红球/前区频率 TOP n。"""
    if not records or len(records) < MIN_RECORDS:
        raise ValueError("历史数据不足(%d期)，拒绝计算热号" % (len(records or []),))
    win = records[:window]
    cnt = Counter()
    for r in win:
        for x in r.get(key, []):
            cnt[x] += 1
    ranked = sorted(range(1, red_max + 1), key=lambda d: (-cnt.get(d, 0), d))
    return {"core_red": ranked[:n],
            "freq": {str(d): cnt.get(d, 0) for d in ranked[:10]}}


def get_dlt_core(records, window=WINDOW):
    """大乐透：前区核心热号 TOP2。"""
    state = _load()
    if _fresh("dlt", state):
        core = _compute_red(records, "reds", 35, window)
        state["dlt"] = {"ym": _ym(), "updated": datetime.now().strftime("%Y-%m-%d"),
                        **core}
        _save(state)
    rec = state["dlt"]
    return rec["core_red"], rec


def get_ssq_core(records, window=WINDOW):
    """双色球：红球核心热号 TOP2。"""
    state = _load()
    if _fresh("ssq", state):
        core = _compute_red(records, "reds", 33, window)
        state["ssq"] = {"ym": _ym(), "updated": datetime.now().strftime("%Y-%m-%d"),
                        **core}
        _save(state)
    rec = state["ssq"]
    return rec["core_red"], rec


def peek(game):
    """只读缓存（不触发计算、不写盘）。返回已锁定的记录 dict；无则返回 None。"""
    return _load().get(game)


def summary_line():
    """给报告/推送用的一行说明（含诚实标注）。"""
    state = _load()
    parts = []
    if state.get("3d"):
        parts.append("3D胆%d拖%s" % (state["3d"]["dan"],
                                     "/".join(str(x) for x in state["3d"]["tuo"])))
    if state.get("dlt"):
        parts.append("大乐透核心%s" % "/".join("%02d" % d for d in state["dlt"]["core_red"]))
    if state.get("ssq"):
        parts.append("双色球核心%s" % "/".join("%02d" % d for d in state["ssq"]["core_red"]))
    if not parts:
        return ""
    return "热号追号（%s，%s 锁定，每月1号重选）｜与机选同概率，非预测" % (
        "；".join(parts), state.get("3d", state.get("dlt", state.get("ssq", {}))).get("ym", ""))


if __name__ == "__main__":
    print(summary_line() or "（尚未生成热号锁定，运行 unified_review.py 后自动生成）")
