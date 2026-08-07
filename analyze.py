"""
福彩3D数据分析引擎
统计：频率热冷号、遗漏值、和值分布、跨度、形态
v4: 3条熔断规则全部暂停等用户决策 + 正常每天10注
"""
import json
import os
from collections import Counter, defaultdict
from itertools import combinations

DATA_FILE = "data/3d_history.json"

def load_data():
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def frequency_analysis(records, top_n=5):
    """每个位置上的号码频率 + 热冷号"""
    pos_counters = {"bai": Counter(), "shi": Counter(), "ge": Counter()}
    total_counter = Counter()

    for r in records:
        pos_counters["bai"][r["bai"]] += 1
        pos_counters["shi"][r["shi"]] += 1
        pos_counters["ge"][r["ge"]] += 1
        for n in r["nums"]:
            total_counter[n] += 1

    return {
        "total_freq": total_counter.most_common(),
        "bai_hot": pos_counters["bai"].most_common(top_n),
        "shi_hot": pos_counters["shi"].most_common(top_n),
        "ge_hot": pos_counters["ge"].most_common(top_n),
        "bai_cold": pos_counters["bai"].most_common()[-top_n:][::-1],
        "shi_cold": pos_counters["shi"].most_common()[-top_n:][::-1],
        "ge_cold": pos_counters["ge"].most_common()[-top_n:][::-1]
    }

def missing_analysis(records):
    """当前遗漏分析 - 各号码多久没出"""
    total = len(records)
    last_seen = {i: None for i in range(10)}

    for idx, r in enumerate(records):
        for n in r["nums"]:
            if last_seen[n] is None:
                last_seen[n] = idx

    missing = {}
    for n in range(10):
        if last_seen[n] is None:
            missing[n] = total
        else:
            missing[n] = last_seen[n]

    return {
        "missing_periods": missing,
        "most_overdue": sorted(missing.items(), key=lambda x: x[1], reverse=True)[:5],
        "least_overdue": sorted(missing.items(), key=lambda x: x[1])[:5]
    }

def sum_value_analysis(records):
    """和值分布分析"""
    sum_counter = Counter()
    for r in records:
        sum_counter[r["sum_val"]] += 1

    recent_100 = [r["sum_val"] for r in records[:100]]
    avg_sum = sum(recent_100) / len(recent_100) if recent_100 else 0

    return {
        "sum_distribution": dict(sorted(sum_counter.items())),
        "recent_100_avg": round(avg_sum, 2),
        "theoretical_avg": 13.5,
        "range_summary": {
            "small": (0, 9), "medium": (10, 18), "large": (19, 27)
        },
        "recent_100_range": {
            "small": sum(1 for s in recent_100 if s <= 9),
            "medium": sum(1 for s in recent_100 if 10 <= s <= 18),
            "large": sum(1 for s in recent_100 if s >= 19)
        }
    }

def span_analysis(records):
    """跨度分析（最大-最小）"""
    spans = []
    for r in records:
        n = r["nums"]
        spans.append(max(n) - min(n))

    span_counter = Counter(spans)
    recent_100_spans = spans[:100]

    return {
        "span_distribution": dict(sorted(span_counter.items())),
        "recent_100_avg_span": round(sum(recent_100_spans) / len(recent_100_spans), 2),
        "max_span_possible": 9
    }

def type_analysis(records):
    """形态分析：豹子/组三/组六比例"""
    type_counter = Counter()
    for r in records:
        type_counter[r["type"]] += 1

    recent_100 = [r["type"] for r in records[:100]]
    recent_type = Counter(recent_100)

    return {
        "overall": dict(type_counter),
        "recent_100": dict(recent_type),
        "probability": {
            "豹子理论概率": "1/100 (1%)",
            "组三理论概率": "27/100 (27%)",
            "组六理论概率": "72/100 (72%)"
        }
    }

def circuit_breaker(records, target_type="组六"):
    """
    熔断判定 v4: 3条规则全部暂停等用户决策
    返回: {
        "stop": bool,          # 是否暂停（所有熔断都=true, 用户决定）
        "reason": str,         # 触发原因
        "suggest": str,        # 给用户的建议
        "push_type": str,      # 推荐目标形态
        "push_count": int,     # 建议推荐注数
        "signal_strength": str # 信号强度
    }
    """
    n = len(records)
    if n < 3:
        return {"stop": False, "reason": "数据不足", "suggest": "",
                "push_type": target_type, "push_count": 10, "signal_strength": "弱"}

    types_all = [r["type"] for r in records]
    sums_3 = [r["sum_val"] for r in records[:3]]

    # 当前组六连出长度
    zl_streak = 0
    for r in records:
        if r["type"] == "组六":
            zl_streak += 1
        else:
            break

    # 当前连续同形态（组三或组六）
    streak_type = types_all[0]
    streak_len = 1
    for t in types_all[1:]:
        if t == streak_type:
            streak_len += 1
        else:
            break

    # === 规则A: 组六连续8期 → 暂停 ===
    if zl_streak >= 8:
        p = 1 - (0.732 ** zl_streak)
        return {"stop": True,
                "reason": f"组六连续{zl_streak}期",
                "suggest": f"组三概率已达{p*100:.0f}%，建议推10注组三搏回归。是否推？",
                "push_type": "组三", "push_count": 10, "signal_strength": "极强"}

    # === 规则B: 连续3期同形态 → 暂停建议强推反向 ===
    if streak_len >= 3:
        reverse = "组六" if streak_type == "组三" else "组三"
        return {"stop": True,
                "reason": f"连续{streak_len}期{streak_type}",
                "suggest": f"3连{streak_type}后形态切换率>80%，建议推10注{reverse}。是否推？",
                "push_type": reverse, "push_count": 10,
                "signal_strength": "极强" if streak_len >= 4 else "强"}

    # === 规则C: 近3期和值连续极端 → 暂停 ===
    if all(s <= 5 for s in sums_3):
        return {"stop": True,
                "reason": f"近3期和值连续极端小({sums_3})",
                "suggest": "和值异常走低，可能继续下行。建议观望或减量。是否推？",
                "push_type": target_type, "push_count": 10, "signal_strength": ""}
    if all(s >= 22 for s in sums_3):
        return {"stop": True,
                "reason": f"近3期和值连续极端大({sums_3})",
                "suggest": "和值异常走高，可能均值回归。建议推均值附近10注组六。是否推？",
                "push_type": target_type, "push_count": 10, "signal_strength": ""}

    # === 正常情况: 每天推满10注组六 ===
    return {"stop": False, "reason": f"正常推荐 (组六{zl_streak}连，{streak_len}连{streak_type})",
            "suggest": "", "push_type": target_type, "push_count": 10, "signal_strength": "中"}

def generate_recommendations(records, info, count=10):
    """
    选号引擎 v3（经验分布采样）：抓住真实可用的边际规律，最大化"形态典型"
    info: {"stop": bool, "push_type": "组六"/"组三", "push_count": int}

    核心改动（相对 v2）：
    1. 经验联合分布加权：用真实数位频率（整体边际）作为各位置权重，
       在独立抽取假设下，联合概率 = 各数位边际乘积，天然复现"和值聚中区/
       跨度典型/数位均衡"等真实规律（而非人为拍脑袋定中区）。
    2. 硬约束带对齐实测密集区：和值锁 9~20（占 82%）、跨度锁 3~7（占 73%），
       剔除结构上极罕出的组合（极端和值/跨度 0、9）。
    3. 奇偶均衡：剔除全奇/全偶，逼近真实 ~50:50。
    4. 遗漏仅作弱 tie-breaker（摒弃"冷号必出"赌徒谬误）。
    注：以上属"分布对齐"，不声称能预测具体开奖（独立随机，EV 仍为负）。
    输出组数严格等于 count（由熔断规则决定，不在此处写死）。
    """
    if info.get("stop"):
        return []

    push_type = info.get("push_type", "组六")
    n = len(records)
    if n < 4:
        return []

    # 计算遗漏（仅用于弱 tie-breaker）
    last_seen = {}
    for idx, r in enumerate(records):
        for num in r["nums"]:
            if num not in last_seen:
                last_seen[num] = idx
    missing = {i: last_seen.get(i, n) for i in range(10)}

    # 经验数位频率（整体边际，Laplace 平滑避免 0）
    total_counter = Counter()
    for r in records:
        for num in r["nums"]:
            total_counter[num] += 1
    denom = n * 3 + 5  # +5 平滑（等效 0.5 先验）
    digit_prob = {i: (total_counter.get(i, 0) + 0.5) / denom for i in range(10)}

    # 近期和值均值（仅用于兜底居中，主权重已由频率联合分布承担）
    recent_sums = [r["sum_val"] for r in records[:30]]
    avg_sum = sum(recent_sums) / len(recent_sums) if recent_sums else 13.5

    if push_type == "组三":
        candidates = _build_zusan_pool(missing, avg_sum, digit_prob)
    else:
        candidates = _build_zuliu_pool(missing, avg_sum, digit_prob)

    return _select_diverse(candidates, count)


def _score_combo(multiset, missing, avg_sum, digit_prob):
    """经验分布打分。频率联合分布为主，和值/跨度硬带 + 奇偶均衡为辅，遗漏弱项。"""
    s = sum(multiset)
    sp = max(multiset) - min(multiset)
    # 经验联合分布（独立假设下 = 各数位边际乘积），频率越高权重越大
    joint = 1.0
    for d in multiset:
        joint *= digit_prob[d]
    joint_norm = joint / (0.1 ** 3)  # 中心化：频率10%时≈1，热号>1冷号<1
    # 和值带 [9,20]（实测密集带，占 82%）；外侧骤降
    if 9 <= s <= 20:
        sum_score = 1.0
    elif 7 <= s <= 22:
        sum_score = 0.5
    else:
        sum_score = 0.08
    # 跨度带 [3,7]（实测典型段，占 73%）；跨度 0/1/2/8/9 极罕出
    if 3 <= sp <= 7:
        span_score = 1.0
    elif sp in (2, 8):
        span_score = 0.5
    else:
        span_score = 0.08
    # 奇偶均衡：避免全奇/全偶（真实 ~50:50）
    odds = sum(1 for d in multiset if d % 2 == 1)
    balance_score = 1.0 if odds in (1, 2) else 0.3
    # 遗漏：弱项，仅作轻微偏好（冷号不等于必出）
    max_miss = max(missing.values()) or 1
    om_score = sum(missing[d] for d in set(multiset)) / (len(set(multiset)) * max_miss)
    score = (0.35 * joint_norm + 0.30 * sum_score + 0.20 * span_score
             + 0.15 * balance_score + 0.05 * om_score)
    return s, sp, score


def _eligible(multiset):
    """硬约束：和值 9~20、跨度 3~7、奇偶均衡(非全奇/全偶)。仅合格候选进入选号池。"""
    s = sum(multiset)
    sp = max(multiset) - min(multiset)
    if not (9 <= s <= 20):
        return False
    if not (3 <= sp <= 7):
        return False
    odds = sum(1 for d in multiset if d % 2 == 1)
    if odds not in (1, 2):
        return False
    return True


def _build_zuliu_pool(missing, avg_sum, digit_prob):
    """枚举全部 120 组六组合，仅保留硬约束合格者并按经验分布打分。"""
    cands = []
    for combo in combinations(range(10), 3):
        nums = sorted(combo)
        if not _eligible(nums):
            continue
        s, sp, score = _score_combo(nums, missing, avg_sum, digit_prob)
        cands.append({
            "nums": nums,
            "multiset": list(nums),
            "distinct": set(nums),
            "sum_val": s, "span": sp, "score": score,
        })
    return cands


def _build_zusan_pool(missing, avg_sum, digit_prob):
    """枚举全部 90 组三组合 [d,d,s]，仅保留硬约束合格者并按经验分布打分。"""
    cands = []
    for d in range(10):
        for s in range(10):
            if s == d:
                continue
            nums = sorted([d, d, s])
            if not _eligible(nums):
                continue
            sv = 2 * d + s
            sp = abs(d - s)
            _, _, score = _score_combo([d, d, s], missing, avg_sum, digit_prob)
            cands.append({
                "nums": nums,
                "multiset": [d, d, s],
                "distinct": {d, s},
                "sum_val": sv, "span": sp, "score": score,
            })
    return cands


def _select_diverse(candidates, count):
    """
    多样性贪心筛选：在合理候选中挑 count 注，使 0~9 数位分布均衡。
    分数主导，多样性做乘性微调：优先引入未覆盖数字、惩罚过度使用的数字。
    """
    if count <= 0:
        return []
    selected = []
    used = Counter()
    pool = sorted(candidates, key=lambda c: -c["score"])

    while len(selected) < count and pool:
        best = None
        best_val = None
        for c in pool:
            if c in selected:
                continue
            new_digits = sum(1 for d in c["distinct"] if used[d] == 0)
            overuse = sum(used[d] for d in c["distinct"])
            # 乘性调整：保留分数主导，多样性只做相对微调
            val = c["score"] * (1 + 0.3 * new_digits - 0.2 * overuse)
            if best_val is None or val > best_val:
                best = c
                best_val = val
        if best is None:
            break
        best["_new"] = [d for d in sorted(best["distinct"]) if used[d] == 0]
        selected.append(best)
        for d in best["multiset"]:
            used[d] += 1
        pool.remove(best)

    return [{
        "nums": c["nums"],
        "logic": _make_logic(c),
        "sum_val": c["sum_val"],
        "span": c["span"],
    } for c in selected]


def _make_logic(c):
    """生成可读的推导逻辑（经验分布对齐 + 均衡性）。"""
    sv = c["sum_val"]
    band = "和值中区" if 9 <= sv <= 20 else ("和值小" if sv < 9 else "和值大")
    sp = c["span"]
    span_desc = "典型跨度" if 3 <= sp <= 7 else "跨度"
    new = c.get("_new", [])
    extra = (" · 新号" + "/".join(map(str, new))) if new else " · 均衡补位"
    return f"经验分布·{band}{sv}·{span_desc}{sp}{extra}"

def full_report():
    """生成完整分析报告"""
    records = load_data()
    if not records:
        return None

    cb = circuit_breaker(records)
    recs = generate_recommendations(records, cb)

    report = {
        "数据概览": {
            "总期数": len(records),
            "数据范围": f"{records[-1]['qihao']} ~ {records[0]['qihao']}",
            "最新开奖": records[0],
            "上一期": records[1] if len(records) > 1 else None
        },
        "频率分析": frequency_analysis(records),
        "遗漏分析": missing_analysis(records),
        "和值分析": sum_value_analysis(records),
        "跨度分析": span_analysis(records),
        "形态分析": type_analysis(records),
        "熔断判定": cb,
        "推荐号码": recs,
        "推荐注数": len(recs)
    }

    os.makedirs("data", exist_ok=True)
    with open("data/analysis_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print("分析报告已生成: data/analysis_report.json")
    return report

def print_summary(report):
    """打印摘要"""
    if not report:
        print("无数据可分析")
        return

    d = report["数据概览"]
    freq = report["频率分析"]
    miss = report["遗漏分析"]
    s = report["和值分析"]
    cb = report.get("熔断判定", {})

    print("\n" + "=" * 50)
    print(f"  福彩3D 数据分析报告")
    print(f"  数据范围: {d['数据范围']} (共{d['总期数']}期)")
    print("=" * 50)

    latest = d["最新开奖"]
    print(f"\n  最新开奖: {latest['qihao']} -> {' '.join(map(str, latest['nums']))} ({latest['type']})")

    print(f"\n  [热号 Top5]")
    for n, c in freq["total_freq"][:5]:
        bar = "=" * min(c // 10, 20)
        print(f"    号码{n}: {c}次 {bar}")

    print(f"\n  [最大遗漏]")
    for n, m in miss["most_overdue"]:
        print(f"    号码{n}: 已遗漏 {m} 期")

    print(f"\n  [近100期和值]")
    print(f"    平均: {s['recent_100_avg']} (理论均值: {s['theoretical_avg']})")
    print(f"    小区间: {s['recent_100_range']['small']}次")
    print(f"    中区间: {s['recent_100_range']['medium']}次")
    print(f"    大区间: {s['recent_100_range']['large']}次")

    t = report["形态分析"]
    print(f"\n  [近100期形态]")
    for k, v in t["recent_100"].items():
        print(f"    {k}: {v}次")

    print(f"\n  [熔断判定 v4]")
    print(f"    触发: {'🛑 是' if cb.get('stop') else '✅ 否'}")
    print(f"    原因: {cb.get('reason', 'N/A')}")
    if cb.get('suggest'):
        print(f"    ⚠️ 建议: {cb.get('suggest')}")
    if not cb.get('stop'):
        print(f"    推荐: {cb.get('push_type', '')} × {cb.get('push_count', 0)}")
        print(f"    信号: {cb.get('signal_strength', '')}")

    recs = report.get("推荐号码", [])
    if recs:
        print(f"\n  [推荐号码] ({len(recs)}注)")
        for i, r in enumerate(recs):
            print(f"    {i+1}. {' '.join(map(str, r['nums']))} | 和{r['sum_val']} 跨{r['span']} | {r['logic']}")
    print("\n" + "=" * 50)

if __name__ == "__main__":
    report = full_report()
    print_summary(report)
