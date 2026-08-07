# -*- coding: utf-8 -*-
"""
双色球 命令行入口：自动获取 → 处理 → 执行（选号）
用法：
  python run.py                # 默认 10 注，先尝试实时抓取，失败回退缓存
  python run.py --seed 123     # 固定种子可复现
  python run.py --notes 5      # 临时改注数
  python run.py --no-fetch     # 仅用本地缓存，不联网
"""
import os
import argparse
from datetime import date

from . import config
from .fetcher import fetch_history
from .analysis import load_history, hot_cold, latest
from .selector import generate_notes

RED_BIG = config.RED_BIG_THRESHOLD
BLUE_BIG = config.BLUE_BIG_THRESHOLD


def _fmt(note: dict) -> str:
    reds = " ".join(f"{d:02d}" for d in note["reds"])
    blues = " ".join(f"{d:02d}" for d in note["blues"])
    return f"红球 {reds}   蓝球 {blues}"


def main(argv=None):
    p = argparse.ArgumentParser(description="双色球 智能选号（10注 + 冷热/均衡/扰动）")
    p.add_argument("--seed", type=int, default=None, help="随机种子(可复现)")
    p.add_argument("--notes", type=int, default=config.NOTES, help="生成注数(默认10)")
    p.add_argument("--no-fetch", action="store_true", help="仅用本地缓存，不联网抓取")
    args = p.parse_args(argv)

    today = date.today().isoformat()

    # ---- 1) 自动获取（实时抓取，失败回退缓存） ----
    if args.no_fetch:
        records, meta = load_history(), {"from_cache": True, "fallback": True,
                                         "latest_issue": ""}
        meta["count"] = len(records)
    else:
        records, meta = fetch_history(config.WINDOW)

    if not records:
        print("⚠️  未获取到任何双色球历史数据，无法选号。请检查网络或 data/ssq_history.json。")
        return

    hc = hot_cold(records, config.WINDOW)
    last = latest(records)

    print("=" * 58)
    print("        双色球 智能选号（%d 注）  %s" % (args.notes, today))
    print("=" * 58)
    src = "实时抓取(500彩票网)" if not meta.get("fallback") else "本地缓存(抓取失败回退)"
    print("\n📡 数据源：%s | 最新一期 %s | 统计窗口 %d 期"
          % (src, last.get("issue", "?"), meta.get("count", 0)))

    # ---- 2) 执行（选号） ----
    notes, bal = generate_notes(records, args.notes, seed=args.seed)

    print("\n【推荐号码 %d 注】（红球6 + 蓝球1）" % len(notes))
    for i, n in enumerate(notes, 1):
        print("  %2d. %s" % (i, _fmt(n)))

    # ---- 3) 选号策略说明 ----
    hot_r = " ".join(f"{d:02d}" for d in hc["hot_red"])
    hot_b = " ".join(f"{d:02d}" for d in hc["hot_blue"])
    cold_r = " ".join(f"{d:02d}" for d in hc["cold_red"])
    cold_b = " ".join(f"{d:02d}" for d in hc["cold_blue"])
    print("\n【选号策略说明】")
    print("  · 冷热号分析：红球热号 %s；红球冷号(高遗漏) %s。" % (hot_r, cold_r))
    print("    蓝球热号 %s；蓝球冷号(高遗漏) %s。以热号为主、冷号补足。" % (hot_b, cold_b))
    print("  · 奇偶均衡：红球 奇%d/偶%d，蓝球 奇%d/偶%d（目标≈50:50）。"
          % (bal["r_odd"], bal["r_even"], bal["b_odd"], bal["b_even"]))
    print("  · 大小均衡：红球 大(≥%d)%d/小%d，蓝球 大(≥%d)%d/小%d（目标≈50:50）。"
          % (RED_BIG, bal["r_big"], bal["r_small"], BLUE_BIG, bal["b_big"], bal["b_small"]))
    print("  · 随机扰动：权重注入 ±%.2f 扰动并加权随机抽样，避免号码呈固定规律。"
          % config.PERTURB)

    # ---- 4) 写详细报告 ----
    _write_report(today, last, meta, notes, hc, bal, args.notes)

    # ---- 5) 微信自包含摘要（自动化捕捉此段） ----
    print("\n" + "-" * 58)
    print("【微信推送摘要】")
    print("🎯 双色球智能选号 %s" % today)
    print("数据源：%s（最新 %s）" % (src, last.get("issue", "?")))
    for i, n in enumerate(notes, 1):
        print("  %d. %s" % (i, _fmt(n)))
    print("策略：热号为主+冷号补足；奇偶/大小均衡；±%.2f扰动。" % config.PERTURB)
    print("-" * 58)


def _write_report(today, last, meta, notes, hc, bal, n_notes):
    try:
        os.makedirs(config.REPORT_DIR, exist_ok=True)
        path = os.path.join(config.REPORT_DIR, "ssq_%s.md" % today)
        lines = []
        lines.append("# 双色球智能选号 %s\n" % today)
        lines.append("- 数据源：%s（最新一期 %s，统计窗口 %d 期）\n"
                      % ("实时抓取(500彩票网)" if not meta.get("fallback") else "本地缓存",
                         last.get("issue", "?"), meta.get("count", 0)))
        if last:
            lines.append("- 最新开奖：%s 期 红球 %s 蓝球 %s（%s）\n"
                         % (last.get("issue"), " ".join("%02d" % d for d in last["reds"]),
                            " ".join("%02d" % d for d in last["blues"]), last.get("date", "")))
        lines.append("## 推荐号码 %d 注\n" % n_notes)
        for i, n in enumerate(notes, 1):
            lines.append("%d. %s\n" % (i, _fmt(n)))
        lines.append("\n## 选号策略\n")
        lines.append("- 红球热号：%s；红球冷号：%s\n"
                     % (" ".join("%02d" % d for d in hc["hot_red"]),
                        " ".join("%02d" % d for d in hc["cold_red"])))
        lines.append("- 蓝球热号：%s；蓝球冷号：%s\n"
                     % (" ".join("%02d" % d for d in hc["hot_blue"]),
                        " ".join("%02d" % d for d in hc["cold_blue"])))
        lines.append("- 奇偶均衡：红球 奇%d/偶%d，蓝球 奇%d/偶%d\n"
                     % (bal["r_odd"], bal["r_even"], bal["b_odd"], bal["b_even"]))
        lines.append("- 大小均衡：红球 大%d/小%d，蓝球 大%d/小%d\n"
                     % (bal["r_big"], bal["r_small"], bal["b_big"], bal["b_small"]))
        lines.append("- 随机扰动：权重注入 ±%.2f 扰动并加权随机抽样。\n" % config.PERTURB)
        with open(path, "w", encoding="utf-8") as f:
            f.writelines(lines)
        print("\n📄 详细报告已生成：%s" % path)
    except Exception as e:
        print("\n⚠️  报告写入失败：%s" % e)


if __name__ == "__main__":
    main()
