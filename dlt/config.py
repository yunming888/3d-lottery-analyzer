# -*- coding: utf-8 -*-
"""大乐透 智能选号程序配置（常量集中，便于调参）"""
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HISTORY_FILE = os.path.join(BASE_DIR, "data", "dlt_history.json")

# ---- 大乐透规则 ----
RED_MIN = 1
RED_MAX = 35          # 前区 01-35
RED_COUNT = 5         # 每注选 5 个不重复前区号
BLUE_MIN = 1
BLUE_MAX = 12         # 后区 01-12
BLUE_COUNT = 2        # 每注选 2 个不重复后区号

# ---- 选号参数 ----
WINDOW = 100          # 冷热号统计窗口（最近 N 期）
NOTES = 10            # 每期生成注数
PERTURB = 0.18        # 随机扰动强度（权重扰动幅度，避免规律性过强）
COLD_WEIGHT = 0.5     # 冷号补偿系数（遗漏归一化后乘此值）
BALANCE_PENALTY = 0.45  # 奇偶/大小失衡时，对“多数方”的惩罚系数
SEED = None           # 随机种子（None=每次不同；设整数可复现）

# 大小分界：前区以 18 为界（1-35 中点≈18），后区以 7 为界（1-12 中点≈6.5）
RED_BIG_THRESHOLD = 18
BLUE_BIG_THRESHOLD = 7

# 数据源：500彩票网 大乐透历史接口
SOURCE_500 = "https://datachart.500.com/dlt/history/newinc/history.php"

REPORT_DIR = os.path.join(BASE_DIR, "data", "reports")
