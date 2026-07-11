"""
福彩3D 数据分析工具 - 主入口
用法:
  python main.py fetch    抓取最新数据
  python main.py report   生成分析报告
  python main.py chart    生成可视化看板
  python main.py all      一键执行全部
"""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"

    if cmd in ("fetch", "all"):
        print("\n[1/3] 抓取最新数据(东方财富)...\n")
        from fetch_data import load_or_fetch
        records = load_or_fetch()
        if not records:
            print("数据抓取失败, 无可用数据")

    if cmd in ("report", "all"):
        print("\n[2/3] 生成分析报告...\n")
        from analyze import full_report, print_summary
        report = full_report()
        print_summary(report)

    if cmd in ("chart", "all"):
        print("\n[3/3] 生成可视化看板...\n")
        from visualize import load_data, generate_html_report
        records = load_data()
        path = generate_html_report(records)
        print(f"\n在浏览器打开看板: file:///{os.path.abspath(path)}")

    print("\n完成.")

if __name__ == "__main__":
    main()
