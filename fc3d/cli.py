# -*- coding: utf-8 -*-
"""
命令行入口：生成福彩3D 直选号码（百位/十位/个位独立选号）+ 选号策略说明。
用法：
  python run.py                # 默认 10 注
  python run.py --seed 123     # 固定种子可复现
  python run.py --notes 5      # 临时改注数
"""
import argparse
from .analysis import load_history, hot_cold, zuliu_streak
from .selector import generate_notes
from .config import NOTES, WINDOW, PERTURB


def main(argv=None):
    p = argparse.ArgumentParser(description="福彩3D 智能选号（直选 + 冷热/均衡/扰动）")
    p.add_argument("--seed", type=int, default=None, help="随机种子(可复现)")
    p.add_argument("--notes", type=int, default=NOTES, help="生成注数(默认10)")
    args = p.parse_args(argv)

    records = load_history()
    streak = zuliu_streak(records)
    hc = hot_cold(records, WINDOW)

    print("=" * 50)
    print("        福彩3D 智能选号（%d 注）" % args.notes)
    print("=" * 50)

    # 形态统计仅供走势参考；组六熔断已随组六玩法移除，不再作为生成门槛
    print("\n📊 历史形态：组六连续 %d 期（仅供走势参考，不做生成门槛）→ 正常生成。" % streak)

    notes, bal = generate_notes(records, args.notes, seed=args.seed)

    # ---- 号码列表 ----
    print("\n【随机采样号码 %d 注·等同机选·无预测力】（百位 十位 个位）" % len(notes))
    for i, n in enumerate(notes, 1):
        print("  %2d.  %d %d %d     (%d%d%d)" % (i, n[0], n[1], n[2], n[0], n[1], n[2]))

    # ---- 选号策略说明 ----
    total = bal["odd"] + bal["even"]
    hot_s = " ".join(str(d) for d in hc["hot"])
    cold_s = " ".join(str(d) for d in hc["cold"])
    print("\n【选号策略说明】")
    print("  · 冷热号分析：近 %d 期热号 %s；冷号(高遗漏) %s。" % (WINDOW, hot_s, cold_s))
    print("    本批以热号为主、冷号补足，避免一味追热导致局部过度集中。")
    print("  · 奇偶均衡：奇数 %d / 偶数 %d（共 %d 位，目标≈50:50）。" % (bal["odd"], bal["even"], total))
    print("  · 大小均衡：大号(5-9) %d / 小号(0-4) %d（共 %d 位，目标≈50:50）。" % (bal["big"], bal["small"], total))
    print("  · 随机扰动：权重注入 ±%.2f 扰动并加权随机抽样，避免号码呈现固定规律。" % PERTURB)
    print("  · 玩法：直选——百/十/个三位独立选号，位置与顺序完全对应才算中奖。")


if __name__ == "__main__":
    main()
