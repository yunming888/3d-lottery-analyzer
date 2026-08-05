# -*- coding: utf-8 -*-
"""
彩票策略分析程序 - 主入口

用法:
    python run.py                      # 分析全部已配置彩种（双色球 + 大乐透）
    python run.py --game ssq           # 仅分析双色球
    python run.py --game dlt --window 200 --k 60
    python run.py --refresh            # 强制刷新数据缓存
    python run.py --out my_output      # 指定输出目录

流程: 抓取整合历史数据 -> 统计分析(频率/冷热/遗漏) -> 数据驱动选号推荐
      -> 历史命中率回测 -> 可视化图表 -> 结构化报告(Markdown/HTML/JSON)
"""

import argparse
import os
import sys

# 允许以脚本方式直接运行（python run.py）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lottery_analyzer import config, fetcher, analyzer, recommender, backtester, visualizer, report


def run_game(game, window, backtest_k, outdir, force_refresh):
    spec = config.get_spec(game)
    print(f"[*] 正在分析 {spec.name}（{game}）...")

    draws, meta = fetcher.fetch_history(game, window=window, force_refresh=force_refresh)
    print(f"    数据: 最新 {meta['latest_issue']}，共 {meta['count']} 期，"
          f"来源 {meta['source']}，缓存={meta.get('from_cache', False)}")

    stats = analyzer.analyze(draws, spec)
    rec = recommender.recommend(stats, spec, alt_count=4)

    backtests = [backtester.backtest(draws, spec, s, k=backtest_k)
                 for s in ("balanced", "hot", "cold")]
    for bt in backtests:
        print(f"    回测[{bt['strategy']}]: {bt['tested']}期 实际中奖率 "
              f"{bt['any_prize_rate']*100:.2f}% / 理论 {bt['any_prize_theory']*100:.4f}%")

    chart_paths = visualizer.make_all_charts(spec, stats, outdir, backtest_result=backtests[0])
    paths = report.save_outputs(spec, meta, stats, rec, backtests, chart_paths, outdir)

    print(f"    推荐(均衡): 红 {' '.join(f'{x:02d}' for x in rec['balanced']['red'])} "
          f"蓝 {' '.join(f'{x:02d}' for x in rec['balanced']['blue'])}")
    print(f"    报告: {paths['html']}")
    print(f"    图表: {len(chart_paths)} 张")
    return paths


def main():
    parser = argparse.ArgumentParser(description="彩票策略分析程序")
    parser.add_argument("--game", default="all",
                        help="彩种：ssq / dlt / all（默认 all）")
    parser.add_argument("--window", type=int, default=config.DEFAULT_WINDOW,
                        help=f"统计窗口期数（默认 {config.DEFAULT_WINDOW}）")
    parser.add_argument("--k", type=int, default=80,
                        help="回测期数（默认 80）")
    parser.add_argument("--out", default=None, help="输出目录")
    parser.add_argument("--refresh", action="store_true", help="强制刷新数据缓存")
    args = parser.parse_args()

    games = list(config.LOTTERIES.keys()) if args.game == "all" else [args.game]
    outdir = args.out or os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")

    print("=" * 60)
    print(" 彩票策略分析程序 v" + __import__("lottery_analyzer", fromlist=["__version__"]).__version__)
    print("=" * 60)
    all_paths = {}
    for g in games:
        try:
            all_paths[g] = run_game(g, args.window, args.k, outdir, args.refresh)
        except Exception as e:
            print(f"[!] {g} 分析失败: {e}")
    print("=" * 60)
    print(" 完成。输出文件:")
    for g, p in all_paths.items():
        print(f"   [{g}] HTML : {p['html']}")
        print(f"   [{g}] MD   : {p['md']}")
        print(f"   [{g}] JSON : {p['json']}")
    print("=" * 60)


if __name__ == "__main__":
    main()
