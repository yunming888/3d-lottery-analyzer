# -*- coding: utf-8 -*-
"""读取大乐透/双色球现有持仓（沿用原选号逻辑，不换号），输出下一期组合与分布统计。"""
import json
import os

BASE = os.path.dirname(os.path.abspath(__file__))


def load_state(f):
    return json.load(open(os.path.join(BASE, "data", f), encoding="utf-8"))


def fmt(nums):
    return " ".join(f"{n:02d}" for n in nums)


def dist(nums, zones, big_min, label):
    odd = sum(1 for n in nums if n % 2)
    big = sum(1 for n in nums if n >= big_min)
    zc = {name: sum(1 for n in nums if lo <= n <= hi) for name, (lo, hi) in zones.items()}
    return {"odd": odd, "even": len(nums) - odd,
            "big": big, "small": len(nums) - big,
            "zone": zc, "sum": sum(nums), "mean": round(sum(nums) / len(nums), 1)}


# ---- 大乐透 ----
d = load_state("dlt_state.json")
pend = [r for r in d["records"] if r.get("status") != "settled"]
target = pend[-1]["target_issue"] if pend else "—"
last_draw = max((r.get("draw_issue") or "0") for r in d["records"])
print(f"=== 大乐透 ===  最近已结算期: {last_draw}  下一期目标: {target}")
allf, allb = [], []
for i, p in enumerate(d["portfolio"], 1):
    print(f"  {i}. 前区 {fmt(p['reds'])}  后区 {fmt(p['blues'])}")
    allf += p["reds"]
    allb += p["blues"]
df = dist(allf, {"一区(01-12)": (1, 12), "二区(13-24)": (13, 24), "三区(25-35)": (25, 35)}, 18, "前区")
db = dist(allb, {"小(01-06)": (1, 6), "大(07-12)": (7, 12)}, 7, "后区")
print(f"  前区分布: 奇{df['odd']}/偶{df['even']}  大(≥18){df['big']}/小{df['small']}  区间 {df['zone']}")
print(f"  前区和值: {df['sum']}  单注均值 {df['mean']}；后区: 奇{db['odd']}/偶{db['even']} 大(≥7){db['big']}/小{db['small']}")
print(f"  核心价值号: {json.load(open(os.path.join(BASE,'data','hot_core.json'),encoding='utf-8'))['dlt']['core_red']}"
      f"（每注必含，core_ym={d['core_ym']}）")

# ---- 双色球 ----
s = load_state("ssq_state.json")
pend = [r for r in s["records"] if r.get("status") != "settled"]
target = pend[-1]["target_issue"] if pend else "—"
last_draw = max((r.get("draw_issue") or "0") for r in s["records"])
print(f"\n=== 双色球 ===  最近已结算期: {last_draw}  下一期目标: {target}")
allr, all_bl = [], []
for i, p in enumerate(s["portfolio"], 1):
    print(f"  {i}. 红球 {fmt(p['reds'])}  蓝球 {fmt(p['blues'])}")
    allr += p["reds"]
    all_bl += p["blues"]
dr = dist(allr, {"一区(01-11)": (1, 11), "二区(12-22)": (12, 22), "三区(23-33)": (23, 33)}, 17, "红球")
dbl = dist(all_bl, {"小(01-08)": (1, 8), "大(09-16)": (9, 16)}, 9, "蓝球")
print(f"  红球分布: 奇{dr['odd']}/偶{dr['even']}  大(≥17){dr['big']}/小{dr['small']}  区间 {dr['zone']}")
print(f"  红球和值: {dr['sum']}  单注均值 {dr['mean']}；蓝球: 奇{dbl['odd']}/偶{dbl['even']} 大(≥9){dbl['big']}/小{dbl['small']}")
print(f"  核心价值号: {json.load(open(os.path.join(BASE,'data','hot_core.json'),encoding='utf-8'))['ssq']['core_red']}"
      f"（每注必含，core_ym={s['core_ym']}）")
