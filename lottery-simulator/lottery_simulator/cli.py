# -*- coding: utf-8 -*-
"""
命令行入口
----------
子命令通过参数组合实现：
  - 生成并展示：        python run.py -n 5
  - 指定彩种：          python run.py -g dlt -n 3
  - 保存历史：          python run.py -n 5 --save
  - 中奖比对：          python run.py --draw "1,2,3,4,5,6+7" --ticket "1,2,3,4,5,6+7"
  - 随机开奖 vs 投注：  python run.py -n 1 --ticket "1,2,3,4,5,6+7"
  - 查看历史：          python run.py --history
号码格式：红球逗号分隔 + '+' + 蓝球逗号分隔（双色球蓝球1个，大乐透蓝球2个）。
"""
import argparse
from typing import List, Tuple

from .specs import get_spec, LOTTERIES
from .draw import simulate, DrawResult
from .prize import check_winning
from .storage import save_draw, load_history, DEFAULT_HISTORY_FILE


def parse_combo(spec, text: str) -> Tuple[List[int], List[int]]:
    """解析 '红球+蓝球' 字符串并校验个数/范围/重复。"""
    if "+" not in text:
        raise ValueError(f"号码格式应为 '红球+蓝球'，如 '1,2,3,4,5,6+7'，收到: {text}")
    red_part, blue_part = text.split("+", 1)
    red = [int(x) for x in red_part.split(",") if x.strip() != ""]
    blue = [int(x) for x in blue_part.split(",") if x.strip() != ""]

    if len(red) != spec.red_count or len(set(red)) != len(red):
        raise ValueError(f"红球需 {spec.red_count} 个不重复数字（1~{spec.red_max}）")
    if len(blue) != spec.blue_count or len(set(blue)) != len(blue):
        raise ValueError(f"蓝球需 {spec.blue_count} 个不重复数字（1~{spec.blue_max}）")
    for n in red:
        if not (spec.red_min <= n <= spec.red_max):
            raise ValueError(f"红球 {n} 超出范围 {spec.red_min}-{spec.red_max}")
    for n in blue:
        if not (spec.blue_min <= n <= spec.blue_max):
            raise ValueError(f"蓝球 {n} 超出范围 {spec.blue_min}-{spec.blue_max}")
    return red, blue


def _print_history(path: str) -> None:
    recs = load_history(path)
    if not recs:
        print("（无历史记录）")
        return
    print(f"\n===== 历史记录（共 {len(recs)} 条）=====")
    for r in recs:
        d = r["draw"]
        red_s = " ".join(f"{x:02d}" for x in d["red"])
        blue_s = " ".join(f"{x:02d}" for x in d["blue"])
        print(f"{r['time']}  {d['spec_key']}  红球 {red_s}  蓝球 {blue_s}")


def main(argv: List[str] = None) -> None:
    p = argparse.ArgumentParser(description="双色球/大乐透 模拟抽奖程序")
    p.add_argument("-g", "--game", default="ssq", choices=list(LOTTERIES.keys()),
                   help="彩种: ssq=双色球, dlt=大乐透")
    p.add_argument("-n", "--count", type=int, default=1, help="生成注数")
    p.add_argument("-s", "--seed", type=int, default=None, help="随机种子(可复现)")
    p.add_argument("--draw", default=None, help="指定开奖号(比对用), 格式 '红+蓝'")
    p.add_argument("--ticket", default=None, help="投注号码(比对用), 格式 '红+蓝'")
    p.add_argument("--save", action="store_true", help="保存生成的号码到历史")
    p.add_argument("--history", action="store_true", help="打印历史记录")
    p.add_argument("--history-file", default=DEFAULT_HISTORY_FILE, help="历史文件路径")
    args = p.parse_args(argv)

    try:
        spec = get_spec(args.game)

        if args.history:
            _print_history(args.history_file)
            return

        # 1) 生成或指定开奖号
        if args.draw:
            red, blue = parse_combo(spec, args.draw)
            draws = [DrawResult(spec_key=spec.key, red=red, blue=blue)]
        else:
            draws = simulate(spec, args.count, args.seed)

        # 2) 结果展示
        print(f"\n===== {spec.name} 模拟开奖（共 {len(draws)} 注）=====")
        for i, d in enumerate(draws, 1):
            label = f"[第{i}注] " if len(draws) > 1 else ""
            print(f"{label}{d}")

        # 3) 中奖比对（可选）
        if args.ticket:
            t_red, t_blue = parse_combo(spec, args.ticket)
            t_red_s = " ".join(f"{n:02d}" for n in t_red)
            t_blue_s = " ".join(f"{n:02d}" for n in t_blue)
            print(f"\n----- 中奖比对（投注: 红球 {t_red_s}  蓝球 {t_blue_s}）-----")
            for i, d in enumerate(draws, 1):
                r = check_winning(d, t_red, t_blue, spec)
                if r["is_win"]:
                    prize = r["fixed_prize"] if r["fixed_prize"] is not None else "浮动奖池"
                    status = f"🎉 中奖! {r['tier_name']}（奖金 {prize}）"
                else:
                    status = "未中奖"
                label = f"[第{i}注] " if len(draws) > 1 else ""
                print(f"{label}命中红球 {r['red_hit']}/{spec.red_count}, "
                      f"蓝球 {r['blue_hit']}/{spec.blue_count} → {status}")

        # 4) 保存历史（可选）
        if args.save:
            for d in draws:
                save_draw(d, args.history_file)
            print(f"\n✅ 已保存 {len(draws)} 注到: {args.history_file}")
    except ValueError as e:
        # 号码格式/范围/个数非法时给出清晰提示，而非堆栈
        print(f"❌ 输入有误: {e}")
        raise SystemExit(2)


if __name__ == "__main__":
    main()
