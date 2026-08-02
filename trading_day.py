"""
交易日 / 休市 判断 (福彩3D)

核心事实 (2026-08-03 核实):
- 福彩3D 是「天天开奖、全年无休」的彩种, 周末照常开奖。
- 仅财政部公告的官方休市期停止开奖: 2026 年春节 02-14~02-23(10天)、国庆 10-01~10-04(4天)。
- 因此「周末 = 休市」对 3D 是错的; 本项目默认 closed_on_weekend=False。

设计要点:
- is_trading_day(date): 判断某日是否为交易日(开奖日)。返回布尔值。
- expected_qihao_for_date(date, anchor_qihao, anchor_date):
    以本地已知的一条(期号, 日期)为锚, 推算该日「应有的期号」。
    用于检测「数据滞后」——今日为交易日, 但本地数据期号落后,
    说明抓取源过期, 此时应报警而非误判休市。

旧逻辑 (daily_review.py 已废弃):
    is_suspension = (last_draw == current_latest)   # 期号没变就判休市
该逻辑在「抓取源过期 / 早晨未开奖 / 抓取失败」时都会误判休市, 已纠正。
"""

import json
import os
from datetime import date, datetime, timedelta

HOLIDAYS_FILE = os.path.join(os.path.dirname(__file__), "data", "holidays.json")

# 兜底内置(防止 holidays.json 缺失): 2026 官方休市期
_FALLBACK_HOLIDAYS = {
    # 春节 2026-02-14 0:00 ~ 02-23 24:00
    "2026-02-14", "2026-02-15", "2026-02-16", "2026-02-17", "2026-02-18",
    "2026-02-19", "2026-02-20", "2026-02-21", "2026-02-22", "2026-02-23",
    # 国庆 2026-10-01 ~ 10-04
    "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04",
}


def _to_date(d):
    """接受 date 对象或 'YYYY-MM-DD' 字符串, 返回 date 对象"""
    if isinstance(d, date) and not isinstance(d, datetime):
        return d
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, str):
        return datetime.strptime(d, "%Y-%m-%d").date()
    raise TypeError(f"不支持的日期类型: {type(d)}")


def load_holidays(path=HOLIDAYS_FILE):
    """从 data/holidays.json 加载休市日集合; 文件缺失则用内置兜底"""
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            holidays = set(data.get("holidays", []))
            if holidays:
                return holidays
        except Exception:
            pass
    return set(_FALLBACK_HOLIDAYS)


def is_trading_day(d, *, closed_on_weekend=False, holidays=None, extra_holidays=None):
    """
    判断 d 是否为交易日(开奖日)。

    Args:
        d: 日期 (date 对象 或 'YYYY-MM-DD' 字符串)
        closed_on_weekend: 周末是否休市。
            ⚠️ 福彩3D 周末照常开奖, 必须保持 False (默认)。
            设为 True 适用于股票等周末真实休市的品种, 但会「误将交易日(周末)判为休市」。
        holidays: 休市日集合 (str 集合, 格式 'YYYY-MM-DD')。
            默认从 data/holidays.json 加载 (含 2026 春节/国庆)。
        extra_holidays: 额外追加的休市日 (与 holidays 合并), 用于临时停开公告。

    Returns:
        True  = 交易日(开奖)
        False = 休市
    """
    d = _to_date(d)

    # 1) 周末: 默认不判休市 (3D 天天开)
    if closed_on_weekend and d.weekday() >= 5:
        return False

    # 2) 官方休市日
    if holidays is None:
        holidays = load_holidays()
    all_holidays = holidays
    if extra_holidays:
        all_holidays = holidays | {str(x) for x in extra_holidays}
    if d.strftime("%Y-%m-%d") in all_holidays:
        return False

    return True


def expected_qihao_for_date(d, anchor_qihao, anchor_date):
    """
    以本地已知的一条(期号, 日期)为锚, 推算 d 日「应有的期号」。

    逻辑: 3D 每天一期(休市日除外), 所以
        expected = anchor_qihao + (anchor_date, d] 之间的交易日天数

    Args:
        d: 目标日期 (date 或 'YYYY-MM-DD')
        anchor_qihao: 锚点期号 (int 或 str, 如 2026199)
        anchor_date: 锚点日期 (date 或 'YYYY-MM-DD', 必须与 anchor_qihao 对应)

    Returns:
        int 期号

    Raises:
        ValueError: anchor_date 晚于 d 时
    """
    d = _to_date(d)
    anchor_date = _to_date(anchor_date)
    anchor_qihao = int(anchor_qihao)
    if anchor_date > d:
        raise ValueError(f"anchor_date({anchor_date}) 不能晚于目标日期 d({d})")
    # 统计 (anchor_date, d] 之间的交易日天数
    td = 0
    cur = anchor_date
    one_day = timedelta(days=1)
    while cur < d:
        cur = cur + one_day
        if is_trading_day(cur):
            td += 1
    return anchor_qihao + td


if __name__ == "__main__":
    # 简单自检
    tests = [
        ("2026-08-03", True),    # 周一, 交易日
        ("2026-08-01", True),    # 周六, 3D 仍开奖 -> 交易日
        ("2026-08-02", True),    # 周日, 3D 仍开奖 -> 交易日
        ("2026-02-15", False),   # 春节休市
        ("2026-02-23", False),   # 春节休市最后一天
        ("2026-02-24", True),    # 春节后恢复
        ("2026-10-01", False),   # 国庆休市
        ("2026-10-05", True),    # 国庆后恢复
    ]
    print("== is_trading_day 自检 ==")
    ok = True
    for ds, expect in tests:
        got = is_trading_day(ds)
        mark = "✅" if got == expect else "❌"
        if got != expect:
            ok = False
        print(f"  {mark} {ds} -> {got} (期望 {expect})")

    # expected_qihao 自检: 锚 2026199=2026-07-28, 推算 08-03 应有 205
    qh = expected_qihao_for_date("2026-08-03", 2026199, "2026-07-28")
    print(f"\n  锚 2026199(07-28) -> 08-03 应有期号: {qh} (期望 2026205)")
    print("\n全部通过 ✅" if ok and qh == 2026205 else "\n存在失败用例 ❌")
