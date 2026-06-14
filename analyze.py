"""
福彩3D数据分析引擎
统计：频率热冷号、遗漏值、和值分布、跨度、形态
v2: 熔断规则修订(三连同形态→强推反向) + 自动推荐生成
"""
import json
import os
from collections import Counter, defaultdict

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
    熔断判定 + 信号强度分析（修订版 v2）
    返回: {
        "stop": bool,          # 是否熔断停推
        "reason": str,         # 原因
        "force_push": bool,    # 是否强推反向
        "push_type": str,      # 推荐目标形态
        "push_count": int,     # 建议推荐注数（0=不推荐，10=满推）
        "signal_strength": str # 信号强度: 弱/中/强/极强
    }
    """
    n = len(records)
    if n < 10:
        return {"stop": False, "reason": "数据不足", "force_push": False,
                "push_type": target_type, "push_count": 10, "signal_strength": "弱"}

    types_20 = [r["type"] for r in records[:20]]
    sums_3 = [r["sum_val"] for r in records[:3]]
    types_all = [r["type"] for r in records]

    # 统计近20期组三
    zs_count_20 = types_20.count("组三")

    # 最近的形态序列（连续同形态）
    streak_type = types_20[0]
    streak_len = 1
    for t in types_20[1:]:
        if t == streak_type:
            streak_len += 1
        else:
            break

    # 最后2期是否都不是组三
    last2_non_zs = all(t != "组三" for t in types_20[:2])

    # === 规则1: 近20期组三>3 且 最近2期都不是组三 → 停止 ===
    if zs_count_20 >= 3 and last2_non_zs:
        return {"stop": True, "reason": f"组三过热({zs_count_20}/20次)且近2期已转组六，观望",
                "force_push": False, "push_type": "", "push_count": 0, "signal_strength": ""}

    # === 规则2: 近3期和值连续极端 → 停止 ===
    if all(s <= 5 for s in sums_3):
        return {"stop": True, "reason": f"近3期和值连续极端小({sums_3})",
                "force_push": False, "push_type": "", "push_count": 0, "signal_strength": ""}
    if all(s >= 22 for s in sums_3):
        return {"stop": True, "reason": f"近3期和值连续极端大({sums_3})",
                "force_push": False, "push_type": "", "push_count": 0, "signal_strength": ""}

    # === 规则3: 连续2期同形态 → 观望 ===
    if streak_len == 2:
        return {"stop": True, "reason": f"连续2期{streak_type}，观望一期",
                "force_push": False, "push_type": "", "push_count": 0, "signal_strength": ""}

    # === 规则4: 连续3期同形态 → 强推反向！（不熔断，推满） ===
    if streak_len == 3:
        push_type = "组六" if streak_type == "组三" else "组三"
        return {"stop": False, "reason": f"连续3期{streak_type}→强推反向{push_type}",
                "force_push": True, "push_type": push_type, "push_count": 10, "signal_strength": "强"}

    # === 规则5: 连续4期以上同形态 → 超级强推 ===
    if streak_len >= 4:
        push_type = "组六" if streak_type == "组三" else "组三"
        extra = streak_len - 3
        return {"stop": False,
                "reason": f"连续{streak_len}期{streak_type}→强力推{push_type}(溢出+{extra}期)",
                "force_push": True, "push_type": push_type, "push_count": 10,
                "signal_strength": "极强"}

    # === 规则6: 组六11连+ → 推组三（回归窗口） ===
    zl_streak = 0
    for t in types_all:
        if t == "组六":
            zl_streak += 1
        else:
            break
    if zl_streak >= 11:
        return {"stop": False, "reason": f"组六{zl_streak}连→组三回归窗口",
                "force_push": True, "push_type": "组三", "push_count": 10, "signal_strength": "强"}

    # 正常情况
    return {"stop": False, "reason": "无异常信号，正常推荐",
            "force_push": False, "push_type": target_type, "push_count": 10, "signal_strength": "中"}


def generate_recommendations(records, info, count=10):
    """
    生成组六推荐（用于自动化任务）
    基于: 遗漏回补/热号搭配/和值回归/跨度偏好/位置独立/去重
    info: circuit_breaker 返回值
    返回: [{"nums": [a,b,c], "logic": "...", "sum_val": N, "span": N}, ...]
    """
    if info["stop"]:
        return []

    n = len(records)
    if n < 10:
        return []

    # 计算遗漏
    last_seen = {}
    for idx, r in enumerate(records):
        for num in r["nums"]:
            if num not in last_seen:
                last_seen[num] = idx

    missing = {}
    for i in range(10):
        missing[i] = last_seen.get(i, n)

    # 计算频率
    freq = Counter()
    for r in records:
        for num in r["nums"]:
            freq[num] += 1

    # 冷热排序
    cold = sorted(range(10), key=lambda x: (-missing[x], -freq[x]))
    hot = sorted(range(10), key=lambda x: (-freq[x], missing[x]))

    # 近10期和值
    recent_sums = [r["sum_val"] for r in records[:10]]
    avg_sum_recent = sum(recent_sums) / len(recent_sums) if recent_sums else 0

    # 近10期跨度
    recent_spans = []
    for r in records[:10]:
        n2 = r["nums"]
        recent_spans.append(max(n2) - min(n2))
    avg_span = sum(recent_spans) / len(recent_spans) if recent_spans else 0
    last_span = recent_spans[0] if recent_spans else 0

    candidates = []
    seen_sets = set()

    def add_candidate(nums, logic):
        key = tuple(sorted(nums))
        if key in seen_sets:
            return
        seen_sets.add(key)
        s = sum(nums)
        sp = max(nums) - min(nums)
        candidates.append({
            "nums": sorted(nums),
            "logic": logic,
            "sum_val": s,
            "span": sp
        })

    # 策略1: 遗漏回补核心（最冷3号组合）
    _cold = cold[:]
    for _ in range(2):
        add_candidate([_cold[0], _cold[1], _cold[2]],
                      f"遗漏回补核心: {_cold[0]}(缺{missing[_cold[0]]}期)+{_cold[1]}(缺{missing[_cold[1]]}期)+{_cold[2]}(缺{missing[_cold[2]]}期)")
        _cold = _cold[3:] + _cold[:3]

    # 策略2: 冷热搭配
    _cold2, _hot = cold[:], hot[:]
    for _ in range(2):
        add_candidate([_cold2[0], _hot[0], _hot[1]],
                      f"冷热搭配: {_cold2[0]}(冷)+{_hot[0]}(热)+{_hot[1]}(热)")
        _cold2 = _cold2[1:] + _cold2[:1]
        _hot = _hot[2:] + _hot[:2]

    # 策略3: 和值回归（目标接近理论均值13.5）
    target_sum = 14 if avg_sum_recent < 10 else 11 if avg_sum_recent > 17 else 13
    _cold3 = cold[:]
    for _ in range(2):
        a = _cold3[0]
        for b in range(10):
            if b == a:
                continue
            c = target_sum - a - b
            if 0 <= c <= 9 and c != a and c != b:
                add_candidate([a, b, c], f"和值{target_sum}回归: {a}+{b}+{c}={target_sum}")
                break
        _cold3 = _cold3[1:] + _cold3[:1]
        target_sum = target_sum + 1 if target_sum < 13 else target_sum - 1

    # 策略4: 跨度修正
    target_span = max(2, min(8, int(avg_span))) if last_span >= 8 else min(8, max(3, int(avg_span + 3)))
    _cold4 = cold[:]
    _hot4 = hot[:]
    for _ in range(2):
        a = _cold4[0]
        b = _hot4[0] if _hot4[0] != a else _hot4[1]
        for c in range(10):
            if c != a and c != b and max(a, b, c) - min(a, b, c) == target_span:
                add_candidate([a, b, c], f"跨{target_span}修正: 近均值{target_span}跨")
                break
        _cold4 = _cold4[1:] + _cold4[:1]
        _hot4 = _hot4[1:] + _hot4[:1]
        target_span = max(3, target_span - 1)

    # 策略5: 位置独立（百/十/个各取优号）
    pos_counter = {"bai": Counter(), "shi": Counter(), "ge": Counter()}
    for r in records:
        pos_counter["bai"][r["bai"]] += 1
        pos_counter["shi"][r["shi"]] += 1
        pos_counter["ge"][r["ge"]] += 1
    bai_top = [n for n, _ in pos_counter["bai"].most_common(5)]
    shi_top = [n for n, _ in pos_counter["shi"].most_common(5)]
    ge_top = [n for n, _ in pos_counter["ge"].most_common(5)]
    for i in range(2):
        a = bai_top[0]
        b = shi_top[min(i, len(shi_top) - 1)]
        c = ge_top[min(i + 2, len(ge_top) - 1)]
        if len({a, b, c}) == 3:
            add_candidate([a, b, c], f"位置独立: 百{a}(热)+十{b}(热)+个{c}(热)")
        bai_top = bai_top[1:] + bai_top[:1]

    return candidates[:count]


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

    print(f"\n  [熔断判定]")
    print(f"    停止: {cb.get('stop', 'N/A')}")
    print(f"    原因: {cb.get('reason', 'N/A')}")
    print(f"    强推: {cb.get('force_push', False)} → {cb.get('push_type', '')} × {cb.get('push_count', 0)}")
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
