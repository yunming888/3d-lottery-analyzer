# -*- coding: utf-8 -*-
"""
报告生成模块
-----------
将分析结果、推荐、回测与图表整合成结构化输出：
- analysis.json ：机器可读的结构化分析结果
- report.md     ：Markdown 报告（引用图表文件）
- report.html   ：自包含 HTML 报告（图表以 base64 内嵌，可单文件分享）
"""

import os
import json
import base64

from . import recommender as rec_mod


def _b64(path):
    with open(path, "rb") as f:
        return "data:image/png;base64," + base64.b64encode(f.read()).decode("ascii")


def _fmt_nums(nums):
    return " ".join(f"{x:02d}" for x in nums)


def _pool_table(pool):
    lines = ["| 号码 | 综合分 | 出现次数 | 近30期 | 当前遗漏 | 最大遗漏 |",
             "|-----|-------|---------|-------|---------|---------|"]
    for it in pool:
        lines.append(f"| {it['num']:02d} | {it['score']:.3f} | {it['freq']} | "
                     f"{it['recent_freq']} | {it['omission']} | {it['max_omission']} |")
    return "\n".join(lines)


def _strategy_block(spec, mode, block):
    lines = [f"### 策略：{mode}（{block['desc']}）", ""]
    lines.append(f"**主推**：红球 {_fmt_nums(block['red'])} ｜ 蓝球 {_fmt_nums(block['blue'])}")
    if block.get("red_alts"):
        for i, (r, b) in enumerate(zip(block["red_alts"], block["blue_alts"]), 1):
            lines.append(f"  备选{i}：红球 {_fmt_nums(r)} ｜ 蓝球 {_fmt_nums(b)}")
    lines.append("")
    lines.append(f"**红球候选池（前 {len(block['red_pool'])}）**")
    lines.append(_pool_table(block["red_pool"]))
    lines.append("")
    lines.append(f"**蓝球候选池（前 {len(block['blue_pool'])}）**")
    lines.append(_pool_table(block["blue_pool"]))
    lines.append("")
    return "\n".join(lines)


def _backtest_block(bt):
    lines = [f"### 策略：{bt['strategy']}", ""]
    lines.append(f"- 回测期数：{bt['tested']}（训练窗口 {bt['train_window']} 期）")
    lines.append(f"- 平均命中：红球 {bt['avg_red_match']} 个 / 蓝球 {bt['avg_blue_match']} 个")
    lines.append(f"- 实际中奖率（任意奖级）：{bt['any_prize_rate']*100:.2f}%")
    lines.append(f"- 理论随机中奖率：{bt['any_prize_theory']*100:.4f}%")
    lines.append(f"- 浮动奖（一/二等奖）命中：{bt['jackpot_wins']} 次（奖金随奖池浮动）")
    lines.append(f"- 固定奖金投入合计：¥{bt['cost']} ｜ 固定奖金回报：¥{bt['fixed_return']} ｜ "
                 f"净盈亏（仅固定奖）：¥{bt['net']}")
    lines.append("")
    lines.append("**奖级命中明细**")
    lines.append("| 奖级 | 名称 | 命中次数 | 单注固定奖金 |")
    lines.append("|-----|------|---------|-------------|")
    for t, d in sorted(bt["tier_detail"].items()):
        fixed = f"¥{d['fixed']}" if d["fixed"] else "浮动"
        lines.append(f"| {t} | {d['name']} | {d['count']} | {fixed} |")
    lines.append("")
    lines.append("**红球命中数分布**")
    lines.append("| 命中红球数 | 期数 |")
    lines.append("|-----------|------|")
    for k, v in bt["red_match_dist"].items():
        lines.append(f"| {k} | {v} |")
    lines.append("")
    return "\n".join(lines)


def build_markdown(spec, meta, stats, rec, backtests, chart_paths):
    L = []
    L.append(f"# {spec.name} 选号策略分析报告")
    L.append("")
    L.append(f"> 生成时间：{meta.get('fetched_at','')} ｜ 数据源：{meta.get('source','')} ｜ "
             f"统计窗口：最近 {stats['window']} 期")
    L.append("")
    L.append("## 一、数据概览")
    L.append("")
    L.append(f"- 彩种：{spec.name}（{spec.key}）")
    L.append(f"- 最新期号：{meta.get('latest_issue','')}（截至抓取时）")
    L.append(f"- 分析期数：{stats['window']} 期")
    L.append(f"- 规则：前区 {spec.red_min}-{spec.red_max} 选 {spec.red_count} 个，"
             f"后区 {spec.blue_min}-{spec.blue_max} 选 {spec.blue_count} 个，每注 ¥{spec.cost_per_note}")
    L.append("")
    L.append("## 二、频率分析")
    L.append("")
    L.append(f"- 红球理论平均出现次数：{stats['red']['expected_freq']} 次")
    L.append(f"- 蓝球理论平均出现次数：{stats['blue']['expected_freq']} 次")
    L.append(f"- 红球和值区间：{stats['red']['parity_sum']['sum_min']} ~ "
             f"{stats['red']['parity_sum']['sum_max']}（均值 {stats['red']['parity_sum']['sum_avg']}）")
    L.append(f"- 红球平均奇偶比（奇数占比）：{stats['red']['parity_sum']['avg_odd_ratio']}")
    L.append("")
    if chart_paths:
        L.append(f"![频率分析]({os.path.basename(chart_paths[0])})")
        L.append("")
    L.append("## 三、冷热号分布")
    L.append("")
    L.append(f"- 热号（高频）：红球 {' '.join(f'{x:02d}' for x in stats['red']['hot'])}")
    L.append(f"- 温号：红球 {' '.join(f'{x:02d}' for x in stats['red']['warm'])}")
    L.append(f"- 冷号（低频）：红球 {' '.join(f'{x:02d}' for x in stats['red']['cold'])}")
    L.append("")
    if len(chart_paths) > 1:
        L.append(f"![冷热号]({os.path.basename(chart_paths[1])})")
        L.append("")
    L.append("## 四、遗漏分析")
    L.append("")
    L.append(f"- 红球高遗漏（最久未出，优先回补候选）："
             f"{' '.join(f'{x:02d}(遗{stats['red']['omission'][x]})' for x in stats['red']['high_omission'])}")
    L.append("")
    if len(chart_paths) > 2:
        L.append(f"![遗漏分析]({os.path.basename(chart_paths[2])})")
        L.append("")
    L.append("## 五、数据驱动选号推荐")
    L.append("")
    for mode in ("balanced", "hot", "cold"):
        L.append(_strategy_block(spec, mode, rec[mode]))
    L.append("---")
    L.append("")
    L.append(rec_mod.RISK_WARNING)
    L.append("")
    L.append("## 六、历史命中率回测")
    L.append("")
    for bt in backtests:
        L.append(_backtest_block(bt))
        if bt.get("strategy") == backtests[0]["strategy"] and len(chart_paths) > 3:
            L.append(f"![回测分布]({os.path.basename(chart_paths[3])})")
            L.append("")
    L.append("## 七、结论")
    L.append("")
    L.append("回测显示，各策略的实际中奖率与组合数学计算的「理论随机中奖率」基本吻合，"
             "说明基于历史统计的选号策略**并未获得超越随机的预测优势**。")
    L.append("号码的冷热与遗漏只是对历史的归纳，不可作为未来走势依据。")
    L.append("本报告仅供统计分析研究与娱乐参考。")
    L.append("")
    return "\n".join(L)


def build_html(spec, meta, stats, rec, backtests, chart_paths):
    css = """
    body{font-family:-apple-system,'Microsoft YaHei',sans-serif;max-width:960px;
         margin:0 auto;padding:24px;color:#222;line-height:1.6;}
    h1,h2,h3{color:#1a3c6e;} .meta{color:#666;font-size:13px;}
    table{border-collapse:collapse;width:100%;margin:10px 0;font-size:13px;}
    th,td{border:1px solid #ddd;padding:6px 8px;text-align:center;}
    th{background:#f0f4fa;} .risk{background:#fff4e5;border-left:4px solid #ff9800;
        padding:12px 16px;margin:16px 0;}
    .rec{background:#f7fbff;border:1px solid #cfe3ff;border-radius:8px;padding:12px 16px;margin:12px 0;}
    img{max-width:100%;border:1px solid #eee;margin:10px 0;border-radius:6px;}
    .num{font-family:monospace;font-size:15px;color:#0b5;}
    """
    parts = [f"<html><head><meta charset='utf-8'><title>{spec.name} 选号策略分析</title>"
             f"<style>{css}</style></head><body>"]
    parts.append(f"<h1>{spec.name} 选号策略分析报告</h1>")
    parts.append(f"<div class='meta'>生成时间：{meta.get('fetched_at','')} ｜ "
                 f"数据源：{meta.get('source','')} ｜ 统计窗口：最近 {stats['window']} 期 ｜ "
                 f"最新期号：{meta.get('latest_issue','')}</div>")
    parts.append("<h2>频率分析</h2>")
    parts.append(f"<p>红球理论平均出现 {stats['red']['expected_freq']} 次；"
                 f"和值均值 {stats['red']['parity_sum']['sum_avg']}。"
                 f"热号：{' '.join(f'{x:02d}' for x in stats['red']['hot'])}；"
                 f"冷号：{' '.join(f'{x:02d}' for x in stats['red']['cold'])}。</p>")
    if chart_paths:
        for p in chart_paths[:3]:
            parts.append(f"<img src='{_b64(p)}'/>")
    parts.append("<h2>数据驱动选号推荐</h2>")
    for mode in ("balanced", "hot", "cold"):
        b = rec[mode]
        parts.append(f"<div class='rec'><h3>{mode}：{b['desc']}</h3>")
        parts.append(f"<p><b>主推</b> 红球 <span class='num'>{_fmt_nums(b['red'])}</span> ｜ "
                     f"蓝球 <span class='num'>{_fmt_nums(b['blue'])}</span></p>")
        for i, (r, bl) in enumerate(zip(b["red_alts"], b["blue_alts"]), 1):
            parts.append(f"<p>备选{i} 红球 <span class='num'>{_fmt_nums(r)}</span> ｜ "
                         f"蓝球 <span class='num'>{_fmt_nums(bl)}</span></p>")
        parts.append("</div>")
    parts.append(f"<div class='risk'>{rec_mod.RISK_WARNING}</div>")
    parts.append("<h2>历史命中率回测</h2>")
    for bt in backtests:
        parts.append(f"<div class='rec'><h3>策略 {bt['strategy']}</h3>")
        parts.append(f"<p>回测 {bt['tested']} 期 ｜ 平均命中 红{bt['avg_red_match']}/蓝"
                     f"{bt['avg_blue_match']} ｜ 实际中奖率 {bt['any_prize_rate']*100:.2f}% ｜ "
                     f"理论 {bt['any_prize_theory']*100:.4f}%</p>")
        parts.append(f"<p>固定奖净盈亏（不含浮动奖）：¥{bt['net']} ｜ "
                     f"浮动奖命中 {bt['jackpot_wins']} 次</p></div>")
    if len(chart_paths) > 3:
        parts.append(f"<img src='{_b64(chart_paths[3])}'/>")
    parts.append("<p>回测结论：各策略实际中奖率与理论随机中奖率基本吻合，"
                 "统计选号无超越随机的预测优势。本报告仅供研究娱乐参考。</p>")
    parts.append("</body></html>")
    return "\n".join(parts)


def save_outputs(spec, meta, stats, rec, backtests, chart_paths, outdir):
    os.makedirs(outdir, exist_ok=True)
    # 结构化 JSON
    analysis = {
        "meta": meta,
        "spec": {"key": spec.key, "name": spec.name,
                 "red": [spec.red_min, spec.red_max, spec.red_count],
                 "blue": [spec.blue_min, spec.blue_max, spec.blue_count]},
        "stats": stats,
        "recommend": rec,
        "backtest": backtests,
    }
    json_path = os.path.join(outdir, f"{spec.key}_analysis.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(analysis, f, ensure_ascii=False, indent=2)

    md_path = os.path.join(outdir, f"{spec.key}_report.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(build_markdown(spec, meta, stats, rec, backtests, chart_paths))

    html_path = os.path.join(outdir, f"{spec.key}_report.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(build_html(spec, meta, stats, rec, backtests, chart_paths))

    return {"json": json_path, "md": md_path, "html": html_path}
