# -*- coding: utf-8 -*-
"""
命令行入口：生成 10 注福彩3D 号码 + 选号策略说明，含组六熔断判定。
用法：
  python run.py                # 默认 10 注
  python run.py --seed 123     # 固定种子可复现
  python run.py --notes 5      # 临时改注数
"""
import argparse
from .analysis import load_history, hot_cold, zuliu_streak
from .selector import generate_notes
from .config import NOTES, BREAK_STREAK, WINDOW, PERTURB


def main(argv=None):
    p = argparse.ArgumentParser(description="福彩3D 智能选号（10注 + 冷热/均衡/扰动）")
    p.add_argument("--seed", type=int, default=None, help="随机种子(可复现)")
    p.add_argument("--notes", type=int, default=NOTES, help="生成注数(默认10)")
    args = p.parse_args(argv)

    records = load_history()
    streak = zuliu_streak(records)
    hc = hot_cold(records, WINDOW)

    print("=" * 50)
    print("        福彩3D 智能选号（%d 注）" % args.notes)
    print("=" * 50)

    # ---- 熔断判定：组六连出 > BREAK_STREAK 期 → 停止生成 ----
    if streak > BREAK_STREAK:
        print("\n⚠️  熔断触发：组六已连续 %d 期（>%d），暂停生成、不押注。" % (streak, BREAK_STREAK))
        print("     （连续组六后形态大概率切换，此时继续追组六风险高，故熔断观望）")
        return

    print("\n📊 历史形态：组六连续 %d 期（≤%d，未触发熔断）→ 正常生成。" % (streak, BREAK_STREAK))

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
    print("  · 熔断规则：组六连出 >%d 期即停止生成，转为观望。" % BREAK_STREAK)


if __name__ == "__main__":
    main()
