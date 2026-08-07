# -*- coding: utf-8 -*-
"""福彩3D 选号程序配置（常量集中，便于调参）"""
import os

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
HISTORY_FILE = os.path.join(BASE_DIR, "data", "3d_history.json")

WINDOW = 30              # 冷热号统计窗口（最近 N 期）
NOTES = 10               # 每期生成注数（恢复为 10 注）
BREAK_STREAK = 7         # 组六连出 > 此值（即 >=8 期）触发熔断，暂停生成
PERTURB = 0.18           # 随机扰动强度（权重扰动幅度，避免规律性过强）
COLD_WEIGHT = 0.5        # 冷号补偿系数（遗漏归一化后乘此值，避免完全忽略冷号）
BALANCE_PENALTY = 0.45   # 奇偶/大小失衡时，对“多数方”的惩罚系数
SEED = None              # 随机种子（None=每次不同；设整数可复现）
