"""
修正6/29结算 + 添加6/30结算
6/29推荐[0,5,8]命中2026170开奖805，之前错误结算为2026169=832
2026171=134 用于结算6/30推荐
"""
import json
from collections import Counter

PROFIT_FILE = "data/profit_loss.json"

with open(PROFIT_FILE, "r", encoding="utf-8") as f:
    data = json.load(f)

# 2026171 = 1,3,4 (组六, 和8, 跨3)
draw_171 = [1, 3, 4]

# ---- 修正 6/29 ----
for r in data["records"]:
    if r["date"] == "2026-06-29":
        # 正确开奖: 2026170 = 805
        r["draw"] = "2026170"
        r["draw_nums"] = [8, 0, 5]
        r["draw_type"] = "组六"
        # 重新计算命中
        hits = 0
        for rec in r["recommendations"]:
            if sorted(rec) == sorted([8, 0, 5]):
                hits += 1
                print(f"  🎯 命中: {rec} == {sorted([8,0,5])}")
        r["hits"] = hits
        r["prize"] = hits * data["prize_per_hit"]
        r["daily_pnl"] = r["prize"] - r["cost"]
        r["reason"] = f"组六10注→{hits}命中[0,5,8]开奖805组六" + (f"，奖金{r['prize']}元" if hits else "")
        print(f"  修正6/29: {r['notes']}注, {hits}命中, 盈亏{r['daily_pnl']}元")

# ---- 添加 6/30 结算 ----
for r in data["records"]:
    if r["date"] == "2026-06-30":
        r["draw"] = "2026171"
        r["draw_nums"] = draw_171
        r["draw_type"] = "组六"
        hits = 0
        for rec in r["recommendations"]:
            if sorted(rec) == sorted(draw_171):
                hits += 1
                print(f"  🎯 命中: {rec} == {sorted(draw_171)}")
        r["hits"] = hits
        r["prize"] = hits * data["prize_per_hit"]
        r["daily_pnl"] = r["prize"] - r["cost"]
        r["reason"] = f"组六{r['notes']}注→{hits}命中" + (f"，奖金{r['prize']}元" if hits else f"，未命中开奖134组六")
        print(f"  结算6/30: {r['notes']}注, {hits}命中, 盈亏{r['daily_pnl']}元")

# ---- 重新计算累计 ----
cumulative = 0
total_bets = 0
total_cost = 0
total_hits = 0
total_prize = 0
settled_count = 0
active_days = 0

for r in data["records"]:
    if r.get("daily_pnl") is not None:
        cumulative += r["daily_pnl"]
        total_bets += r["notes"]
        total_cost += r["cost"]
        total_hits += (r["hits"] or 0)
        total_prize += (r["prize"] or 0)
        settled_count += 1
        if r["notes"] > 0:
            active_days += 1

data["summary"] = {
    "total_days": len(data["records"]),
    "settled_days": settled_count,
    "active_days": active_days,
    "total_bets": total_bets,
    "total_cost": total_cost,
    "total_hits": total_hits,
    "total_prize": total_prize,
    "net_pnl": cumulative,
    "pending_bets": 0,
    "pending_cost": 0,
    "last_settled": "2026-06-30",
    "last_hit": "2026-06-29 1注 (修正)"
}

print(f"\n=== 最终汇总 ===")
print(f"总注数: {total_bets} | 命中: {total_hits} | 命中率: {total_hits/max(1,total_bets)*100:.1f}%")
print(f"总成本: {total_cost}元 | 总奖金: {total_prize}元 | 净盈亏: {cumulative}元")

with open(PROFIT_FILE, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
print("\nprofit_loss.json 已更新")
