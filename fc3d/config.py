# -*- coding: utf-8 -*-
"""福彩3D 选号程序配置（常量集中，便于调参）"""
import os

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
HISTORY_FILE = os.path.join(BASE_DIR, "data", "3d_history.json")

WINDOW = 30              # 冷热号统计窗口（最近 N 期）
NOTES = 10               # 每期生成注数（恢复为 10 注）
PERTURB = 0.18           # 随机扰动强度（权重扰动幅度，避免规律性过强）
COLD_WEIGHT = 0.5        # 冷号补偿系数（遗漏归一化后乘此值，避免完全忽略冷号）
BALANCE_PENALTY = 0.45   # 奇偶/大小失衡时，对“多数方”的惩罚系数
SEED = None              # 随机种子（None=每次不同；设整数可复现）

# ---- 直选定位 + 和值带（v6，2026-09-27 起；2026-09-28 起为唯一玩法，组六已移除） ----
DIRECT_MODE = True       # 3D 出号模式恒为直选定位+和值带（旧组六玩法已移除，勿置 False）
DIRECT_POS_N = 2         # 每位定位候选个数（百/十/个各取 TOP2，组合 2^3=8 注直选）
DIRECT_COUNT = 8         # 直选目标注数
SUM_BAND_PEAK = 2        # 和值带 = 近100期峰值 ± 此值（默认 ±2）；设 0 则固定 10-17
DIRECT_PRIZE = 1040      # 直选单注奖金（3D 直选中奖 1040 元/注）
DIRECT_COST = 2          # 直选单注成本（元）
