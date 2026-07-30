"""
福彩3D 策略回测: 旧策略(每天10注组六) vs 新策略(形态自适应 v8)
遍历历史, 每天用"截至前一天"的数据做形态判定+选号, 与当天真实开奖对比。
history 为最新在前(同 daily_review.py 约定)。
"""
import json
import sys
from collections import Counter

sys.path.insert(0, ".")
from daily_review import circuit_breaker_user_rules
from analyze import generate_recommendations

history = json.load(open("data/3d_history.json", encoding="utf-8"))
N = len(history)
print(f"历史总期数: {N}\n")


def prize_of(draw):
    if draw["type"] == "组三":
        return 320
    if draw["type"] == "组六":
        return 160
    return 1040


def simulate_day(avail, draw, push_type, count):
    """返回 (盈亏, 命中注数)"""
    if count == 0:
        return 0, 0
    info = {"stop": False, "push_type": push_type, "push_count": count}
    recs = generate_recommendations(avail, info, count=count)
    dset = set(draw["nums"])
    hits = sum(1 for r in recs if set(r["nums"]) == dset)
    cost = len(recs) * 2
    return hits * prize_of(draw) - cost, hits


# 旧策略: 每天无脑10注组六 (造成-394元的核心行为)
old_total = 0
old_hits = 0
# 新策略: 形态自适应 v8
new_total = 0
new_hits = 0
new_zusan_days = 0
new_zuliu_days = 0
new_stop_days = 0
mismatch_old_days = 0  # 旧策略推组六却开组三(确定必亏)
days = 0

# 从后往前遍历, 要求已知历史>=30期才做形态判断(保证决策稳定)
for i in range(N - 1, 0, -1):
    avail = history[i + 1:]          # 截至 i 前一天的已知数据
    if len(avail) < 30:
        continue
    draw = history[i]                # 当天真实开奖
    days += 1

    # 旧: 10注组六
    p_old, h_old = simulate_day(avail, draw, "组六", 10)
    old_total += p_old
    old_hits += h_old
    if draw["type"] == "组三":
        mismatch_old_days += 1

    # 新: 形态自适应
    cb = circuit_breaker_user_rules(avail)
    if cb["stop"]:
        p_new, h_new = 0, 0
        new_stop_days += 1
    else:
        p_new, h_new = simulate_day(avail, draw, cb["push_type"], cb["push_count"])
        if cb["push_type"] == "组三":
            new_zusan_days += 1
        else:
            new_zuliu_days += 1
    new_total += p_new
    new_hits += h_new

print("=" * 52)
print(f"  回测样本: {days} 天 (已知历史>=30期)")
print("=" * 52)
print(f"  [旧] 每天10注组六:   净盈亏 {old_total:+d}元 | 命中 {old_hits}注")
print(f"       其中形态错配(推组六开组三) {mismatch_old_days} 天 (确定亏损)")
print(f"  [新] 形态自适应 v8:   净盈亏 {new_total:+d}元 | 命中 {new_hits}注")
print(f"       推组三 {new_zusan_days}天 | 推组六 {new_zuliu_days}天 | 熔断 {new_stop_days}天")
print("=" * 52)
delta = new_total - old_total
print(f"  新策略相对旧策略: {delta:+d}元 ({'更优' if delta > 0 else '未改善'})")
print("=" * 52)

# 分项: 旧策略在组三日的亏损 vs 新策略如何
print("\n[形态错配分析]")
print(f"  旧策略在 {mismatch_old_days} 个组三日全部必亏, 合计约 -{mismatch_old_days*20}元(成本)")
print("  新策略在组三密集期改推组三, 命中即按320元计, 可挽回部分损失。")
print("  注: 彩票为独立随机事件, 回测仅反映选号/形态策略的历史表现, 不代表未来收益。")
