# -*- coding: utf-8 -*-
"""双色球 智能选号程序配置（常量集中，便于调参；规则参考大乐透 dlt 框架）"""
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HISTORY_FILE = os.path.join(BASE_DIR, "data", "ssq_history.json")

# ---- 双色球规则 ----
RED_MIN = 1
RED_MAX = 33          # 红球 01-33
RED_COUNT = 6         # 每注选 6 个不重复红球
BLUE_MIN = 1
BLUE_MAX = 16         # 蓝球 01-16
BLUE_COUNT = 1        # 每注选 1 个蓝球

# ---- 选号参数（与大乐透 dlt 一致）----
WINDOW = 100          # 冷热号统计窗口（最近 N 期）
NOTES = 5             # 每期生成注数（用户规则：双色球固定5组）
PERTURB = 0.18        # 随机扰动强度（权重扰动幅度，避免规律性过强）
COLD_WEIGHT = 0.5     # 冷号补偿系数（遗漏归一化后乘此值）
BALANCE_PENALTY = 0.45  # 奇偶/大小失衡时，对“多数方”的惩罚系数
SEED = None           # 随机种子（None=每次不同；设整数可复现）

# 大小分界：红球以 17 为界（1-33 中点≈17），蓝球以 9 为界（1-16 中点≈8.5）
RED_BIG_THRESHOLD = 17
BLUE_BIG_THRESHOLD = 9

# 数据源：500彩票网 双色球历史接口
SOURCE_500 = "https://datachart.500.com/ssq/history/newinc/history.php"

REPORT_DIR = os.path.join(BASE_DIR, "data", "reports")
