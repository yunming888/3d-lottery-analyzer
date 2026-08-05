# -*- coding: utf-8 -*-
"""
选号推荐引擎
-----------
基于统计分析结果，提供三种数据驱动的选号策略（均为启发式，娱乐参考）：
- hot（热号优先）：近期出现频率高者优先
- cold（冷号回补）：当前遗漏大者优先（「该出」假设）
- balanced（均衡混合）：频率与遗漏加权综合

每个策略产出：1 注主推 + M 注备选（由候选池顺位替换生成），并附带号码依据。
"""

# 均衡策略权重：频率 / 遗漏
BALANCED_W = (0.55, 0.45)


def _scores(zone, mode):
    freq = zone["freq"]
    omis = zone["omission"]
    maxf = max(freq.values()) or 1
    maxo = max(omis.values()) or 1
    out = {}
    for x in freq:
        sf = freq[x] / maxf
        so = omis[x] / maxo
        if mode == "hot":
            out[x] = sf
        elif mode == "cold":
            out[x] = so
        else:
            out[x] = BALANCED_W[0] * sf + BALANCED_W[1] * so
    return out


def _rank_zone(zone, mode):
    sc = _scores(zone, mode)
    return sorted(sc.keys(), key=lambda x: sc[x], reverse=True), sc


def _build_zone_set(zone, mode, count, alt_count):
    ranked, sc = _rank_zone(zone, mode)
    selected = sorted(ranked[:count])
    alts = []
    for i in range(1, alt_count + 1):
        cand_idx = count + i - 1
        if cand_idx >= len(ranked):
            break
        # 替换"第 i 低"的选中位置；当 count 很小（如蓝球仅 1 个）时钳制到合法下标
        replace_idx = count - i
        if replace_idx < 0:
            replace_idx = 0
        new = selected[:]
        new[replace_idx] = ranked[cand_idx]
        alts.append(sorted(new))
    return selected, alts, ranked, sc


def _pool_view(zone, ranked, sc, top_n):
    """候选池视图（含依据），供报告展示。"""
    view = []
    for x in ranked[:top_n]:
        view.append({
            "num": x,
            "score": round(sc[x], 4),
            "freq": zone["freq"][x],
            "recent_freq": zone["recent_freq"][x],
            "omission": zone["omission"][x],
            "max_omission": zone["max_omission"][x],
        })
    return view


def recommend(stats, spec, alt_count=4):
    """
    生成推荐。

    返回 dict: { strategy: {red, blue, red_alts, blue_alts, red_pool, blue_pool, desc} }
    """
    strategies = {
        "hot": "热号优先：选取统计窗口内出现频率最高的号码",
        "cold": "冷号回补：选取当前遗漏值最大的号码（假设'该出'）",
        "balanced": "均衡混合：频率与遗漏加权综合（%.0f%%频率 / %.0f%%遗漏）"
                    % (BALANCED_W[0] * 100, BALANCED_W[1] * 100),
    }
    result = {}
    for mode, desc in strategies.items():
        red_sel, red_alts, red_ranked, red_sc = _build_zone_set(
            stats["red"], mode, spec.red_count, alt_count)
        blue_sel, blue_alts, blue_ranked, blue_sc = _build_zone_set(
            stats["blue"], mode, spec.blue_count, alt_count)
        result[mode] = {
            "desc": desc,
            "red": red_sel,
            "blue": blue_sel,
            "red_alts": red_alts,
            "blue_alts": blue_alts,
            "red_pool": _pool_view(stats["red"], red_ranked, red_sc, spec.red_count + alt_count + 2),
            "blue_pool": _pool_view(stats["blue"], blue_ranked, blue_sc, spec.blue_count + alt_count + 2),
        }
    return result


RISK_WARNING = (
    "【风险提示】彩票开奖为独立随机事件，历史统计仅描述「已经发生」的规律，"
    "无法预测未来走势。本程序所有推荐均基于历史数据的娱乐性参考，不构成任何"
    "投资建议，不保证中奖。请理性购彩、量力而行，切勿追号或倍投超出自身承受范围；"
    "未满18周岁禁止购彩。"
)
