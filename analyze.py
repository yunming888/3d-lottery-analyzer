"""
福彩3D数据分析引擎
统计：频率热冷号、遗漏值、和值分布、跨度、形态
选号引擎 v4（2026-08-20 重写）:
  问题诊断(回测证实):
    旧逻辑给"近30期热号"加0.3权重(近期热≠未来热, 赌徒谬误);
    旧硬约束(和值9-20/跨度3-7/奇偶1-2)把120个组六集合砍到60个,
    真实组六开奖46.75%落在约束带外 -> 近一半组六日命中率被锁死0%,
    虽不改变数学期望(每注理论中奖率恒定), 但放大"全不中"方差、体验更差。
  新逻辑:
    1) 长期经验数位边际分布(全窗口 Laplace 平滑), 去除近期赌徒谬误权重;
    2) 按边际分布无放回覆盖加权采样, 自然复现"和值/跨度典型"且不再硬剔除半数空间;
    3) 覆盖均衡: 每数字出现次数趋向均衡, 提升数字覆盖;
    4) 按最新期号派生随机种子 -> 同日确定、跨日自然变化、可复现。
  仍属"分布对齐", 不改变负EV与理论中奖率; 真实开奖独立随机。
"""
import json
import os
import random
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
    熔断判定（保留旧接口；实际每日规则见 daily_review.circuit_breaker_user_rules）
    """
    n = len(records)
    if n < 3:
        return {"stop": False, "reason": "数据不足", "suggest": "",
                "push_type": target_type, "push_count": 10, "signal_strength": "弱"}

    types_all = [r["type"] for r in records]
    sums_3 = [r["sum_val"] for r in records[:3]]

    zl_streak = 0
    for r in records:
        if r["type"] == "组六":
            zl_streak += 1
        else:
            break

    streak_type = types_all[0]
    streak_len = 1
    for t in types_all[1:]:
        if t == streak_type:
            streak_len += 1
        else:
            break

    if zl_streak >= 8:
        p = 1 - (0.732 ** zl_streak)
        return {"stop": True,
                "reason": f"组六连续{zl_streak}期",
                "suggest": f"组三概率已达{p*100:.0f}%，建议推10注组三搏回归。是否推？",
                "push_type": "组三", "push_count": 10, "signal_strength": "极强"}

    if streak_len >= 3:
        reverse = "组六" if streak_type == "组三" else "组三"
        return {"stop": True,
                "reason": f"连续{streak_len}期{streak_type}",
                "suggest": f"3连{streak_type}后形态切换率>80%，建议推10注{reverse}。是否推？",
                "push_type": reverse, "push_count": 10,
                "signal_strength": "极强" if streak_len >= 4 else "强"}

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

    return {"stop": False, "reason": f"正常推荐 (组六{zl_streak}连，{streak_len}连{streak_type})",
            "suggest": "", "push_type": target_type, "push_count": 10, "signal_strength": "中"}


# ===================== 选号引擎 v4（重写） =====================
ENGINE_VERSION = "v4"  # 选号引擎版本，供报告/推送标注（出号时附带说明）
def _digit_marginal(records):
    """长期经验数位边际分布（全窗口 Laplace 平滑）。
    去除旧逻辑的'近30期热号0.3权重'——近期热≠未来热, 属赌徒谬误, 不提升期望。"""
    total = Counter()
    for r in records:
        for num in r["nums"]:
            total[num] += 1
    denom = len(records) * 3 + 10  # Laplace: 每数字 +1 先验
    return {i: (total.get(i, 0) + 1.0) / denom for i in range(10)}


def _weighted_choice_dict(w, rng):
    items = list(w.items())
    tot = sum(v for _, v in items)
    if tot <= 0:
        return items[rng.randrange(len(items))][0]
    r = rng.random() * tot
    cum = 0.0
    for d, v in items:
        cum += v
        if r <= cum:
            return d
    return items[-1][0]


def _sample_digits(rng, marginal, used, target, k, exclude=()):
    """无放回按'边际×覆盖均衡'权重抽 k 个互异数字。
    - 边际: 经验频率越高越优先(自然复现典型和值/跨度)
    - 覆盖均衡: 已超额使用的数字降权, 未达标的升权 -> 每数字出现次数趋向均衡
    - exclude: 组三时排除已选的'对子数字'"""
    chosen = []
    avail = [d for d in range(10) if d not in exclude]
    for _ in range(k):
        w = {}
        for d in avail:
            if d in chosen:
                continue
            base = marginal[d]
            util = used.get(d, 0)
            if util >= target:
                w[d] = base * 0.2          # 已达均衡目标, 大幅降权
            else:
                w[d] = base * (1.0 + 0.6 * (target - util) / max(1, target))
        d = _weighted_choice_dict(w, rng)
        chosen.append(d)
        avail.remove(d)
    return sorted(chosen)


def _make_logic_simple(nums, push_type):
    sv = sum(nums)
    band = "和值中区" if 9 <= sv <= 20 else ("和值小" if sv < 9 else "和值大")
    return f"经验边际·{band}{sv}·覆盖均衡"


def generate_recommendations(records, info, count=10):
    """
    选号引擎 v4（经验边际采样 + 覆盖均衡 + 每日变化）
    info: {"stop": bool, "push_type": "组六"/"组三", "push_count": int}
    返回: list of {"nums":[...], "sum_val":int, "span":int, "logic":str}

    说明: 公平随机下每注理论中奖率恒定, 本引擎不改变负EV与理论中奖率;
    仅去除假性规律(赌徒谬误), 使选号统计上更干净、覆盖更均衡、不再把半数开奖日锁死0%。
    """
    if info.get("stop"):
        return []

    push_type = info.get("push_type", "组六")
    n = len(records)
    if n < 4:
        return []

    marginal = _digit_marginal(records)
    # 每日变化种子: 用最新期号派生 -> 同日确定、跨日自然变化、可复现
    try:
        seed = int(records[0]["qihao"])
    except Exception:
        seed = 20260613
    rng = random.Random(seed)

    target = count * 3 / 10.0  # 每数字期望出现次数(每注3码)
    used = Counter()
    selected = []
    seen = set()
    attempts = 0
    max_attempts = count * 500

    while len(selected) < count and attempts < max_attempts:
        attempts += 1
        if push_type == "组三":
            d = _sample_digits(rng, marginal, used, target, 1)[0]   # 对子数字
            s = _sample_digits(rng, marginal, used, target, 1, exclude=(d,))[0]  # 单数字
            nums = sorted([d, d, s])
        else:
            nums = _sample_digits(rng, marginal, used, target, 3)
        key = tuple(nums)
        if key in seen:
            continue
        seen.add(key)
        sv = sum(nums)
        sp = max(nums) - min(nums)
        selected.append({
            "nums": nums,
            "sum_val": sv,
            "span": sp,
            "logic": _make_logic_simple(nums, push_type),
        })
        for x in nums:
            used[x] += 1

    return selected


def trend_analysis(records, window=100):
    """
    吃透最近 window 期走势图规律：数字热冷、和值/跨度趋势、当前连形态、最大遗漏。
    返回统计 dict + 可读 conclusion（出号前研判用，不声称预测）。
    """
    win = records[:window]
    n = len(win)
    dig = Counter()
    for r in win:
        for x in r["nums"]:
            dig[x] += 1
    tot = sum(dig.values()) or 1
    freq_sorted = sorted(((d, c, c / tot * 100) for d, c in dig.items()), key=lambda t: -t[1])
    hot = [d for d, _, _ in freq_sorted[:3]]
    cold = [d for d, _, _ in freq_sorted[-3:]]

    recent = records[:30]
    sums_all = [r["sum_val"] for r in win]
    sums_recent = [r["sum_val"] for r in recent]
    avg_all = sum(sums_all) / len(sums_all)
    avg_recent = sum(sums_recent) / len(sums_recent)
    spans_all = [r["span"] for r in win]
    spans_recent = [r["span"] for r in recent]
    span_avg_all = sum(spans_all) / len(spans_all)
    span_avg_recent = sum(spans_recent) / len(spans_recent)

    zl = 0
    for r in records:
        if r["type"] == "组六":
            zl += 1
        else:
            break

    miss = missing_analysis(records)
    overdue = miss["most_overdue"][:3]

    trend_dir = "走高" if avg_recent > avg_all + 1 else ("走低" if avg_recent < avg_all - 1 else "平稳")
    span_dir = "扩大" if span_avg_recent > span_avg_all + 0.5 else ("收窄" if span_avg_recent < span_avg_all - 0.5 else "平稳")
    conclusion = (
        f"近{n}期: 热号 {hot} / 冷号 {cold}; "
        f"和值均值 {avg_all:.1f}(近30期 {avg_recent:.1f}, {trend_dir}); "
        f"跨度均值 {span_avg_all:.1f}(近30期 {span_avg_recent:.1f}, {span_dir}); "
        f"组六连出 {zl} 期; 最大遗漏 {overdue[0][0]}号({overdue[0][1]}期)。"
    )
    return {
        "window": n, "freq_sorted": freq_sorted, "hot": hot, "cold": cold,
        "avg_sum_all": avg_all, "avg_sum_recent": avg_recent, "sum_trend": trend_dir,
        "span_avg_all": span_avg_all, "span_avg_recent": span_avg_recent, "span_trend": span_dir,
        "zl_streak": zl, "overdue": overdue, "conclusion": conclusion,
    }


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
