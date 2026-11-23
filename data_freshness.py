# -*- coding: utf-8 -*-
"""
data_freshness —— 开奖数据新鲜度检查（只读诊断层）

背景（2026-11-23 云明指令「加个数据新鲜度检查，防止 9 期滞后」）：
  huiniao 镜像自 11-14 起停更，福彩3D 滞后 8 期、七乐彩滞后 3 期，
  但 3D 仅暂停出号、滞后只写在品种段一行文字里；七乐彩 stale_reuse
  只防重复建仓、不防源停更 —— 两者都不进「⚠️ 运行告警」段，问题被静默掩盖。

本模块统一检查四品种「本地最新开奖日」vs「截至昨日最近的法定开奖日」，
按开奖日历算出落后开奖期数，超阈值经 alerts.ALERTS 升级为微信摘要的
「⚠️ 运行告警」段，从而在任何品种滑向 9 期滞后之前显式告警。

设计原则：
  - 只读本地 history.json，不改任何台账/状态，不碰选号与结算代码
  - 用「开奖日期」而非期号反推，天然处理跨年、休市、期号格式差异
  - 休市日按 trading_day.holidays.json 排除，避免把官方停开误报为滞后
  - 幂等：纯函数，同输入必得同输出；不写文件
  - 红线：告警文案不含「推荐/预测/荐号」正面词

阈值（gap = 本地最新开奖日之后、截至昨日应开但缺失的开奖期数）：
  gap <= 1  正常（1 期容差，避免同步抖动/调期误报）
  gap == 2  WARN
  gap >= 3  ERROR
"""
import os
import json
from datetime import date, datetime, timedelta

ROOT = os.path.dirname(os.path.abspath(__file__))

from trading_day import load_holidays

# 开奖星期（Monday=0）；None = 天天开（仅休市除外）
DRAW_DOWNS = {
    "3d": None,        # 福彩3D 天天开
    "dlt": (0, 2, 5),  # 周一/三/六
    "ssq": (1, 3, 6),  # 周二/四/日
    "qlc": (0, 2, 4),  # 周一/三/五
}
NAMES = {"3d": "福彩3D", "dlt": "大乐透", "ssq": "双色球", "qlc": "七乐彩"}
HISTORY = {
    "3d": "data/3d_history.json",      # list，元素含 qihao/date
    "dlt": "data/dlt_history.json",    # dict(draws=[...])，元素含 issue/date
    "ssq": "data/ssq_history.json",
    "qlc": "data/qlc_history.json",
}
WARN_GAP = 2
ERROR_GAP = 3


def _to_date(x):
    """'YYYY-MM-DD' / date / datetime → date；失败 None。"""
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, date):
        return x
    if isinstance(x, str):
        try:
            return datetime.strptime(x, "%Y-%m-%d").date()
        except ValueError:
            return None
    return None


def _is_draw_day(d, game, holidays):
    """该日期是否为品种的法定开奖日（排除官方休市）。"""
    if d.isoformat() in holidays:
        return False
    dows = DRAW_DOWNS[game]
    return True if dows is None else (d.weekday() in dows)


def _latest_local(game):
    """只读本地最新开奖 (issue, draw_date)；失败返回 (None, None)。"""
    try:
        with open(os.path.join(ROOT, HISTORY[game]), encoding="utf-8") as f:
            data = json.load(f)
        rec = data[0] if isinstance(data, list) else (data.get("draws") or [None])[0]
        if not rec:
            return None, None
        issue = rec.get("qihao") or rec.get("issue")
        return str(issue) if issue else None, _to_date(rec.get("date"))
    except Exception:
        return None, None


def _expected_last_draw_day(yesterday, game, holidays):
    """yesterday（含）之前最近的法定开奖日。"""
    d = yesterday
    for _ in range(15):
        if _is_draw_day(d, game, holidays):
            return d
        d -= timedelta(days=1)
    return None


def _missing_draws(local_day, expected_day, game, holidays):
    """(local_day, expected_day] 区间内应开但未落入本地的开奖期数。
    local_day > expected_day 表示本地数据超前（异常）→ 返回 -1。"""
    if local_day is None or expected_day is None:
        return None
    if local_day > expected_day:
        return -1
    n = 0
    d = local_day + timedelta(days=1)
    while d <= expected_day:
        if _is_draw_day(d, game, holidays):
            n += 1
        d += timedelta(days=1)
    return n


def check_all(yesterday_str):
    """检查四品种数据新鲜度，返回 {game: {...}}，不改任何状态。"""
    yesterday = _to_date(yesterday_str)
    if yesterday is None:
        return {}
    holidays = load_holidays()
    out = {}
    for game in ("3d", "dlt", "ssq", "qlc"):
        issue, local_day = _latest_local(game)
        expected = _expected_last_draw_day(yesterday, game, holidays)
        gap = _missing_draws(local_day, expected, game, holidays)

        level = "OK"
        msg = ""
        if gap is None:
            level, msg = "WARN", "无法判定数据新鲜度（本地无开奖日期或文件读取失败）"
        elif gap < 0:
            level, msg = "ERROR", "数据异常：本地最新开奖日 %s 晚于截至 %s 的最近开奖日" % (
                local_day.isoformat(), yesterday_str)
        elif gap >= ERROR_GAP:
            level = "ERROR"
            msg = "数据新鲜度告警：本地最新 %s期(%s)，截至 %s 应已开出 %d 期，抓取源疑似停更，号码与盈亏不完整" % (
                issue or "?", local_day.isoformat(), yesterday_str, gap)
        elif gap >= WARN_GAP:
            level = "WARN"
            msg = "数据新鲜度提醒：本地最新 %s期(%s)，较开奖日历落后 %d 期，请留意抓取源同步" % (
                issue or "?", local_day.isoformat(), gap)

        out[game] = {
            "name": NAMES[game], "issue": issue,
            "local_day": local_day.isoformat() if local_day else None,
            "expected_day": expected.isoformat() if expected else None,
            "gap": gap, "level": level, "msg": msg,
        }
    return out


def alert_all(results, alerter):
    """把非 OK 结果写入告警收集器（alerter 需有 add(sev, scope, msg)）。"""
    for game in ("3d", "dlt", "ssq", "qlc"):
        r = results.get(game) or {}
        if r.get("level") in ("WARN", "ERROR"):
            alerter.add(r["level"], r["name"], r["msg"])


def render_lines(results):
    """渲染微信摘要用的只读检查行（全部正常时也给出一行 PASS）。"""
    lines = []
    bad = [g for g in ("3d", "dlt", "ssq", "qlc")
           if (results.get(g) or {}).get("level") in ("WARN", "ERROR")]
    if bad:
        for g in bad:
            r = results[g]
            lines.append("  [%s] %s：%s" % (r["level"], r["name"], r["msg"]))
    else:
        lines.append("  ✅ 四品种开奖数据新鲜度正常（截至昨日，本地均为最新）")
    return lines


# ---------------- 自检 ----------------
if __name__ == "__main__":
    # 2026-11-23 复盘场景：昨日 11-22。预期 3D gap=8(ERROR)、qlc gap=3(ERROR)，
    # dlt/ssq gap=0(OK)。另测休市边界：国庆期内不误报。
    r = check_all("2026-11-22")
    print("== check_all('2026-11-22') ==")
    for g in ("3d", "dlt", "ssq", "qlc"):
        x = r[g]
        print("  %-4s local=%s(%s) expected=%s gap=%s level=%s" % (
            g, x["issue"], x["local_day"], x["expected_day"], x["gap"], x["level"]))
        if x["msg"]:
            print("       msg: %s" % x["msg"])
    print("\n== 断言（通用不变量，不依赖当前数据状态）==")
    ok = True
    for g in ("3d", "dlt", "ssq", "qlc"):
        got = r[g]
        good = got["gap"] is not None and got["gap"] >= 0 and got["level"] in ("OK", "WARN", "ERROR")
        if got["gap"] is not None and got["gap"] < 0:
            good = got["level"] == "ERROR"  # 超前数据应报 ERROR
        mark = "✅" if good else "❌"
        print("  %s %s: gap=%s level=%s" % (mark, g, got["gap"], got["level"]))
        ok = ok and good

    # 休市边界：国庆 10-01~10-04 停开，若本地停在 09-30、昨日 10-03，3D gap 应为 0
    hd = load_holidays()
    e = _expected_last_draw_day(date(2026, 10, 3), "3d", hd)
    mark = "✅" if e == date(2026, 9, 30) else "❌"
    print("  %s 休市边界: 截至10-03最近开奖日=%s (期望2026-09-30)" % (mark, e))
    ok = ok and (e == date(2026, 9, 30))
    print("\n全部通过 ✅" if ok else "\n存在失败用例 ❌")
