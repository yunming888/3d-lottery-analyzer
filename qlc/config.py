# -*- coding: utf-8 -*-
"""七乐彩 智能选号程序配置（常量集中，便于调参）

七乐彩官方规则（全国联合销售 30 选 7 电脑福利彩票）：
  - 从 01-30 中选 7 个不重复号码作为「基本号码」，2 元/注；
  - 开奖先摇出 7 个基本号码，再摇出 1 个「特别号码」；
  - 开奖日：每周一 / 三 / 五 21:15；每周 3 期。
  - 奖级：一等(7中7)、二等(6+特)、三等(6) 为浮动奖；四等(5+特,200元)、
    五等(5,50元)、六等(4+特,10元)、七等(4,5元) 为固定奖。
  - 返奖率 50%（当期奖金 49% + 调节基金 1%），单注奖金封顶 500 万元。

⚠️ 出号性质：以下配置只决定「投多少注、投什么结构」，不改变任何中奖概率。
   每注一等奖概率恒为 1/2,035,800，数学上等同机选。
"""
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HISTORY_FILE = os.path.join(BASE_DIR, "data", "qlc_history.json")

# ---- 七乐彩规则 ----
BASIC_MIN = 1
BASIC_MAX = 30          # 基本号码 01-30
BASIC_COUNT = 7         # 每注选 7 个不重复基本号码
SPECIAL_MIN = 1
SPECIAL_MAX = 30        # 特别号码也从 01-30 中摇出（不得与基本号重复）
SPECIAL_COUNT = 1       # 官方规则：特别号码只有 1 个

# ---- 选号参数（与 dlt/ssq 保持一致口径）----
WINDOW = 100            # 冷热号统计窗口（最近 N 期）
NOTES = 5               # 每期生成注数（用户规则：各玩法固定 5 组）
PERTURB = 0.18          # 随机扰动强度（避免号码呈固定规律）
COLD_WEIGHT = 0.12      # 冷号补偿系数（装饰性；冷号≠必出，属赌徒谬误）
BALANCE_PENALTY = 0.45  # 奇偶/大小失衡时对"多数方"的惩罚系数
SEED = None             # 随机种子（None=每次不同）

# 大小分界：01-30 中点为 15.5 → 16 起算大号（16-30 共 15 个，与 1-15 等势）
BASIC_BIG_THRESHOLD = 16

# 开奖日：周一(0) / 周三(2) / 周五(4)
DRAW_DOWS = (0, 2, 4)

# 数据源：huiniao 官方镜像（免鉴权，与 3D/ssq/dlt 同源）
SOURCE_HUINIAO = "http://api.huiniao.top/interface/home/lotteryHistory"

REPORT_DIR = os.path.join(BASE_DIR, "data", "reports")
