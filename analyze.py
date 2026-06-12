"""
福彩3D数据分析引擎
统计：频率热冷号、遗漏值、和值分布、跨度、形态
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
    last_seen = {i: 0 for i in range(10)}

    for idx, r in enumerate(records):
        for n in r["nums"]:
            if last_seen[n] == 0:
                last_seen[n] = idx

    missing = {}
    for n in range(10):
        if last_seen[n] == 0:
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

def full_report():
    """生成完整分析报告"""
    records = load_data()
    if not records:
        return None

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
        "形态分析": type_analysis(records)
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
    print("\n" + "=" * 50)

if __name__ == "__main__":
    report = full_report()
    print_summary(report)
