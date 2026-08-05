# -*- coding: utf-8 -*-
"""
可视化模块
---------
使用 matplotlib 生成统计图表（频率、冷热号、遗漏、回测命中分布）。
自动查找系统中文字体，避免中文标签显示为方框。
输出 PNG 到指定目录，返回文件路径列表。
"""

import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager as fm

_FONT_SET = False


def _ensure_cjk_font():
    global _FONT_SET
    if _FONT_SET:
        return
    candidates = [
        r"C:\Windows\Fonts\simhei.ttf",
        r"C:\Windows\Fonts\SimHei.ttf",
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\Microsoft YaHei UI.ttf",
        r"C:\Windows\Fonts\SourceHanSansSC-Regular.otf",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                fm.fontManager.addfont(path)
                name = fm.FontProperties(fname=path).get_name()
                plt.rcParams["font.family"] = name
                plt.rcParams["axes.unicode_minus"] = False
                break
            except Exception:
                continue
    _FONT_SET = True


def _save(fig, path):
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def chart_frequency(spec, stats, outdir):
    """红球/蓝球出现频率柱状图。"""
    _ensure_cjk_font()
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))
    for ax, zone, label in ((axes[0], "red", f"{spec.name} 红球(前区)频率"),
                            (axes[1], "blue", f"{spec.name} 蓝球(后区)频率")):
        nums = spec.red_pool if zone == "red" else spec.blue_pool
        freq = [stats[zone]["freq"][x] for x in nums]
        ax.bar([str(x) for x in nums], freq, color="#4C72B0")
        ax.set_title(label)
        ax.set_xlabel("号码")
        ax.set_ylabel("出现次数")
        ax.tick_params(axis="x", rotation=90, labelsize=7)
    path = os.path.join(outdir, f"{spec.key}_frequency.png")
    _save(fig, path)
    return path


def chart_hotcold(spec, stats, outdir):
    """冷热号分布：按号码顺序的柱状图，颜色区分热/温/冷。"""
    _ensure_cjk_font()
    nums = spec.red_pool
    freq = [stats["red"]["freq"][x] for x in nums]
    hot = set(stats["red"]["hot"])
    warm = set(stats["red"]["warm"])
    colors = ["#C44E52" if x in hot else "#8172B3" if x in warm else "#55A868" for x in nums]
    fig, ax = plt.subplots(figsize=(12, 4.5))
    ax.bar([str(x) for x in nums], freq, color=colors)
    ax.set_title(f"{spec.name} 红球冷热号分布（红=热号 紫=温号 绿=冷号）")
    ax.set_xlabel("号码")
    ax.set_ylabel("出现次数")
    ax.tick_params(axis="x", rotation=90, labelsize=7)
    path = os.path.join(outdir, f"{spec.key}_hotcold.png")
    _save(fig, path)
    return path


def chart_omission(spec, stats, outdir):
    """当前遗漏值柱状图（按遗漏降序，凸显高遗漏号码）。"""
    _ensure_cjk_font()
    nums = spec.red_pool
    omis = [(x, stats["red"]["omission"][x]) for x in nums]
    omis.sort(key=lambda t: t[1], reverse=True)
    labels = [str(x) for x, _ in omis]
    vals = [v for _, v in omis]
    fig, ax = plt.subplots(figsize=(12, 4.5))
    ax.bar(labels, vals, color="#DD8452")
    ax.set_title(f"{spec.name} 红球当前遗漏值（越高越久未出）")
    ax.set_xlabel("号码（按遗漏降序）")
    ax.set_ylabel("遗漏期数")
    ax.tick_params(axis="x", rotation=90, labelsize=7)
    path = os.path.join(outdir, f"{spec.key}_omission.png")
    _save(fig, path)
    return path


def chart_backtest(red_match_dist, outdir, key):
    """回测红球命中数分布柱状图。"""
    _ensure_cjk_font()
    keys = sorted(red_match_dist.keys(), key=lambda s: int(s))
    vals = [red_match_dist[k] for k in keys]
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.bar(keys, vals, color="#4C72B0")
    ax.set_title("回测：红球命中数分布")
    ax.set_xlabel("命中红球个数")
    ax.set_ylabel("期数")
    for i, v in enumerate(vals):
        ax.text(i, v + 0.3, str(v), ha="center", fontsize=8)
    path = os.path.join(outdir, f"{key}_backtest.png")
    _save(fig, path)
    return path


def make_all_charts(spec, stats, outdir, backtest_result=None):
    os.makedirs(outdir, exist_ok=True)
    paths = [
        chart_frequency(spec, stats, outdir),
        chart_hotcold(spec, stats, outdir),
        chart_omission(spec, stats, outdir),
    ]
    if backtest_result:
        paths.append(chart_backtest(backtest_result["red_match_dist"], outdir, spec.key))
    return paths
