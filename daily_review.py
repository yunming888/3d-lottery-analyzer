"""
福彩3D 每日复盘自动化脚本 (动态版)
- 抓取最新数据
- 结算昨日待结算推荐 (修正: 按日期匹配开奖, 避免6/29期号错位bug)
- 熔断判定 (用户规则: Rule4/6/7 覆盖 Rule1/2/3)
- 生成10注组六推荐
- 更新 profit_loss.json
- 生成 markdown 报告
- 输出摘要

用法: python daily_review.py
"""
import json
import os
import sys
from datetime import datetime, timedelta
from collections import Counter

sys.path.insert(0, os.path.dirname(__file__))

from fetch_data import load_or_fetch
from analyze import (
    frequency_analysis, missing_analysis, sum_value_analysis,
    span_analysis, type_analysis, generate_recommendations
)

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

    # 策略1: 按日期匹配
    draw = None
    for h in history:
        if h.get("date") == rec_date:
            draw = h
            break

    # 策略2: 日期匹配失败, 用最新已结算期号+1推断
    if draw is None:
        latest_settled_qihao = None
        for rec in pl["records"]:
            if rec["hits"] is not None and rec["draw"] != "待开奖":
                latest_settled_qihao = rec["draw"]
        if latest_settled_qihao:
            expected_qihao = str(int(latest_settled_qihao) + 1)
            for h in history:
                if h["qihao"] == expected_qihao:
                    draw = h
                    print(f"  日期匹配失败, 期号推断: {expected_qihao}")
                    break

    # 策略3: 仍失败, 用 history[0] 但警告
    if draw is None:
        draw = history[0]
        print(f"  ⚠️ 警告: 日期和期号匹配均失败, 使用history[0]: {draw['qihao']}")

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
    pending["prize"] = hits * 160
    pending["daily_pnl"] = hits * 160 - pending["cost"]

    draw_str = ''.join(map(str, draw["nums"]))
    if hits > 0:
        hit_strs = ['[' + ','.join(map(str, h)) + ']' for h in hit_list]
        pending["reason"] = f"组六{pending['notes']}注->{hits}命中{''.join(hit_strs)} 开奖{draw_str}{draw['type']}, 日盈亏{pending['daily_pnl']}元"
    else:
        pending["reason"] = f"组六{pending['notes']}注->0命中 开奖{draw_str}{draw['type']}"

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
    用户修订版熔断规则 (v7)
    Rule1已禁用, 靠Rule2(和值极端)/Rule3(连续同形态)管
    覆盖规则: Rule4/6/7 不熔断
    用户只推组六, 不推组三
    """
    types_all = [r["type"] for r in history]
    sums_3 = [r["sum_val"] for r in history[:3]]

    # 当前连续同形态
    streak_type = types_all[0]
    streak_len = 1
    for t in types_all[1:]:
        if t == streak_type:
            streak_len += 1
        else:
            break

    # 组六连出长度
    zl_streak = 0
    for r in history:
        if r["type"] == "组六":
            zl_streak += 1
        else:
            break

    # 组三在近30期内的次数
    recent_30_types = types_all[:30]
    gs_count_30 = recent_30_types.count("组三")

    # 最近2期是否都是组三
    last2_both_gs = (len(types_all) >= 2 and types_all[0] == "组三" and types_all[1] == "组三")

    rules_fired = []
    stop = False

    # === Rule1: 组三高频熔断 — 已禁用 (2026-07-06) ===
    # 原逻辑: 近30期组三>=10次则熔断, 但组三频率波动大, 用户决定靠Rule2/3管
    # 仅记录组三频率供参考, 不触发熔断
    if gs_count_30 >= 10:
        rules_fired.append(f"Rule1(已禁用): 近30期组三{gs_count_30}次>=10, 仅记录不熔断")

    # === 覆盖规则 (始终生效) ===
    # Rule 4: 连续3期同形态 -> 不熔断, 强力推荐
    if streak_len >= 3:
        rules_fired.append(f"Rule4: 连续{streak_len}期{streak_type} -> 强推不熔断")

    # Rule 6: 组三2连 -> 不熔断, 推组六
    if streak_type == "组三" and streak_len >= 2:
        rules_fired.append(f"Rule6: 组三{streak_len}连 -> 推组六不熔断")

    # Rule 7: 组六11连+ -> 警戒但不熔断
    if zl_streak >= 11:
        rules_fired.append(f"Rule7: 组六{zl_streak}连 -> 警戒但不熔断")

    # === 次级熔断规则 (仅当无覆盖规则时生效) ===
    if not any("Rule4" in r or "Rule6" in r or "Rule7" in r for r in rules_fired):
        # Rule 2: 近3期和值极端
        if all(s <= 5 for s in sums_3):
            rules_fired.append(f"Rule2: 近3期和值极端小({sums_3}) -> 熔断")
            stop = True
        elif all(s >= 22 for s in sums_3):
            rules_fired.append(f"Rule2: 近3期和值极端大({sums_3}) -> 熔断")
            stop = True

        # Rule 3: 连续2期同形态 -> 观望
        if streak_len >= 2:
            rules_fired.append(f"Rule3: 连续{streak_len}期{streak_type} -> 观望熔断")
            stop = True

    return {
        "stop": stop,
        "rules_fired": rules_fired,
        "streak_type": streak_type,
        "streak_len": streak_len,
        "zl_streak": zl_streak,
        "gs_count_30": gs_count_30,
        "last2_both_gs": last2_both_gs,
        "sums_3": sums_3,
        "push_type": "组六",
        "push_count": 0 if stop else 10,
    }


def generate_report(history, pl, cb, recs, settlement, today_draw_qihao):
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
    rec_table = "\n".join(rec_rows) if rec_rows else "| - | 熔断未推 | - | - | - |"

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
        cb_detail = "- 无规则触发, 正常推荐\n"
    cb_status = "🛑 熔断(暂停)" if cb["stop"] else "✅ 正常推10注组六"

    # 结算信息
    settle_section = ""
    if settlement:
        rec_data, draw, hits, hit_list = settlement
        settle_section = f"""
### {rec_data['date']} 结算

| 项目 | 数值 |
|------|------|
| 开奖 | {draw['qihao']} → **{' '.join(map(str, draw['nums']))}** {draw['type']} |
| 推荐 | {rec_data['notes']}注组六 |
| 命中 | **{hits}注** {"🎯" if hits > 0 else ""} |
| 成本 | {rec_data['cost']}元 |
| 奖金 | {rec_data['prize']}元 |
| 日盈亏 | **{rec_data['daily_pnl']:+d}元** |
"""
        if hit_list:
            settle_section += f"\n> 🎯 命中推荐: {hit_list[0]}\n"

    s = pl["summary"]
    next_qihao = str(int(latest["qihao"]) + 1)

    report = f"""# 福彩3D 每日复盘报告
**日期: {TODAY}** | 期号: {latest['qihao']} 已开 → {next_qihao} 待开

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

| 日期 | 推荐数 | 成本 | 命中 | 奖金 | 当日盈亏 | 累计盈亏 |
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

---

## 四、今日推荐 ({len(recs)}注组六)

| # | 号码 | 和值 | 跨度 | 推导逻辑 |
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

    # 2. 加载P&L
    print("\n[2/7] 加载盈亏数据...")
    pl = load_json(PL_FILE)
    print(f"  追踪区间: {pl['start_date']} ~ {pl['end_date']}")
    print(f"  当前累计: {pl['summary']['net_pnl']:+d}元")

    # 3. 结算昨日待结算
    print("\n[3/7] 结算昨日推荐...")
    settlement = settle_pending(history, pl)

    # 4. 重新计算累计统计
    print("\n[4/7] 更新累计统计...")
    summary = calc_summary(pl)
    print(f"  已结算: {summary['settled_days']}天, 活跃: {summary['active_days']}天")
    print(f"  总注数: {summary['total_bets']}, 总命中: {summary['total_hits']}")
    print(f"  净盈亏: {summary['net_pnl']:+d}元, 待结算: {summary['pending_bets']}注")

    # 5. 熔断判定
    print("\n[5/7] 熔断判定...")
    cb = circuit_breaker_user_rules(history)
    print(f"  形态: {cb['streak_type']}{cb['streak_len']}连, 组六{cb['zl_streak']}连")
    print(f"  组三近30期: {cb['gs_count_30']}次")
    for rf in cb["rules_fired"]:
        print(f"  🔴 {rf}")
    print(f"  {'🛑 熔断, 0注' if cb['stop'] else '✅ 正常推10注组六'}")

    # 6. 生成推荐
    print("\n[6/7] 生成推荐...")
    if cb["stop"]:
        recs = []
        print("  熔断, 不推荐")
        reason = f"熔断触发({'; '.join(cb['rules_fired'])})"
    else:
        info = {"stop": False, "push_type": "组六", "push_count": 10}
        recs = generate_recommendations(history, info, count=10)
        print(f"  生成{len(recs)}注组六:")
        for i, r in enumerate(recs):
            print(f"    {i+1}. {' '.join(map(str, r['nums']))} | 和{r['sum_val']} 跨{r['span']} | {r['logic']}")
        reason = f"组六{len(recs)}注推荐 | " + "; ".join(cb["rules_fired"] if cb["rules_fired"] else ["正常推荐"])

    # 检查今天是否已有记录
    today_exists = any(r["date"] == TODAY for r in pl["records"])
    if today_exists:
        print(f"\n  今天({TODAY})已有记录, 跳过添加")
        # 更新现有记录的推荐 (如果熔断状态变化)
        for r in pl["records"]:
            if r["date"] == TODAY and r["hits"] is None:
                r["recommendations"] = [rec["nums"] for rec in recs]
                r["notes"] = len(recs)
                r["cost"] = len(recs) * 2
                r["reason"] = reason
                break
    else:
        # 添加今日记录
        today_rec = {
            "date": TODAY,
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
    report_path = generate_report(history, pl, cb, recs, settlement, latest["qihao"])

    # 摘要
    print(f"\n{'='*50}")
    print(f"  每日复盘完成 {TODAY}")
    print(f"{'='*50}")
    if settlement:
        print(f"  昨日结算: {settlement[2]}注命中, {settlement[0]['daily_pnl']:+d}元")
    print(f"  累计盈亏: {summary['net_pnl']:+d}元 ({summary['total_hits']}注命中)")
    print(f"  今日推荐: {len(recs)}注组六, 成本{len(recs)*2}元")
    print(f"  报告: {report_path}")
    print(f"  追踪期: {pl['start_date']} ~ {pl['end_date']}")


if __name__ == "__main__":
    main()
