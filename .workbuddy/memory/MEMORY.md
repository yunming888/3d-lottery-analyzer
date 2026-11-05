# 3D彩票分析器 - 项目记忆
> 2026-11-05 精简整理：合并去重、更新过时口径；历史演进细节见 `.workbuddy/memory/automations/automation-1786103338209/memory.md` 与 git log。红线全部保留。

## 🔴 出号性质标注红线（最高优先级，勿回退）
- 所有对外输出（报告/微信摘要/CLI）号码一律称「随机采样」，禁止「推荐/荐号/预测/推导」。
- 报告顶部 + 号码小节顶部必须有性质声明：等同投注站机选、无预测力；开奖随机且每期独立、不存在可推算的下期号码；收费荐号均属诈骗；仅供学习研究，不构成投注建议。
- 标签：`今日随机采样：N注（押XXX期）｜等同机选·无预测力【选号引擎 vX】`
- 3D 主段【选号引擎 钟摆v2 + 大小形态v1】；两组专段【选号引擎 大小形态v1】；dlt/ssq/qlc【选号引擎 v3】。
- 概率口径：3D 直选单注 0.1%、命中率恒 = 注数/1000、ROI 52%；七乐彩一等奖恒 1/2,035,800、返奖率 50%；形态只决定钱花在哪块。
- 不改算法、不改结算，只改表述。

## 每日自动化（唯一彩票任务）
- `automation-1786103338209`「彩票每期复盘（福彩3D+大乐透+双色球+七乐彩）」，ACTIVE，**每日 05:00**，长期有效（validUntil 2099-12-31，停止由云明手动停）。当前 prompt **v1.8**。
- 编排器 `unified_review.py`：依次 `daily_review.main()`(3D) + `dlt/settle` + `ssq/settle` + `qlc/settle`，汇总写 `data/reports/unified_YYYY-MM-DD.md`，打印唯一【微信推送摘要】；每月1号额外生成上月月度报告。脚本幂等。
- 运行必须用 venv：`C:/Users/Administrator/.workbuddy/binaries/python/envs/default/Scripts/python.exe`（裸 managed python 缺 requests）。
- git：`git add -A && git commit -m "每日复盘" && git pull --rebase origin master && git push origin master`。
- 微信推送的自动化回复**禁止调用 present_files**（不渲染→空白），只输出纯文本摘要；发结果用 `send_automation_result`。
- ⚠️ 改自动化时间：改 rrule → **PAUSED → ACTIVE**（强制重算 nextRunAt）→ 换算北京时间核对。只改 rrule 不刷新会当日按旧时间重复触发。
- 每日核对：四品种均出号（休市/非开奖日除外）、无「⚠️ 运行告警」、无静默 0 注、红线声明完整；异常信号 = 静默出 0 注。

## 选号引擎（当前版本）
- **3D = 钟摆v2（主线直选，动态 8~13 注）+ 大小形态v1（A/B 各8注=16注）**；**dlt/ssq/qlc = v3**（`ENGINE_VERSION` 在 analyze.py 及各 selector.py / size_pattern_daily.py；换引擎须同步）。
- 3D 2026-09-28 起纯直选（组六玩法彻底移除），2026-09-29 起主线切钟摆v2：`analyze.PENDULUM_MODE=True`、`DEFAULT_PUSH_TYPE="钟摆直选"`；多窗口融合(10/30/60)+z值标准化+极值回撤+和值分位带(P20-P80)+跨区约束。置换检验 z=1.59 不显著，**无概率优势**，仅结构偏好。
- 结算：直选精确命中（三位同位同值）1040 元/注；组选集合相同不算中奖；去重按 (百,十,个) 位置元组，禁止组选集合归并。"组六"字样仅剩形态统计（展示用，不参与出号）。组六连出熔断已取消，仍停投的只有休市与数据滞后。
- **大小形态两组已并入 3D 主台账（勿回退）**：`size_pattern_daily.py` 只出号（纯函数、不写状态、不单独结算）；`daily_review.py` 把 16 注追加进 `generate_recommendations()` 写进 `profit_loss.json` 同一条记录；`settle_pending()` 统一结算、`calc_summary()` 统一累计，四品种合计自动包含。**无第二份台账/独立结算/跨模块写回**。A「大大小」/B「大小小」固定形态，每日按各位该侧近100期频率 TOP2 重算（复用 `position_pattern.build_notes`）。
- **注数动态**：3D 每日 = 钟摆v2 动态 N + 16 = **N+16 注**，成本 **2×(N+16) 元**，勿写死 28/56。`EFFECTIVE_FROM=2026-11-05`（`size_pattern_daily.is_active()`），口径变更日 11-05，此前约 12 注/24 元；历史 139 条不改写，回测切勿混用前后两段。
- 已作废 v1.6 物件勿恢复：`data/size_pattern_state.json`（从未生成）、独立报告 `size_pattern_*.md`、`run_daily()`、月度独立附节。自测 `python size_pattern_daily.py --selftest`。
- 接入点：3D 主段标签【钟摆v2 + 大小形态v1】只列主线 N 注；专段 `━━ 📐 福彩3D 大小形态两组（已并入 3D 主台账）━━` 列 16 注。
- **热号固定追号**（2026-09-01 起生效）：dlt/ssq/qlc 每注前区/红球/基本号必含核心热号 TOP2（后区/蓝球/特别号不锁），各固定 5 注/10 元每期，每月1号重选；`hot_core.py` + `data/hot_core.json`（按 ym 判跨月，peek() 只读），持久化 portfolio，settle 步骤3.5 校验，跨月或持仓不含核心号→重建组合（`core_ym`）。⚠️ 踩坑：`MIN_RECORDS=10` 防空数据（改 hot_core 后核对 freq 非零）；核心号可能与 `_valid_note` 和值区间冲突致候选池空静默出0注，已加 `check_sum` 放宽。3d_pos 键（旧分位定位）钟摆v2 不读，长期停留 2026-09 属预期。热号追号与随机数学等价。
- 组合轮换：`_is_rotation_day` 以 2026-08-14 为锚每14天周五轮换最冷2组。
- 历史废弃版本勿恢复：v6 分位直选 / v4 边际采样 / v3 硬约束带 / v2 枚举打分 / v1 策略拼接、组六胆拖、组六连出熔断。

## 昨日随机采样（供核对）段（v1.8，2026-11-04 新增）
- 云明指令「每天复盘之前，把昨天预测的号复制过来，我可以核对」→ 对外统一称「**昨日随机采样（供核对）**」，段内自带性质声明，禁「预测/推荐/荐号」。**纯展示、不参与结算**。
- 位置：微信摘要「（前一自然日：%s）」之后、`━━ 🎯 福彩3D ━━` 之前；统一报告顶部性质声明之后、`## 福彩3D` 之前。两处同口径。
- 实现：`unified_review.py` 的 `_load_json_safe()`/`load_yesterday_notes()`/`_fmt_3d_compact()`/`_yn_tag()`/`yesterday_notes_lines()`/`yesterday_notes_md()`；只读，绝不写台账。
- 数据源：3D = `profit_loss.json` 的 `records[].recommendations`（三位数字 list）；dlt/ssq/qlc = `*_state.json` 的 `records[].notes`（note dict）。筛选 `date <= yesterday`，当天新写 pending 天然排除→幂等。
- ⚠️ **口径坑（勿回退）**：非天天开奖品种取「截至昨日最近一次挂出」，必须显示**实际挂出日期**并标「·沿用」，禁止写死「昨日挂出」。
- 11-05 起 3D 主台账含 16 注 → 该段按「钟摆主线 N / A组 / B组」拆分；条件为 `SIZE_EFFECTIVE_FROM` + `push_type` 含「大小形态」+ 注数>16 三重校验，**勿靠总注数猜**。生效首日（11-05 复盘展示 11-04 挂出号）不拆分属正常，11-06 起才拆。

## 规则、数据源、成本
- 开奖日：3D 每日；dlt 周一/三/六；ssq 周二/四/日；qlc 周一/三/五。昨日无开奖的品种在报告中注明。结算按 target=最新+1 结算 pending；一/二等奖浮动奖不计 PnL（保守）。追踪区间见 `profit_loss.json end_date`。
- 数据源：**huiniao 官方镜像** `http://api.huiniao.top/interface/home/lotteryHistory?type=fcsd|ssq|dlt|qlc&page=1&limit=100`（免鉴权，~5分钟同步，响应 `data.data.list` 两层 data；期号 3D/ssq/qlc 7位、dlt 6位）。东方财富兜底已废弃。中福彩 403、体彩需签名 E0001、500彩票网需 UA。双源校验 `verify_data.py`。
- 休市：3D 仅春节/国庆官方公告期停开；用 `trading_day.is_trading_day(date)` 按日历判定，**绝不用「期号没变」判休市**（抓取滞后会误判）；数据落后标「数据滞后」。日表 `data/holidays.json`。qlc 期号 `period_util.next_qlc_qihao`（跨年已修）。
- 走势研判 `analyze.trend_analysis(records, window=100)`。

## 只读诊断工具（不接每日链路、不改出号/结算）
- `bet_structure_analysis.py` → ROI 恒定：dlt 固定奖 26.9% / ssq 24.3% / 3D 组六 48.0%（含浮动奖保守 43.3%/44.8%）；期望线性，复式/胆拖无法改变。复式只改方差不改概率（「至少中小奖概率」复式远低：dlt 7+2 12.25% vs 21注分散 76.54%）。3D 胆拖 ≡ 分散单式。三坑：ssq 6+16 全包蓝「100%中奖但必亏」、复式提升中奖率是统计幻觉、dlt 追加固定奖 ROI 26.9%→18.0%。校验基准：ssq 单注 6.709%、dlt 6.670%。
- `fetch_long_history.py`+`fc3d_backtest.py` → `data/reports/fc3d_backtest_diagnosis.md`：3D 组六 EV = -1.04 元/注；500期 walk-forward 五套方案 z 全在 ±2 → 策略间无显著差异（看到"某版更好"先查 z）；胆拖 71.9% 开奖日结构性必灭但与随机等价；熔断真实作用=少投少亏（非择时信号）；凯利 f*=-0.0066<0 → 最优仓位 0；"回本"需 2.08 倍命中≈5.9σ；实盘 758 注 -1036 元 = 结构损耗 788(76%) + 运气偏差 248(24%)，z=-0.73。
- `pendulum.py`/`pendulum_v2.py`：分三位置划左(0-3)/中(4-6)/右(7-9)区算重心/偏移/动量/回摆，**置换检验**（打乱期序重跑，比朴素 z 严）+ 前后半段稳健性。500期：区域 z 无正向优势；v1 直选 z=3.48 但不稳定+多重比较→噪声；v2 直选 1.70% vs 基准1.01%（z=1.59 不显著），v1 的 z 消失佐证噪声。数据本身接近独立均匀（卡方/自相关通过）→ **判为噪声，不外推**。
- `_next_notes.py`：读 dlt/ssq portfolio 输出下一期组合（沿用不换号），用户再问"给号码"直接跑。
- 历史脚本 `backtest.py`/`backtest_selectors.py`/`settle_and_report.py` 已加"过时/归档"头注释（假设组六口径，勿据此调参）。

## 子项目与依赖
- `lottery-strategy-analyzer/`：通用 ssq/dlt 策略分析（独立），数据源 500彩票网；新增彩种在 `config.py` 注册 LOTTERIES/SOURCE_500/TIER_FUNC。
- 无 requirements.txt；venv 是**共享托管环境**（40+包，含其它项目依赖），本项目只用 `requests`（每日链路）+ matplotlib/pandas/numpy（仅子项目）。**切勿 blanket `pip install -U`**，定点升级。
- 死代码：`fc3d/selector.py` 旧逻辑，未被每日链路调用（仅 `fc3d/run.py` CLI），勿误接。
- ⚠️ 同一文件不要一条消息发多个 Edit（并行会静默丢失），改 `daily_review.py`/`unified_review.py` 多段一律用**单个 Python 脚本原子完成**，改完 Grep 校验。本机 Bash coreutils 全坏，文件读写走「Python 脚本 + Read 工具」。

## 用户对「彩票规律/预测」的立场
- 用户认为彩票有规律、要求"正确推测号码"，不接受"无法预测"。
- 立场：公平随机每期独立，策略不改变负EV；但**边际分布规律真实可用**（组六占比高、和值聚集中区≈14、跨度3-7、长周期趋均匀、奇偶/大小≈50:50），引擎已对齐边际。
- 边界：坦诚无法真预测，不谎称能预测以免诱导加注扩大亏损；用真实数据说话。
