# 3D彩票分析器 - 项目记忆

## 出号性质标注红线 (最高优先级, 勿回退)
- 所有对外输出(报告/微信摘要/CLI)中号码一律称「随机采样」，禁止「推荐/荐号/预测/推导」。
- 报告顶部 + 号码小节顶部必须有性质声明：等同投注站机选、无预测力；开奖随机且每期独立；声称能预测者均属诈骗；仅供学习研究，不构成投注建议。
- 标签格式：`今日随机采样：N注（押XXX期）｜等同机选·无预测力【选号引擎 vX】`
- 证据口径：3D 组六单注中奖率 0.6%，实测 3命中/588注 ≈ 期望 3.5，与机选无统计差异。
- 不改算法、不改结算，只改表述。

## 每日自动化（唯一彩票任务）
- `automation-1786103338209`「彩票每期复盘（福彩3D+大乐透+双色球）」，ACTIVE，**每日 05:00**（2026-08-31 起由 07:00 改点，prompt v1.2），有效期至 2026-09-30。
- 编排器 `unified_review.py`：依次跑 `daily_review.main()`(3D) + `dlt/settle.run_daily()` + `ssq/settle.run_daily()`，汇总写 `data/reports/unified_YYYY-MM-DD.md`，打印唯一【微信推送摘要】；每月1号额外生成上月月度报告 `data/reports/YYYY-MM-monthly.md`。脚本幂等，可重复运行。
- 运行环境必须用 venv：`C:/Users/Administrator/.workbuddy/binaries/python/envs/default/Scripts/python.exe`（裸 managed python 缺 requests）。
- git：`git add -A && commit && git pull --rebase && git push origin master`。
- 微信推送的自动化回复**禁止调用 present_files**（不渲染→空白），只输出纯文本摘要。
- ⚠️ 改自动化时间的正确流程：改 rrule → **PAUSED → ACTIVE**（强制重算 nextRunAt）→ 用 python 把 nextRunAt 换算成北京时间核对。只改 rrule 时 nextRunAt 不刷新，会导致当日按旧时间重复触发一次。

## 选号引擎（当前版本）
- **福彩3D v5 / 大乐透 v3 / 双色球 v3**（`ENGINE_VERSION` 常量在 analyze.py、dlt/selector.py、ssq/selector.py；换引擎须同步更新）。
- 规则「热号固定追号」，**2026-09-01 起生效**（`hot_core.EFFECTIVE_FROM` + `is_active()`）；8/31 前仍走旧逻辑（3D v4 边际采样、dlt/ssq v2 无核心号），到点自动切换无需改码。
  - 3D：胆1拖5 = C(5,2)=10 注，每注必含胆码；胆=近100期频率TOP1，拖=其余TOP5；组三/异常回退 v4。
  - 大乐透/双色球：每注前区/红球必含核心热号 TOP2（后区/蓝球不锁），各 5 注。
  - 统一模块 `hot_core.py` + 状态 `data/hot_core.json`（按 `ym` 判跨月，`peek()` 只读）。dlt/ssq 走持久化 portfolio，settle 步骤3.5 有核心号校验：跨月变更或持仓有注不含核心号 → 立即重建组合（`st["core_ym"]` 记录已应用月份）。
  - 踩坑：① `hot_core.MIN_RECORDS=10` 防空数据污染缓存（**改 hot_core 后务必核对 hot_core.json 的 freq 非零**）；② 核心号可能与 `_valid_note` 和值区间冲突致候选池空、静默出0注，已加 `check_sum` 参数放宽重试。
  - **2026-09-01 生效首日已验证通过**：3D 胆2拖3/5/6/8/9（10注每注含胆）；dlt 核心前区 26/13、ssq 核心红球 24/30（各5注每注含）；freq 均非零，dlt/ssq 正常触发"已重建5组"且 `core_ym=2026-09`。2026-09 全月锁定，下次重选 10-01。
  - 每日核对清单：`hot_core.json` 三品种 freq 非零 + 每注含核心号 + `ym` 为当月；异常信号是**静默出 0 注**。
- 热号追号与随机**数学等价**（每注概率恒定，3D 胆拖每期最多中1注无叠加），属投注结构偏好，对外标注不变。
- 历史版本（均已废弃，勿恢复）：v4 经验边际采样（现为 3D 回退路径）/ v3 硬约束带 / v2 枚举打分 / v1 策略拼接。

## 规则与成本
- 福彩3D：常态每天 10 组组六（每天更换）；**组六连出 >= 7 期熔断暂停(0注)**，形态打断(出组三/豹子)即恢复。只推组六，不推组三。成本 20 元/天。
- 大乐透/双色球：各固定 5 组（`NOTES=5`），成本 10 元/期。持久化 portfolio，`_is_rotation_day` 以 2026-08-14 为锚点每14天轮换最冷2组（08-14/08-28/09-11/09-25…）。
- 开奖日：3D 每日；大乐透 周一/三/六；双色球 周二/四/日。昨日无开奖的品种在报告中注明。
- 结算：按 target=最新+1 结算 pending；一/二等奖浮动奖记为"浮动奖"不计 PnL（保守）。
- 追踪期 2026-06-13 ~ 2026-08-31（`profit_loss.json end_date`）。

## 数据源与休市
- 数据源：**huiniao 官方镜像** `http://api.huiniao.top/interface/home/lotteryHistory?type=fcsd|ssq|dlt&page=1&limit=100`（免鉴权，~5分钟同步，响应 `data.data.list` 两层 data；期号 3D/双色球7位、大乐透6位）。东方财富兜底已过期废弃。
- 中福彩官网(cwl.gov.cn)对无头浏览器 403、体彩 API(webapi.sporttery.cn) 需签名 E0001 —— 均无法自动抓。500彩票网需带 User-Agent。双源校验脚本 `verify_data.py`。
- 走势研判 `analyze.trend_analysis(records, window=100)`：热冷号/和值跨度/组六连出/最大遗漏。
- 休市：3D 天天开奖，仅春节/国庆官方公告期停开；用 `trading_day.is_trading_day(date)` 按日历判定，**绝不用"期号没变"判休市**（抓取滞后时会误判）；数据落后时标记「数据滞后」而非休市。休市日表 `data/holidays.json`。

## 投注结构性价比结论（可直接引用）
- `bet_structure_analysis.py` → `data/reports/bet_structure_analysis.md`（独立跑，不接每日链路）。
- **ROI 恒定**：大乐透固定奖 26.9% / 双色球 24.3% / 3D 组六 48.0%；含浮动奖保守 43.3%/44.8%。期望线性性决定，复式/胆拖都无法改变。
- **复式只改方差不改概率**：一等奖概率 = 注数/总组合数，与同注数分散单式相同；但「至少中小奖概率」复式远低（大乐透 7+2 复式 12.25% vs 21注分散 76.54%）。想常有回响选分散单式，想中大奖则结构无所谓。
- **3D 胆拖 ≡ 分散单式**（连中奖概率也相同）：每期最多中1注无叠加，胆码错全废的风险已反映在概率里。
- 三坑：①双色球 6+16 全包蓝球「100%中奖但必亏」(32元必中5元)；②复式提升的中奖率是统计幻觉；③大乐透追加只作用于浮动奖，固定奖 ROI 从 26.9% 掉到 18.0%。
- 校验基准：双色球单注中奖率 6.709%、大乐透 6.670%；复式固定奖期望必须 = 注数 × 单注期望。

## 子项目与依赖
- `lottery-strategy-analyzer/`：通用双色球/大乐透策略分析（与3D项目独立），数据源 500彩票网，输出 json/md/html+PNG；新增彩种只需在 `config.py` 注册 LOTTERIES/SOURCE_500/TIER_FUNC。
- 依赖：无 requirements.txt；venv 是**共享托管环境**(40+包，含其它项目依赖)，本项目只用 `requests`（每日链路）与 matplotlib/pandas/numpy（仅子项目）。**切勿 blanket `pip install -U`**，定点升级。
- 死代码：`fc3d/selector.py` 仍是旧逻辑，未被每日链路调用（仅 `fc3d/run.py` CLI），勿误接。

## 用户对"彩票规律/预测"的立场（2026-08-07 强调）
- 用户认为彩票有规律，要求"正确推测号码"，不接受"无法预测"。
- 我的立场：公平随机每期独立，策略不改变负EV；但**边际分布规律真实可用**（组六占比高、和值聚集中区≈14、跨度3-7、数字长周期趋均匀、奇偶/大小≈50:50），引擎已对齐这些边际。
- 边界：坦诚说明无法真预测，不谎称能预测以免诱导加注扩大亏损；用真实数据说话。
