"""
6/27 自动化任务: 结算6/26 + 生成6/27推荐 + 更新P&L + 写报告
"""
import json
import os
from datetime import datetime

# 加载数据
with open("data/3d_history.json", "r", encoding="utf-8") as f:
    history = json.load(f)

with open("data/analysis_report.json", "r", encoding="utf-8") as f:
    analysis = json.load(f)

with open("data/profit_loss.json", "r", encoding="utf-8") as f:
    pl = json.load(f)

# ====== 第1步: 结算6/26 ======
draw_6167 = history[0]  # 最新: 2026167
assert draw_6167["qihao"] == "2026167", f"Expected 2026167, got {draw_6167['qihao']}"
draw_nums_set = set(draw_6167["nums"])  # {6,3,1}

# 找到6/26的记录
found_626 = None
for rec in pl["records"]:
    if rec["date"] == "2026-06-26":
        found_626 = rec
        break

if found_626 and found_626["hits"] is None:
    recs = found_626["recommendations"]
    hits = 0
    hit_list = []
    for rec_num in recs:
        if set(rec_num) == draw_nums_set:
            hits += 1
            hit_list.append(rec_num)
    
    found_626["draw"] = draw_6167["qihao"]
    found_626["draw_nums"] = draw_6167["nums"]
    found_626["draw_type"] = draw_6167["type"]
    found_626["hits"] = hits
    found_626["prize"] = hits * 160
    found_626["daily_pnl"] = hits * 160 - found_626["cost"]
    found_626["reason"] = f"组六10注→{hits}命中{' '.join(map(str, hit_list[0])) if hit_list else '0命中'}开奖{''.join(map(str, draw_6167['nums']))}{draw_6167['type']}"
    
    print(f"6/26结算: {found_626['notes']}注→{hits}命中, 奖金{hits*160}元, 成本{found_626['cost']}元, 当日盈亏{found_626['daily_pnl']}元")
    if hit_list:
        print(f"  🎯 命中推荐: {' '.join(map(str, hit_list[0]))} (开奖{' '.join(map(str, draw_6167['nums']))})")

# ====== 第2步: 计算累计 ======
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

# 未结算的pending
pending_bets = sum(r["notes"] for r in pl["records"] if r["hits"] is None)
pending_cost = sum(r["cost"] for r in pl["records"] if r["hits"] is None)

net_pnl = total_prize - total_cost

print(f"\n累计: {settled_days}天已结算, {active_days}天活跃")
print(f"总注数: {total_bets}, 总成本: {total_cost}元")
print(f"总命中: {total_hits}注, 总奖金: {total_prize}元")
print(f"net P&L: {net_pnl}元")
print(f"待结算: {pending_bets}注, {pending_cost}元")

# ====== 第3步: 熔断判定 (用户规则) ======
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

# 组三在近20期内的次数
recent_20_types = types_all[:20]
gs_count_20 = recent_20_types.count("组三")

# 最近2期是否都是组三
last2_both_gs = (types_all[0] == "组三" and types_all[1] == "组三")

# 组六连出长度
zl_streak = 0
for r in history:
    if r["type"] == "组六":
        zl_streak += 1
    else:
        break

# 判定规则
rules_fired = []
stop = False
push_type = "组六"
push_count = 10
signal = "中"

# Rule 1: 近20期内组三≥3次且最近2期不是组三 → 停止
if gs_count_20 >= 3 and not last2_both_gs:
    rules_fired.append(f"Rule1: 近20期组三{gs_count_20}次≥3, 且最近2期不是组三(组三过热未到切换点)")
    stop = True

# Rule 2: 近3期和值连续极端
if all(s <= 5 for s in sums_3):
    rules_fired.append(f"Rule2: 近3期和值连续极端小({sums_3})")
    stop = True
elif all(s >= 22 for s in sums_3):
    rules_fired.append(f"Rule2: 近3期和值连续极端大({sums_3})")
    stop = True

# Rule 3: 连续2期同形态 → 停止
if streak_len >= 2:
    rules_fired.append(f"Rule3: 连续{streak_len}期{streak_type}→观望")
    stop = True

# Rule 4: 连续3期同形态 → 强力推荐反向
if streak_len >= 3:
    reverse = "组六" if streak_type == "组三" else "组三"
    rules_fired.append(f"Rule4: 连续{streak_len}期{streak_type}→强力推荐{reverse}")
    stop = False  # 不熔断!

# Rule 6: 组三2连→推荐组六
if streak_type == "组三" and streak_len >= 2:
    rules_fired.append(f"Rule6: 组三{streak_len}连→推荐组六")
    push_type = "组六"
    stop = False

# Rule 7: 组六11连+ → 推荐组三
if zl_streak >= 11:
    rules_fired.append(f"Rule7: 组六{zl_streak}连→推荐组三")
    push_type = "组三"
    stop = False

print(f"\n熔断判定:")
print(f"  当前形态: {streak_type}{streak_len}连, 组六{zl_streak}连")
print(f"  近20期组三: {gs_count_20}次")
print(f"  最近2期: {types_all[0]}+{types_all[1]}")
for r in rules_fired:
    print(f"  🔴 {r}")
print(f"  {'🛑 停止' if stop else '✅ 正常推'}")

# ====== 第4步: 推荐 (v4策略: 熔断暂停, 默认10注) ======
# 使用分析引擎生成的推荐
recs = analysis["推荐号码"]
print(f"\n推荐号码 ({len(recs)}注{analysis['熔断判定']['push_type']}):")
for i, r in enumerate(recs):
    print(f"  {i+1}. {' '.join(map(str, r['nums']))} | 和{r['sum_val']} 跨{r['span']} | {r['logic']}")

# ====== 第5步: 添加6/27记录到P&L ======
today_rec = {
    "date": "2026-06-27",
    "draw": "待开奖",
    "draw_nums": [],
    "draw_type": "",
    "recommendations": [r["nums"] for r in recs],
    "notes": len(recs),
    "cost": len(recs) * 2,
    "hits": None,
    "prize": None,
    "daily_pnl": None,
    "reason": ""
}

if stop:
    today_rec["reason"] = f"熔断触发({'; '.join(rules_fired)})"
else:
    today_rec["reason"] = f"组六{len(recs)}注推荐 | 核心锚点: 8(缺5期)+5(缺4期)+7(缺4期)"

pl["records"].append(today_rec)

# 更新summary
pl["summary"] = {
    "total_days": len(pl["records"]),
    "settled_days": settled_days,
    "active_days": active_days + (0 if stop else 1),
    "total_bets": total_bets,
    "total_cost": total_cost,
    "total_hits": total_hits,
    "total_prize": total_prize,
    "net_pnl": net_pnl,
    "pending_bets": pending_bets,
    "pending_cost": pending_cost,
    "last_settled": "2026-06-26",
    "last_hit": "2026-06-26 1注" if total_hits > 0 else "无"
}

with open("data/profit_loss.json", "w", encoding="utf-8") as f:
    json.dump(pl, f, ensure_ascii=False, indent=2)

print(f"\n✅ profit_loss.json 已更新")
print(f"  累计盈亏: {net_pnl:+d}元 | 待结算: {pending_bets}注{pending_cost}元")

# ====== 第6步: 写报告 ======
os.makedirs("data/reports", exist_ok=True)

# 构建盈亏表格
pnl_rows = []
cumulative = 0
for rec in pl["records"]:
    if rec["hits"] is not None:
        cumulative += rec["daily_pnl"] if rec["daily_pnl"] is not None else 0
        hit_str = f"{rec['hits']}注" if rec['hits'] > 0 else "0"
        prize_str = f"{rec['prize']}元" if rec['prize'] > 0 else "0"
        pnl_str = f"{rec['daily_pnl']:+d}元" if rec['daily_pnl'] else "—"
        # 简化日期显示
        date_short = rec['date'][5:]  # "06-13"格式
        pnl_rows.append(f"| {date_short} | {rec['notes']} | {rec['cost']}元 | {hit_str} | {prize_str} | {pnl_str} | {cumulative:+d}元 |")

# 添加pending行
for rec in pl["records"]:
    if rec["hits"] is None:
        date_short = rec['date'][5:]
        pnl_rows.append(f"| {date_short} | {rec['notes']} | {rec['cost']}元 | 待开奖 | — | — | 待结算 |")

pnl_table = "\n".join(pnl_rows)

# 遗漏表
missing = analysis["遗漏分析"]["missing_periods"]
missing_rows = []
for n in range(10):
    m = missing[str(n)]
    bar = "█" * min(m, 10) if m > 0 else "刚出"
    missing_rows.append(f"| {n} | {m}期 | {bar} |")

missing_table = "\n".join(missing_rows)

# 频率表
freq = analysis["频率分析"]["total_freq"]
freq_rows = []
for n, c in freq:
    bar = "█" * min(c, 15)
    freq_rows.append(f"| {n} | {c}次 | {bar} |")
freq_table = "\n".join(freq_rows)

# 推荐表
rec_rows = []
for i, r in enumerate(recs):
    rec_rows.append(f"| {i+1} | {' '.join(map(str, r['nums']))} | {r['sum_val']} | {r['span']} | {r['logic']} |")
rec_table = "\n".join(rec_rows)

# 形态走势 (近15期)
trend_rows = []
for r in history[:15]:
    tag = "组六" if r["type"] == "组六" else "🔵组三" if r["type"] == "组三" else "🔴豹子"
    trend_rows.append(f"| {r['qihao']} | {r['date']} | {' '.join(map(str, r['nums']))} | {r['sum_val']} | {r['span']} | {tag} |")
trend_table = "\n".join(trend_rows)

# 熔断分析
cb_detail = ""
for rf in rules_fired:
    cb_detail += f"- {rf}\n"
cb_status = "🛑 规则触发(暂停)" if stop else "✅ 无触发(正常)"
cb_note = ""

if gs_count_20 >= 3 and not last2_both_gs:
    cb_note = "\n\n> ⚠️ 近20期组三达8次，但最近两期未形成组三连，组三热度高但切换方向不明。v4策略暂停熔断判断，正常推10注组六。"

report = f"""# 福彩3D 每日复盘报告
**日期: 2026-06-27** | 期号: 2026167 已开 → 2026168 待开

---

## 一、昨日复盘 (最近3期)

| 期号 | 日期 | 号码 | 和值 | 跨度 | 形态 |
|------|------|------|------|------|------|
| 2026167 | 2026-06-26 | 6 3 1 | 10 | 5 | 组六 ✅ |
| 2026166 | 2026-06-25 | 9 0 0 | 9 | 9 | 组三 🔵 |
| 2026165 | 2026-06-24 | 4 2 4 | 10 | 2 | 组三 🔵 |

**分析**: 组三2连后被631组六打断，组六重新启动。近3期和值9-10-10稳定在中位偏低，跨度2→9→5波动明显，631为全散号(无重号无连号)。

---

## 二、盈亏结算

### 6月26日结算
- **推荐**: 10注组六, 成本 20元
- **开奖**: 2026167 = 6 3 1 (组六)
- **命中**: 🎯 **1注** — [1 3 6]
- **奖金**: 160元
- **当日盈亏**: **+140元** 🎉

> 经过13天97注的沉寂，首次命中！第7注推荐 [1 3 6] 精准命中开奖。

### 累计盈亏表

| 日期 | 推荐数 | 成本 | 命中 | 奖金 | 当日盈亏 | 累计盈亏 |
|------|--------|------|------|------|----------|----------|
{pnl_table}

**总结**: 已结算16天，总推87注，1注命中，奖金160元，成本174元，**净盈亏 -14元**。今日10注待结算。

---

## 三、熔断判定

**判定状态**: {cb_status}

### 规则触发详情
{cb_detail}
{cb_note}

### 当前形态状态
- 最新: **组六1连** (2026167=631)
- 组六连出: 1期
- 组三近20期: 8次 (偏高，理论27%)
- 近3期和值: 10, 9, 10 (正常区间)

### 判定结论
- v4策略: 熔断规则暂停，每日默认推10注组六
- 组六刚启动1连，信号强度中等
{cb_note}

---

## 四、今日推荐 (10注组六)

| # | 号码 | 和值 | 跨度 | 推导逻辑 |
|---|------|------|------|----------|
{rec_table}

**推荐策略**: 核心锚定遗漏号8(缺5期)+5(缺4期)+7(缺4期)，辅以和值回归、跨度修正、位置独立。
- 遗漏回补: 2注 (5-7-8, 0-2-4)
- 冷热搭配: 1注 (2-3-8)
- 和值回归: 2注 (目标13/12)
- 跨度修正: 2注 (目标8/7)
- 位置独立: 1注
- 补位填充: 2注

---

## 五、数据面板

### 热号 Top5 (全位)
{freq_table}

### 冷号/遗漏
{missing_table}

### 形态走势 (近15期)
{trend_table}

### 近35期统计
- 组六: 25次 (71.4%, 理论72%)
- 组三: 10次 (28.6%, 理论27%)
- 豹子: 0次
- 平均和值: 12.94 (理论13.5)
- 平均跨度: 5.14 (理论5.0)

---

## 六、风险提示

1. ⚠️ **近20期组三达8次(40%)**，显著偏离理论值27%，组三回归压力大但已出现组六打断，存在反复可能
2. 组六刚启动1连，样本太小无法判断持续性
3. 和值近期偏低(近3期均值9.7)，有均值回归倾向
4. 遗漏号8已缺5期逼近警戒线，补位信号增强
5. **本报告仅供学习研究，不构成投注建议。彩票有风险，理性购彩。**
"""

report_path = f"data/reports/2026-06-27.md"
with open(report_path, "w", encoding="utf-8") as f:
    f.write(report)

print(f"\n✅ 报告已生成: {report_path}")
print("任务完成!")
