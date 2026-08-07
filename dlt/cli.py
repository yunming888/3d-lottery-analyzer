# -*- coding: utf-8 -*-
"""
大乐透 命令行入口：每日复盘 + 结算 + 选号
用法：
  python run.py                # 默认 10 注，实时抓取→结算→选号→报告
  python run.py --notes 5      # 临时改注数
（结算/盈亏逻辑见 settle.py，按日期幂等，重复运行安全）
"""
import argparse
from datetime import date

from . import config
from .settle import run_daily


def main(argv=None):
    p = argparse.ArgumentParser(description="大乐透 每日复盘（结算+选号）")
    p.add_argument("--notes", type=int, default=config.NOTES, help="生成注数(默认10)")
    args = p.parse_args(argv)

    print("=" * 58)
    print("        大乐透 每日复盘（结算 + 选号）  %s" % date.today().isoformat())
    print("=" * 58)

    res = run_daily(n_notes=args.notes)
    if res.get("error"):
        print("⚠️  %s" % res["error"])
        return
    print("\n📄 报告：%s" % res["report_path"])
    print("累计净盈亏：%+d 元（已结算 %d 轮，待结算 %d 轮）" % (
        res["summary"]["net_pnl"], res["summary"]["rounds"], res["summary"]["pending_rounds"]))


if __name__ == "__main__":
    main()
