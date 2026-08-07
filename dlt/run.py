# -*- coding: utf-8 -*-
"""大乐透 智能选号 入口。"""
import os
import sys

# 将项目根目录加入 sys.path，确保 `from dlt...` 在任何运行方式下都可导入
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dlt.cli import main

if __name__ == "__main__":
    main()
