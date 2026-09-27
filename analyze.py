"""
福彩3D数据分析引擎
统计：频率热冷号、遗漏值、和值分布、跨度、形态
现行玩法：直选（v6，2026-09-28 起为唯一玩法）
  百位/十位/个位各自独立选号，位置与顺序完全对应才算中奖；
  注数 = 各位候选数相乘；不做任何组选归并。详见 generate_recommendations。

历史玩法（已移除，仅作记录，勿恢复）：
  v5 组六胆拖、v4 组六边际采样、组六连出熔断。回测证实：
  旧逻辑给"近30期热号"加0.3权重(赌徒谬误)；旧硬约束(和值9-20/跨度3-7/奇偶1-2)
  把120个组六集合砍到60个，近一半组六日命中率被锁死0%——虽不改变期望，但放大"全不中"方差。
  熔断（组六连出>=7期停投）只是"少投一天"，并非择时信号。
  现行直选同样不改变负EV与理论中奖率(单注恒 1/1000)，真实开奖独立随机。
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

# ===================== 选号引擎 v6（直选定位 + 和值带） =====================
# v6（2026-09-27 定；2026-09-28 起为**唯一玩法**，旧组六玩法已移除）
#
# 玩法：**直选**。百位 / 十位 / 个位各自独立选号，号码顺序与位置必须完全对应才算中奖。
# 不做任何组选归并——032 与 320 是两注不同的直选，不因数字集合相同而合并或去重。
#
# 规则：
#   1) 定位候选：每个位置分别统计近 POS_WINDOW 期该位出现频次，取 TOP DIRECT_POS_N（默认 2）
#   2) 组合：三位候选做位置笛卡尔积；**注数 = 百位候选数 × 十位候选数 × 个位候选数**
#   3) 去重：按 (百,十,个) 位置元组去重，禁止组选集合去重
#   4) 过滤：和值落在「近 30 期峰值 ± SUM_BAND_PEAK」带内的注优先保留
#   5) 兜底：带内注数不足目标时，放宽到全和值范围补足（不做组选去重）
#   6) 成本 = 注数 × 2 元；中奖口径 = 直选精确命中（三位同位同值），1040 元/注
#
# 红线不变：随机采样·等同机选·无预测力。定位候选与和值带只是投注结构偏好，
# 不提升每注中奖概率（单注直选命中恒为 1/1000），期望不变。
#
# 历史玩法（已移除，勿恢复）：v5 组六胆拖(胆1拖5)、v4 组六边际采样、组六连出熔断。
ENGINE_VERSION = "v6"                 # 选号引擎版本，供报告/推送标注

DIRECT_POS_N = 2                      # 每个位置取几位候选
DIRECT_POS_WINDOW = 30                # 定位候选统计窗口（与 hot_core 3d_pos 缓存口径一致）
DIRECT_TARGET_NOTES = 8               # 目标注数（= 各位候选数之积 2×2×2）


def _digit_marginal(records):
    """长期经验数位边际分布（全窗口 Laplace 平滑）——统计工具，供历史回测复用。"""
    total = Counter()
    for r in records:
        for num in r["nums"]:
            total[num] += 1
    denom = len(records) * 3 + 10      # Laplace: 每数字 +1 先验
    return {i: (total.get(i, 0) + 1.0) / denom for i in range(10)}


def _mk_note(nums, logic):
    return {"nums": nums, "sum_val": sum(nums),
            "span": max(nums) - min(nums), "logic": logic}


# 出号诊断：每次 generate_recommendations 后更新，供报告/排查读取（不参与出号决策）
LAST_GEN = {"engine": "未运行", "target": 0, "returned": 0,
            "core_notes": 0, "filled": 0, "note": ""}


def generate_recommendations(records, info, count=None):
    """
    选号引擎 v6（直选定位 + 和值带）—— **唯一出号入口**。

    玩法：直选。百/十/个三位各自独立选号，位置与顺序完全对应才算中奖；
    同一位置内部数字互异，组合按位置元组去重，绝不按组选集合归并。

    info: {"stop": bool}（stop=True 时不出号，如休市/数据滞后）

    规则（沿用用户 2026-09-27 定，2026-09-28 移除旧组六玩法后成为唯一规则）：
      - 定位候选 = 各位置近 POS_WINDOW 期频次 TOP DIRECT_POS_N，月内锁定，每月 1 号重选
      - 注数 = 百位候选数 × 十位候选数 × 个位候选数（缺省 2×2×2 = 8 注）
      - 和值带 = 近30期峰值±2，带内注优先；不足则放宽到全和值补全至目标注数
      - 成本 = 注数 × 2 元；中奖 = 直选精确命中 1040 元/注

    ⚠️ 诚实边界：定位候选与和值带只是投注结构偏好，与机选数学等价，
    不提升任何概率优势，对外保持「随机采样·等同机选·无预测力」标注。
    """
    global LAST_GEN
    if count is None:
        count = DIRECT_TARGET_NOTES
    LAST_GEN = {"engine": "v6直选定位", "target": count, "returned": 0,
                "core_notes": 0, "filled": 0, "note": ""}

    if info.get("stop"):
        LAST_GEN.update({"engine": "休市/暂停", "note": "规则拦截，不出号"})
        return []
    if not records or len(records) < 4:
        LAST_GEN.update({"engine": "数据不足", "note": "历史期数少于4期，拒绝出号"})
        return []

    return _generate_direct(records, info, count)


def last_gen_desc():
    """给报告/推送用的一句话出号诊断（调用可选）。"""
    g = LAST_GEN
    return "%s：目标%d注/实出%d注（和值带内%d注，补全%d注）%s" % (
        g["engine"], g["target"], g["returned"], g["core_notes"], g["filled"],
        ("｜" + g["note"]) if g["note"] else "")


def _direct_position_candidates(records, n=DIRECT_POS_N, window=DIRECT_POS_WINDOW):
    """本地按位统计 TOP n（hot_core 不可用时的回退；口径与 hot_core 一致）。
    返回 {"bai":[...], "shi":[...], "ge":[...]}，各位内数字互异且升序。"""
    cnt = {"bai": Counter(), "shi": Counter(), "ge": Counter()}
    for r in records[:window]:
        nums = r["nums"]
        cnt["bai"][nums[0]] += 1
        cnt["shi"][nums[1]] += 1
        cnt["ge"][nums[2]] += 1
    pos = {}
    for p, c in cnt.items():
        ranked = sorted(range(10), key=lambda d: (-c.get(d, 0), d))
        pos[p] = sorted(ranked[:n])
    return pos


def _validate_direct_notes(notes, pos):
    """直选选号校验，返回 (ok, msg)。
    ①每位数字 0-9；②每注各位必须取自对应位置的候选；
    ③按 (百,十,个) 位置元组去重（禁止组选集合归并）；④注数 ≤ 各位候选数之积。"""
    bai, shi, ge = pos["bai"], pos["shi"], pos["ge"]
    cap = len(bai) * len(shi) * len(ge)
    if len(notes) > cap:
        return False, "注数 %d 超过各位候选数之积 %d" % (len(notes), cap)
    seen = set()
    for n in notes:
        b, s, g = n["nums"]
        if not all(isinstance(x, int) and 0 <= x <= 9 for x in (b, s, g)):
            return False, "存在非法数字 %s" % (n["nums"],)
        if b not in bai or s not in shi or g not in ge:
            return False, "存在越位号码 %s（候选 百%s/十%s/个%s）" % (n["nums"], bai, shi, ge)
        key = (b, s, g)
        if key in seen:
            return False, "重复注(位置元组) %s" % (key,)
        seen.add(key)
    return True, "校验通过：%d注，位置元组互异，未做组选归并" % len(notes)


# ===================== 和值带（近30期峰值 ± SUM_BAND_PEAK） =====================
def _sum_band_of(records, window=30, pad=2):
    """近 window 期和值峰值 ± pad 的整数区间 [lo, hi]。无数据回退 10-17。"""
    c = Counter()
    for r in records[:window]:
        c[r["sum_val"]] += 1
    if not c:
        return 10, 17
    peak = max(s for s, n in c.items() if n == max(c.values()))
    return max(0, peak - pad), min(27, peak + pad)


# ===================== 直选出号主实现 =====================
def _generate_direct(records, info, count):
    """3D 直选定位 + 和值带。
    百/十/个 各取 TOP n 定位候选 → 位置笛卡尔积（注数 = 各位候选数相乘）
    → 和值带内优先 → 不足则全和值补全 → 直选校验。
    返回 note list（nums 为 [百,十,个]，sum_val = 三位和）。"""
    global LAST_GEN
    LAST_GEN = {"engine": "v6直选定位", "target": count, "returned": 0,
                "core_notes": 0, "filled": 0, "note": ""}

    # 1) 定位候选（优先 hot_core 月锁缓存；不可用时本地按位统计，绝不回退组六）
    try:
        import hot_core
        pos, meta = hot_core.get_3d_position(records, n=DIRECT_POS_N)
        source = "hot_core 月锁(%s)" % meta.get("ym", "?")
    except Exception as e:
        pos = _direct_position_candidates(records)
        source = "本地按位统计(回退：%s)" % e

    bai, shi, ge = pos.get("bai", []), pos.get("shi", []), pos.get("ge", [])
    if not (bai and shi and ge):
        LAST_GEN.update({"note": "定位候选缺失，拒绝出号（不回退旧玩法）"})
        return []

    # 2) 注数 = 各位置所选号码数量相乘
    total = len(bai) * len(shi) * len(ge)
    lo, hi = _sum_band_of(records)

    # 3) 位置笛卡尔积：和值带内优先
    in_band, all_notes = [], []
    for b in bai:
        for s in shi:
            for g in ge:
                sv = b + s + g
                note = _mk_note([b, s, g], "直选定位·百%s十%s个%s" % (b, s, g))
                all_notes.append(note)
                if lo <= sv <= hi:
                    note["logic"] += "·和值带%d-%d" % (lo, hi)
                    in_band.append(note)

    # 4) 带内不足 → 放宽到全和值补全（按位置元组去重，不做组选归并）
    notes = list(in_band)
    for n in all_notes:
        if len(notes) >= min(count, total):
            break
        if any(n["nums"] == x["nums"] for x in notes):
            continue
        n = dict(n)
        n["logic"] = n["logic"].split("·和值带")[0] + "·全和值补全"
        notes.append(n)
    notes = notes[:min(count, total)]

    # 5) 直选校验
    ok, msg = _validate_direct_notes(notes, pos)
    cost = len(notes) * 2
    LAST_GEN.update({
        "returned": len(notes), "core_notes": len(in_band),
        "filled": max(0, len(notes) - len(in_band)),
        "note": ("%s；候选 百%s/十%s/个%s；注数=%d×%d×%d=%d，实出%d注（带内%d）；"
                 "和值带%d-%d；成本%d元；%s" % (
                     source, bai, shi, ge, len(bai), len(shi), len(ge), total,
                     len(notes), len(in_band), lo, hi, cost, msg)),
    })
    if not ok:
        LAST_GEN["note"] = "⚠️校验失败：" + msg + "｜" + LAST_GEN["note"]
    return notes


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

    info = {"stop": False}
    recs = generate_recommendations(records, info)

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
        "出号诊断": last_gen_desc(),
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
    diag = report.get("出号诊断", "")

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

    print(f"\n  [出号诊断]")
    print(f"    {diag}")

    recs = report.get("推荐号码", [])
    if recs:
        print(f"\n  [随机采样号码·等同机选] ({len(recs)}注)")
        for i, r in enumerate(recs):
            print(f"    {i+1}. {' '.join(map(str, r['nums']))} | 和{r['sum_val']} 跨{r['span']} | {r['logic']}")
    print("\n" + "=" * 50)


if __name__ == "__main__":
    report = full_report()
    print_summary(report)
