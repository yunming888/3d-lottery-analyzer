"""
福彩3D 每日复盘自动化脚本 (动态版)
- 抓取最新数据
- 结算昨日待结算号码 (修正: 按日期匹配开奖, 避免6/29期号错位bug)
- 熔断判定 (用户新规则 2026-08-07: 每天10组组六, 组六连出>6期熔断暂停)
- 生成10组组六随机采样(每天都换)
- ⚠️ 出号性质声明(2026-08-29 用户定): 采样等同机选、无预测力, 对外一律标注"随机采样"而非"推荐"
- 更新 profit_loss.json
- 生成 markdown 报告
- 输出摘要

用法: python daily_review.py
"""
import json
import os
import sys
import argparse
from datetime import datetime, timedelta
from collections import Counter

sys.path.insert(0, os.path.dirname(__file__))

from fetch_data import load_or_fetch
from analyze import (
    frequency_analysis, missing_analysis, sum_value_analysis,
    span_analysis, type_analysis, generate_recommendations, trend_analysis, ENGINE_VERSION
)
from trading_day import is_trading_day, expected_qihao_for_date

# 支持 --date YYYY-MM-DD 回溯运行 (用于补跑历史日期)
parser = argparse.ArgumentParser()
parser.add_argument("--date", help="回溯日期 YYYY-MM-DD (默认今天)")
_args, _ = parser.parse_known_args()
if getattr(_args, "date", None):
    try:
        NOW = datetime.strptime(_args.date, "%Y-%m-%d")
    except ValueError:
        print(f"⚠️ 无效日期 {_args.date}, 使用今天")
        NOW = datetime.now()
else:
    NOW = datetime.now()
TODAY = NOW.strftime("%Y-%m-%d")
TODAY_SHORT = NOW.strftime("%m-%d")
DATA_DIR = "data"
REPORT_DIR = "data/reports"
PL_FILE = os.path.join(DATA_DIR, "profit_loss.json")
HISTORY_FILE = os.path.join(DATA_DIR, "3d_history.json")


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def settle_pending(history, pl):
    """
    结算待结算记录 — 修正版
    按日期匹配开奖, 避免6/29期号错位bug
    """
    pending = None
    for rec in pl["records"]:
        if rec["hits"] is None:
            # 只结算日期早于今天的记录 (今天的开奖还没出)
            if rec["date"] >= TODAY:
                print(f"待结算记录 {rec['date']} 是今天或未来, 开奖尚未出, 跳过结算")
                continue
            pending = rec
            break

    if pending is None:
        print("无待结算记录")
        return None

    rec_date = pending["date"]
    print(f"待结算: {rec_date}, 推荐{pending['notes']}注")

    # 策略1 (主): 按目标期号精确匹配 — 最可靠, 不受 date 缺失/偏移影响
    draw = None
    target = pending.get("target_qihao")
    if target:
        tq = str(target)
        for h in history:
            # 兼容 target_qihao 为 3位(200) 或 7位(2026200) 两种写法
            if h["qihao"] == tq or h["qihao"].endswith(tq):
                draw = h
                break
        if draw is None:
            # 目标期号尚未抓到 -> 暂缓结算, 下期再试, 绝不用错号
            print(f"  ⏸ 目标期号 {target} 尚未抓到, 暂缓结算(下期再试), 不污染数据")
            return None
        else:
            print(f"  按期号匹配: {target}")

    # 策略2 (兜底): 目标期号缺失时, 按非空 date 匹配
    if draw is None:
        for h in history:
            if h.get("date") and h["date"] == rec_date:
                draw = h
                break
        if draw is not None:
            print(f"  按日期匹配(无目标期号): {draw['qihao']}")

    # 策略3: 仍失败 -> 暂缓, 不再使用 history[0] (曾导致错配)
    if draw is None:
        print(f"  ⚠️ 无法确定 {rec_date} 的开奖期号(无目标期号且日期缺失), 暂缓结算")
        return None

    # 结算
    draw_set = set(draw["nums"])
    hits = 0
    hit_list = []
    for rec_nums in pending["recommendations"]:
        if set(rec_nums) == draw_set:
            hits += 1
            hit_list.append(rec_nums)

    pending["draw"] = draw["qihao"]
    pending["draw_nums"] = draw["nums"]
    pending["draw_type"] = draw["type"]
    pending["hits"] = hits
    # 动态奖金: 组三320 / 组六160 / 豹子1040
    per = 320 if draw["type"] == "组三" else 160 if draw["type"] == "组六" else 1040
    pending["prize"] = hits * per
    pending["daily_pnl"] = hits * per - pending["cost"]

    draw_str = ''.join(map(str, draw["nums"]))
    ptype = draw["type"]
    if hits > 0:
        hit_strs = ['[' + ','.join(map(str, h)) + ']' for h in hit_list]
        pending["reason"] = f"{ptype}{pending['notes']}注->{hits}命中{''.join(hit_strs)} 开奖{draw_str}{draw['type']}, 日盈亏{pending['daily_pnl']}元"
    else:
        pending["reason"] = f"{ptype}{pending['notes']}注->0命中 开奖{draw_str}{draw['type']}"

    print(f"  开奖: {draw['qihao']} = {draw_str} ({draw['type']})")
    print(f"  命中: {hits}注, 奖金: {pending['prize']}元, 当日盈亏: {pending['daily_pnl']}元")
    if hit_list:
        print(f"  🎯 命中推荐: {hit_list[0]}")

    return pending, draw, hits, hit_list


def calc_summary(pl):
    """重新计算累计统计"""
    total_cost = 0
    total_hits = 0
    total_prize = 0
    settled_days = 0
    active_days = 0
    total_bets = 0

    for rec in pl["records"]:
        if rec["hits"] is not None:
            total_cost += rec["cost"]
            total_bets += rec["notes"]
            if rec["notes"] > 0:
                active_days += 1
            if rec["hits"] > 0:
                total_hits += rec["hits"]
                total_prize += rec["prize"]
            settled_days += 1

    pending_bets = sum(r["notes"] for r in pl["records"] if r["hits"] is None)
    pending_cost = sum(r["cost"] for r in pl["records"] if r["hits"] is None)
    net_pnl = total_prize - total_cost

    pl["summary"] = {
        "total_days": len(pl["records"]),
        "settled_days": settled_days,
        "active_days": active_days,
        "total_bets": total_bets,
        "total_cost": total_cost,
        "total_hits": total_hits,
        "total_prize": total_prize,
        "net_pnl": net_pnl,
        "pending_bets": pending_bets,
        "pending_cost": pending_cost,
        "last_settled": TODAY,
        "last_hit": f"{TODAY} {total_hits}注" if total_hits > 0 else "无"
    }
    return pl["summary"]


def circuit_breaker_user_rules(history):
    """
    熔断规则 (用户新规则 2026-08-07)
    - 常态: 每天推 10 组组六 (每天都换)
    - 熔断: 当组六连续开出 > 6 期(即 >=7 期)时, 熔断暂停(0注),
            回避极端连开风险, 直到形态打断(出组三/豹子)再恢复
    """
    types_all = [r["type"] for r in history]

    # 当前连续同形态 (含组三/豹子)
    streak_type = types_all[0]
    streak_len = 1
    for t in types_all[1:]:
        if t == streak_type:
            streak_len += 1
        else:
            break

    # 组六连出长度 (从最新一期往前)
    zl_streak = 0
    for r in history:
        if r["type"] == "组六":
            zl_streak += 1
        else:
            break

    # 组三近30期次数 (信息留存, 不参与熔断决策)
    gs_count_30 = types_all[:30].count("组三")
    sums_3 = [r["sum_val"] for r in history[:3]]

    rules_fired = []
    # 熔断规则：组六连出 > 6 期 -> 暂停
    if zl_streak > 6:
        rules_fired.append(f"熔断: 组六已连出 {zl_streak} 期(>6) -> 暂停推送, 回避极端连开风险")
        stop = True
    else:
        stop = False
        rules_fired.append(f"常态: 推 10 组组六 (组六连出 {zl_streak} 期, 未达熔断阈值 7 期)")

    push_type = "组六"
    push_count = 0 if stop else 10

    return {
        "stop": stop,
        "rules_fired": rules_fired,
        "streak_type": streak_type,
        "streak_len": streak_len,
        "zl_streak": zl_streak,
        "gs_count_30": gs_count_30,
        "last2_both_gs": False,
        "sums_3": sums_3,
        "push_type": push_type,
        "push_count": push_count,
    }


def generate_report(history, pl, cb, recs, settlement, today_draw_qihao, trend=None):
    """生成 markdown 报告"""
    os.makedirs(REPORT_DIR, exist_ok=True)

    latest = history[0]
    prev = history[1] if len(history) > 1 else None
    prev2 = history[2] if len(history) > 2 else None

    # 盈亏表格
    pnl_rows = []
    cumulative = 0
    for rec in pl["records"]:
        if rec["hits"] is not None:
            cumulative += rec["daily_pnl"] if rec["daily_pnl"] is not None else 0
            hit_str = f"{rec['hits']}注" if rec["hits"] > 0 else "0"
            prize_str = f"{rec['prize']}元" if rec["prize"] > 0 else "0"
            pnl_str = f"{rec['daily_pnl']:+d}元" if rec["daily_pnl"] else "—"
            date_short = rec["date"][5:]
            pnl_rows.append(f"| {date_short} | {rec['notes']} | {rec['cost']}元 | {hit_str} | {prize_str} | {pnl_str} | {cumulative:+d}元 |")
    for rec in pl["records"]:
        if rec["hits"] is None:
            date_short = rec["date"][5:]
            pnl_rows.append(f"| {date_short} | {rec['notes']} | {rec['cost']}元 | 待开奖 | — | — | 待结算 |")
    pnl_table = "\n".join(pnl_rows)

    # 遗漏表
    miss = missing_analysis(history)
    missing_rows = []
    for n in range(10):
        m = miss["missing_periods"][n]
        bar = "█" * min(m, 10) if m > 0 else "刚出"
        missing_rows.append(f"| {n} | {m}期 | {bar} |")
    missing_table = "\n".join(missing_rows)

    # 频率表
    freq = frequency_analysis(history)
    freq_rows = []
    for n, c in freq["total_freq"]:
        bar = "█" * min(c, 15)
        freq_rows.append(f"| {n} | {c}次 | {bar} |")
    freq_table = "\n".join(freq_rows)

    # 推荐表
    rec_rows = []
    for i, r in enumerate(recs):
        rec_rows.append(f"| {i+1} | {' '.join(map(str, r['nums']))} | {r['sum_val']} | {r['span']} | {r['logic']} |")
    rec_table = "\n".join(rec_rows) if rec_rows else "| - | 休市/熔断未出号 | - | - | - |"

    # 形态走势 (近15期)
    trend_rows = []
    for r in history[:15]:
        tag = "组六" if r["type"] == "组六" else "🔵组三" if r["type"] == "组三" else "🔴豹子"
        trend_rows.append(f"| {r['qihao']} | {r.get('date', '?')} | {' '.join(map(str, r['nums']))} | {r['sum_val']} | {r['span']} | {tag} |")
    trend_table = "\n".join(trend_rows)

    # 熔断详情
    cb_detail = ""
    for rf in cb["rules_fired"]:
        cb_detail += f"- {rf}\n"
    if not cb["rules_fired"]:
        cb_detail = "- 无规则触发, 正常出号\n"
    if any("休市" in rf for rf in cb["rules_fired"]):
        cb_status = "⏸ 休市(无新开奖)"
    elif cb["stop"]:
        cb_status = "🛑 熔断(暂停)"
    else:
        cb_status = f"✅ 推{cb['push_count']}注{cb['push_type']}"

    # 结算信息
    settle_section = ""
    if settlement:
        rec_data, draw, hits, hit_list = settlement
        settle_section = f"""
### {rec_data['date']} 结算

| 项目 | 数值 |
|------|------|
| 开奖 | {draw['qihao']} → **{' '.join(map(str, draw['nums']))}** {draw['type']} |
| 投注 | {rec_data['notes']}注组六 |
| 命中 | **{hits}注** {"🎯" if hits > 0 else ""} |
| 成本 | {rec_data['cost']}元 |
| 奖金 | {rec_data['prize']}元 |
| 日盈亏 | **{rec_data['daily_pnl']:+d}元** |
"""
        if hit_list:
            settle_section += f"\n> 🎯 命中号码: {hit_list[0]}\n"

    s = pl["summary"]
    next_qihao = str(int(latest["qihao"]) + 1)

    # 100期走势研判段落（出号前必看）
    trend_section = ""
    if trend:
        freq_rows = "\n".join(
            f"| {d} | {c}次 | {p:.1f}% | {'█' * min(c, 15)} |"
            for d, c, p in trend["freq_sorted"]
        )
        trend_section = f"""
---

## 三·五、100期走势研判（出号前必看）

> {trend['conclusion']}

### 数字热冷（近{trend['window']}期全位）
| 数字 | 出现次数 | 频率 | 热度 |
|------|----------|------|------|
{freq_rows}

### 和值 / 跨度趋势
| 指标 | 近{trend['window']}期均值 | 近30期均值 | 走势 |
|------|------|------|------|
| 和值 | {trend['avg_sum_all']:.1f} | {trend['avg_sum_recent']:.1f} | {trend['sum_trend']} |
| 跨度 | {trend['span_avg_all']:.1f} | {trend['span_avg_recent']:.1f} | {trend['span_trend']} |

### 当前形态连开
- 组六连出 **{trend['zl_streak']}** 期
- 最大遗漏: {', '.join(f"{d}号({m}期)" for d, m in trend['overdue'])}

---
"""

    try:
        import hot_core
        _engine_status = hot_core.effective_desc() + "（代码版本 选号引擎 %s）" % ENGINE_VERSION
    except Exception:
        _engine_status = "选号引擎 %s" % ENGINE_VERSION

    report = f"""# 福彩3D 每日复盘报告
**日期: {TODAY}** | 期号: {latest['qihao']} 已开 → {next_qihao} 待开

> ⚠️ **性质声明**：本报告中的号码均为程序随机采样生成，**等同投注站机选，不具备预测能力**。
> 彩票开奖完全随机、每期独立，不存在可推算的下期号码；任何声称能预测或推荐中奖号码的个人、平台或 AI 均属诈骗。
> 本报告仅供学习研究与盈亏记录，不构成投注建议。
>
> ℹ️ **出号规则状态**：{_engine_status}

---

## 一、昨日复盘 (最近3期)

| 期号 | 日期 | 号码 | 和值 | 跨度 | 形态 |
|------|------|------|------|------|------|
| {latest['qihao']} | {latest.get('date', '?')} | {' '.join(map(str, latest['nums']))} | {latest['sum_val']} | {latest['span']} | {latest['type']} |
{f"| {prev['qihao']} | {prev.get('date', '?')} | {' '.join(map(str, prev['nums']))} | {prev['sum_val']} | {prev['span']} | {prev['type']} |" if prev else ""}
{f"| {prev2['qihao']} | {prev2.get('date', '?')} | {' '.join(map(str, prev2['nums']))} | {prev2['sum_val']} | {prev2['span']} | {prev2['type']} |" if prev2 else ""}

---

## 二、盈亏结算
{settle_section}
### 累计盈亏表

| 日期 | 投注数 | 成本 | 命中 | 奖金 | 当日盈亏 | 累计盈亏 |
|------|--------|------|------|------|----------|----------|
{pnl_table}

> **累计**: {s['settled_days']}天已结算/{s['active_days']}活跃日/{s['total_bets']}注/{s['total_hits']}命中/净盈亏{s['net_pnl']:+d}元, 待结算{s['pending_bets']}注{s['pending_cost']}元

---

## 三、熔断判定

**判定状态**: {cb_status}

### 规则触发详情
{cb_detail}

### 当前形态状态
- 最新: **{cb['streak_type']}{cb['streak_len']}连** (组六{cb['zl_streak']}连)
- 组三近30期: {cb['gs_count_30']}次
- 近3期和值: {', '.join(map(str, cb['sums_3']))}

{trend_section}
## 四、今日随机采样 ({len(recs)}注{cb['push_type']})｜等同机选·无预测力  【选号引擎 {ENGINE_VERSION}】

> ⚠️ 以下号码由程序按历史分布随机采样生成，**与投注站机选在统计上无区别，不具备任何预测能力**。
> 开奖完全随机、每期独立，不存在可推算的下期号码。任何声称能预测中奖号的人或平台均为诈骗。
> 本节仅供学习研究与记录盈亏，不构成投注建议。

| # | 号码 | 和值 | 跨度 | 采样逻辑 |
|---|------|------|------|----------|
{rec_table}

---

## 五、数据面板

### 热号 Top5 (全位)
{freq_table}

### 冷号/遗漏
{missing_table}

### 形态走势 (近15期)
{trend_table}

---

## 六、风险提示

1. 本报告仅供学习研究，不构成投注建议。彩票有风险，理性购彩。
2. 数据来源: 东方财富 caipiao.eastmoney.com
3. 生成时间: {NOW.strftime('%Y-%m-%d %H:%M:%S')}
"""

    report_path = os.path.join(REPORT_DIR, f"{TODAY}.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)

    print(f"\n✅ 报告已生成: {report_path}")
    return report_path


def main():
    print(f"=== 福彩3D 每日复盘 {TODAY} ===\n")

    # 1. 抓取最新数据
    print("[1/7] 抓取最新数据...")
    history = load_or_fetch()
    if not history:
        print("❌ 数据抓取失败, 退出")
        return
    latest = history[0]
    print(f"  最新: {latest['qihao']} | {' '.join(map(str, latest['nums']))} | {latest['type']}")
    print(f"  范围: {history[-1]['qihao']} ~ {history[0]['qihao']} ({len(history)}期)")

    # 昨日(前一自然日)开奖，用于统一复盘摘要
    yesterday = (NOW - timedelta(days=1)).strftime("%Y-%m-%d")
    yesterday_draw = None
    for h in history:
        if h.get("date") == yesterday:
            yesterday_draw = h
            break

    # 2. 加载P&L
    print("\n[2/7] 加载盈亏数据...")
    pl = load_json(PL_FILE)
    print(f"  追踪区间: {pl['start_date']} ~ {pl['end_date']}")
    print(f"  当前累计: {pl['summary']['net_pnl']:+d}元")

    # 2.5 休市检测 (修正版): 以日历为准, 不再用"期号不变=休市"
    #   - 今日为官方休市期  => 真休市 (春节/国庆等)
    #   - 今日为交易日, 但本地数据期号落后 => 数据滞后(抓取源过期), 不误判休市
    last_draw = pl.get("last_draw_qihao")
    current_latest = history[0]["qihao"]
    today_dt = datetime.strptime(TODAY, "%Y-%m-%d").date()
    is_holiday = not is_trading_day(today_dt)
    data_stale = False
    if not is_holiday:
        # 以本地最新一条(期号, 日期)为锚, 推算今日应有的期号
        anchor_date = None
        anchor_qihao = None
        for h in history:
            if h.get("date"):
                anchor_date = datetime.strptime(h["date"], "%Y-%m-%d").date()
                anchor_qihao = int(h["qihao"])
                break
        if anchor_date is not None:
            try:
                expected_qh = expected_qihao_for_date(today_dt, anchor_qihao, anchor_date)
                gap = expected_qh - int(current_latest)
                if gap > 1:
                    # 落后超过1期 => 抓取源严重过期(如东方财富卡在199), 不误判休市
                    data_stale = True
                    print(f"  ⚠️ 数据严重滞后: 本地最新 {current_latest} 落后预期 {expected_qh} ({gap}期), 抓取源可能过期, 不判休市")
                elif gap == 1:
                    # 恰好落后1期 => 今日开奖尚未出(晚间21:15才开), 属正常, 仍可基于昨日数据推荐下一期
                    print(f"  ✅ 数据正常(今日 {expected_qh} 尚未开奖, 基于最新 {current_latest} 推荐)")
                else:
                    print(f"  ✅ 数据已含今日/更新, 最新 {current_latest}")
            except ValueError:
                pass
    is_suspension = is_holiday
    if is_holiday:
        print(f"  ⏸ 休市: 今日为官方休市期(非交易日)")
    else:
        pl["last_draw_qihao"] = current_latest

    # 3. 结算昨日待结算
    print("\n[3/7] 结算昨日推荐...")
    settlement = settle_pending(history, pl)

    # 4. 重新计算累计统计
    print("\n[4/7] 更新累计统计...")
    summary = calc_summary(pl)
    print(f"  已结算: {summary['settled_days']}天, 活跃: {summary['active_days']}天")
    print(f"  总注数: {summary['total_bets']}, 总命中: {summary['total_hits']}")
    print(f"  净盈亏: {summary['net_pnl']:+d}元, 待结算: {summary['pending_bets']}注")

    # 5. 熔断判定 + 6. 生成推荐 (休市或数据滞后时跳过)
    trend = None
    if is_suspension:
        cb = {"stop": True,
              "rules_fired": [f"休市: 今日为官方休市期, 无新开奖"],
              "streak_type": "-", "streak_len": 0, "zl_streak": 0, "gs_count_30": 0,
              "last2_both_gs": False, "sums_3": [0, 0, 0], "push_type": "组六", "push_count": 0}
        recs = []
        reason = "福彩3D休市(官方休市期), 无推荐"
        print("\n[5/7] 熔断判定: 休市, 跳过")
        print("[6/7] 生成推荐: 休市, 无推荐")
    elif data_stale:
        cb = {"stop": True,
              "rules_fired": [f"数据滞后: 本地最新 {current_latest} 落后预期期号, 抓取源过期, 暂停推荐"],
              "streak_type": "-", "streak_len": 0, "zl_streak": 0, "gs_count_30": 0,
              "last2_both_gs": False, "sums_3": [0, 0, 0], "push_type": "组六", "push_count": 0}
        recs = []
        reason = "数据滞后(抓取源过期), 暂停推荐, 待数据源恢复"
        print("\n[5/7] 熔断判定: 数据滞后, 跳过")
        print("[6/7] 生成推荐: 数据滞后, 无推荐")
    else:
        print("\n[5/7] 熔断判定...")
        cb = circuit_breaker_user_rules(history)
        print(f"  形态: {cb['streak_type']}{cb['streak_len']}连, 组六{cb['zl_streak']}连")
        print(f"  组三近30期: {cb['gs_count_30']}次")
        for rf in cb["rules_fired"]:
            print(f"  🔴 {rf}")
        status = "🛑 熔断, 0注" if cb["stop"] else f"✅ 推{cb['push_count']}注{cb['push_type']}"
        print(f"  {status}")

        # 5.5 100期走势研判（出号前必看）
        trend = trend_analysis(history)
        print(f"\n[5.5/7] 100期走势研判:")
        print(f"  {trend['conclusion']}")

        print("\n[6/7] 生成推荐...")
        if cb["stop"]:
            recs = []
            print("  熔断, 不推荐")
            reason = f"熔断触发({'; '.join(cb['rules_fired'])})"
        else:
            info = {"stop": False, "push_type": cb["push_type"], "push_count": cb["push_count"]}
            recs = generate_recommendations(history, info, count=cb["push_count"])
            print(f"  生成{len(recs)}注{cb['push_type']}:")
            for i, r in enumerate(recs):
                print(f"    {i+1}. {' '.join(map(str, r['nums']))} | 和{r['sum_val']} 跨{r['span']} | {r['logic']}")
            reason = f"{cb['push_type']}{len(recs)}注随机采样 | " + "; ".join(cb["rules_fired"] if cb["rules_fired"] else ["正常出号"])

    # 计算目标期号 (休市或数据滞后则无)
    if is_suspension or data_stale:
        target_qihao = None
    else:
        # 目标 = 最新已开期号 + 1 (下期). 直接用 history[0], 避免依赖 prev 记录状态字符串(休市/数据未更新等)
        target_qihao = str(int(history[0]["qihao"]) + 1)

    # 检查今天是否已有记录
    today_exists = any(r["date"] == TODAY for r in pl["records"])
    if today_exists:
        print(f"\n  今天({TODAY})已有记录, 检查是否需要纠正")
        for r in pl["records"]:
            if r["date"] == TODAY:
                if is_suspension:
                    r.update({"draw": "休市", "draw_nums": [], "draw_type": "休市",
                              "recommendations": [], "notes": 0, "cost": 0,
                              "hits": 0, "prize": 0, "daily_pnl": 0,
                              "reason": reason, "target_qihao": None})
                elif data_stale:
                    r.update({"draw": "数据未更新", "draw_nums": [], "draw_type": "数据未更新",
                              "recommendations": [], "notes": 0, "cost": 0,
                              "hits": 0, "prize": 0, "daily_pnl": 0,
                              "reason": reason, "target_qihao": None})
                else:
                    # 正常交易日: 若今日记录尚未结算(待开奖)且注数与当前规则(push_count)不符,
                    # 则按新规则刷新(确保"10组组六/熔断暂停"等改动即时生效到今日记录)
                    if r.get("hits") is None and (not r.get("recommendations") or r.get("notes") != len(recs)):
                        r["recommendations"] = [rec["nums"] for rec in recs]
                        r["notes"] = len(recs)
                        r["cost"] = len(recs) * 2
                        r["reason"] = reason
                        r["target_qihao"] = target_qihao
                break
    else:
        if is_suspension:
            today_rec = {"date": TODAY, "target_qihao": None, "draw": "休市",
                         "draw_nums": [], "draw_type": "休市", "recommendations": [],
                         "notes": 0, "cost": 0, "hits": 0, "prize": 0,
                         "daily_pnl": 0, "reason": reason}
        elif data_stale:
            today_rec = {"date": TODAY, "target_qihao": None, "draw": "数据未更新",
                         "draw_nums": [], "draw_type": "数据未更新", "recommendations": [],
                         "notes": 0, "cost": 0, "hits": 0, "prize": 0,
                         "daily_pnl": 0, "reason": reason}
        else:
            # 添加今日记录
            today_rec = {
                "date": TODAY,
                "target_qihao": target_qihao,
                "draw": "待开奖",
                "draw_nums": [],
                "draw_type": "",
                "recommendations": [r["nums"] for r in recs],
                "notes": len(recs),
                "cost": len(recs) * 2,
                "hits": None,
                "prize": None,
                "daily_pnl": None,
                "reason": reason
            }
        pl["records"].append(today_rec)

    # 再次更新summary (包含今日pending)
    summary = calc_summary(pl)

    # 保存P&L
    save_json(PL_FILE, pl)
    print(f"\n  ✅ profit_loss.json 已更新")

    # 7. 生成报告
    print("\n[7/7] 生成报告...")
    report_path = generate_report(history, pl, cb, recs, settlement, latest["qihao"], trend)

    # 摘要
    print(f"\n{'='*50}")
    print(f"  每日复盘完成 {TODAY}")
    print(f"{'='*50}")
    if settlement:
        print(f"  昨日结算: {settlement[2]}注命中, {settlement[0]['daily_pnl']:+d}元")
    print(f"  累计盈亏: {summary['net_pnl']:+d}元 ({summary['total_hits']}注命中)")
    print(f"  今日随机采样(等同机选): {len(recs)}注组六, 成本{len(recs)*2}元")
    print(f"  报告: {report_path}")
    print(f"  追踪期: {pl['start_date']} ~ {pl['end_date']}")

    # 返回结构化摘要，供 unified_review.py 统一汇总（不影响原自动化调用）
    return {
        "game": "3D", "name": "福彩3D", "today": TODAY,
        "yesterday": yesterday, "yesterday_draw": yesterday_draw,
        "settlement": settlement,  # (rec, draw, hits, hit_list) 或 None
        "summary": summary,
        "recommendations": recs,   # list of {nums, sum_val, span, logic}
        "next_qihao": target_qihao,
        "circuit": cb,
        "trend": trend,
        "report_path": report_path,
    }


if __name__ == "__main__":
    main()
