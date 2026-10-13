# -*- coding: utf-8 -*-
"""
period_util —— 跨年期号推算工具（2026-10-13 审计修复 A3）

背景（number_generation_audit_2026-10-13.md P0-1）：
  旧实现「最新期号 + 1」在跨年时产生不存在的期号：
    3D  : 2026355 + 1 = 2026356，真实下期是 2027001 → 结算永久失配
    dlt : 26154   + 1 = 26155，  真实下期是 27001   → 组合永久冻结
  触发时间约 2026-12-28（大乐透/双色球）/ 2026-12-31（3D）。

修复思路：期号年内连续编号，"最新期+1"在年内永远正确；
  唯一错误场景是跨年。因此用「最新开奖日期 → 下一开奖日期」的年份判定进位：
    - 3D        天天开奖（休市期号连续跳过），下一期 = 最新开奖日的次一自然日起
    - 大乐透    周一/三/六开奖
    - 双色球    周二/四/日开奖
  date 缺失/解析失败时回退旧的 +1 行为并打印告警（保持可用性）。

春节等年内休市不影响年份判定（春节不跨年）；
国庆同理。唯一跨年附近的休市是元旦，已由"次一开奖日年份"覆盖。
"""
from datetime import datetime, timedelta

# 大乐透开奖星期（Monday=0）：周一/三/六
DLT_DRAW_DOWS = (0, 2, 5)
# 双色球开奖星期：周二/四/日
SSQ_DRAW_DOWS = (1, 3, 6)


def _to_date(d):
    """'YYYY-MM-DD' / date / datetime → date；失败返回 None。"""
    from datetime import date as _date
    if isinstance(d, _date):
        return d
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, str):
        try:
            return datetime.strptime(d, "%Y-%m-%d").date()
        except ValueError:
            return None
    return None


def _next_draw_date(cur_date, draw_dows):
    """cur_date 之后（不含）的第一个开奖日。draw_dows=None 表示次一自然日（3D）。"""
    nd = cur_date + timedelta(days=1)
    if draw_dows is None:
        return nd
    dows = set(draw_dows)
    for _ in range(14):  # 最长两周必有开奖
        if nd.weekday() in dows:
            return nd
        nd += timedelta(days=1)
    return cur_date + timedelta(days=1)  # 理论不可达，兜底


def next_3d_qihao(cur_qihao, cur_date=None, warn=True):
    """福彩3D 下一期期号。cur_qihao: '2026271'；cur_date: 最新开奖日 'YYYY-MM-DD'。
    跨年 → '2027001'；年内 → cur+1（与旧行为一致）。"""
    cur = int(str(cur_qihao))
    d = _to_date(cur_date)
    if d is None:
        if warn:
            print("  ⚠️ period_util: 3D 最新开奖日期缺失，期号推算退化为 %d+1（跨年场景可能失配）" % cur)
        return str(cur + 1)
    nd = _next_draw_date(d, None)
    if nd.year > d.year:
        return "%d001" % nd.year
    return str(cur + 1)


def next_issue_yy(cur_issue, cur_date=None, draw_dows=None, game="", warn=True):
    """大乐透/双色球 下一期期号（YYNNN）。cur_issue: '26116'。
    跨年 → '27001'；年内 → cur+1（与旧行为一致）。"""
    cur = int(str(cur_issue))
    d = _to_date(cur_date)
    if d is None:
        if warn:
            print("  ⚠️ period_util: %s 最新开奖日期缺失，期号推算退化为 %d+1（跨年场景可能失配）" % (game, cur))
        return str(cur + 1)
    nd = _next_draw_date(d, draw_dows)
    if nd.year > d.year:
        return "%02d001" % (nd.year % 100)
    return str(cur + 1)


def next_dlt_issue(cur_issue, cur_date=None, warn=True):
    return next_issue_yy(cur_issue, cur_date, DLT_DRAW_DOWS, game="大乐透", warn=warn)


def next_ssq_issue(cur_issue, cur_date=None, warn=True):
    return next_issue_yy(cur_issue, cur_date, SSQ_DRAW_DOWS, game="双色球", warn=warn)


# ---------------- 自检 ----------------
if __name__ == "__main__":
    cases = [
        # (说明, 函数, 参数, 期望)
        ("3D 年内", next_3d_qihao, ("2026271", "2026-10-12"), "2026272"),
        ("3D 年末→跨年(元旦开奖)", next_3d_qihao, ("2026355", "2026-12-31"), "2027001"),
        ("3D 年末(12/30开奖,次日跨年前)", next_3d_qihao, ("2026354", "2026-12-30"), "2026355"),
        ("3D 12/31开奖但date缺失→退化+1", next_3d_qihao, ("2026355", None), "2026356"),
        ("大乐透 年内", next_dlt_issue, ("26116", "2026-10-12"), "26117"),
        ("大乐透 年末: 12-28(周一)开奖→下期12-30周三年内", next_dlt_issue, ("26154", "2026-12-28"), "26155"),
        ("大乐透 年末最后一期12-30(周三)→2027-01-02周六跨年", next_dlt_issue, ("26155", "2026-12-30"), "27001"),
        ("大乐透 年末: 12-23(周三)开奖→12-26周六年内", next_dlt_issue, ("26152", "2026-12-23"), "26153"),
        ("双色球 年末: 12-27(周日)开奖→12-29周二年内", next_ssq_issue, ("26153", "2026-12-27"), "26154"),
        ("双色球 年末最后一期12-31(周四)→2027-01-03周日跨年", next_ssq_issue, ("26154", "2026-12-31"), "27001"),
        ("双色球 年内", next_ssq_issue, ("26116", "2026-10-11"), "26117"),
        ("大乐透 date缺失→退化+1", next_dlt_issue, ("26154", None), "26155"),
    ]
    ok = True
    for name, fn, args, expect in cases:
        got = fn(*args, warn=False) if len(args) == 2 else fn(*args)
        # 退化用例（date缺失）保留告警输出属于预期，此处静默
        mark = "✅" if got == expect else "❌"
        if got != expect:
            ok = False
        print("  %s %s: %s -> %s (期望 %s)" % (mark, name, args, got, expect))
    print("\n全部通过 ✅" if ok else "\n存在失败用例 ❌")
