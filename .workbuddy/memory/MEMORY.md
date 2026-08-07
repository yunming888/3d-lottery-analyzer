# 3D彩票分析器 - 项目记忆

## 熔断规则版本 (福彩3D)
- v9 (2026-08-07, 用户新规则): **常态每天推 10 组组六(每天更换)**; **仅当组六连续开出 > 6 期(即>=7期)时熔断暂停(0注)**, 回避极端连开; 形态打断(出组三/豹子)即恢复。旧 Rule1~7/形态自适应逻辑全部废弃。
- 用户只推组六, 不推组三。

## 选号算法版本
- v2 (2026-08-06): analyze.py `generate_recommendations` 重构 —— 枚举全量候选(组六120/组三90)→ 统计合理性打分(和值贴近近期中区10~17 / 跨度4~6最优 / 遗漏仅作弱tie-breaker, 摒弃"冷号必出"赌徒谬误)→ 多样性贪心筛选(分数主导, 乘性微调: 优先引入未覆盖数字、惩罚过度使用数字, 使0~9分布均衡)。输出组数严格等于熔断给的 count, 不写死。
- 组六×5: 0~9全覆盖, 单数字1~2次, 和值13~17; 组六×10: 每数字精确3次; 组三×10: 全覆盖, 4~2次。
- v1 (废弃): 固定策略顺序(遗漏回补/冷热搭配/和值回归/跨度修正/位置独立/补位)拼接后截断, 无均衡约束, 偏赌徒谬误。

## 技术备忘
- git push: 统一用 `git pull --rebase` + `git push origin master`; Python API 兜底已废弃(token 失效)
- 微信推送(automation push_to_wechat): 自动化回复禁止调用 present_files(微信不渲染文件卡片→空白), 改为纯文本自包含输出
- 数据源: **已切换为 huiniao 官方镜像** `http://api.huiniao.top/interface/home/lotteryHistory?type=fcsd&page=1&limit=30` (fetch_data.py `fetch_huiniao`, 免鉴权, ~5分钟同步, 含 200+, 返回 `data.data.list[].{code,day,one,two,three}`)。东方财富兜底仍保留但已过期卡在 2026199。huiniao 实测最新 2026207(2026-08-05开), 2026208 每晚21:15开。
- 每日7点自动执行 (automation-1782775804842)

## 休市判断 (2026-08-03 重构)
- 福彩3D **天天开奖、全年无休**, 周末照常开; 仅财政部公告的官方休市期停开: 春节(2026-02-14~02-23, 10天)、国庆(2026-10-01~10-04, 4天)。
- ❌ 旧逻辑(已废弃): `is_suspension = (last_draw_qihao == current_latest)` —— 期号没变就判休市, 在「抓取源过期/早晨未开奖/抓取失败」时全误判。
- ✅ 新逻辑: `trading_day.is_trading_day(date)` 按日历判定真休市; 交易日但本地数据期号落后预期(`expected_qihao_for_date` 推算)→ 标记「数据滞后」, **绝不误判休市**, 也不编造待开奖记录。
- 休市日列表: `data/holidays.json`(每年需按官方公告更新)。
- 07-31 那3注曾因数据过期误记 target=2026200(=07-29已开), 已修正为真实下一期 **2026202(2026-07-31开, 988 组三)**; 命中0/盈亏-6 不变(推组六 vs 组三必输)。结算逻辑现已按期号精确匹配, 数据新鲜时 target=latest+1 正确。

## 追踪期
- 2026-06-13 ~ 2026-08-31
- profit_loss.json end_date = 2026-08-31

## 子项目: lottery-strategy-analyzer (2026-08-05 新建)
- 位置: 本仓库 `lottery-strategy-analyzer/` —— 通用彩票策略分析程序（双色球/大乐透），与 3D 项目独立。
- 结构: `lottery_analyzer/` 包(config/fetcher/analyzer/recommender/backtester/visualizer/report) + `run.py`(CLI)。
- 数据源: 500彩票网历史接口 `datachart.500.com/{game}/history/newinc/history.php`(server-render HTML, 需剔 `<!--<td>2</td>-->` 注释伪节点; 期号 YYNNN 跨年, 抓取起点按当前年份回退≥2年取窗口)。
- 统计: 频率/冷热三分位/当前+最大遗漏/区间/奇偶和值; 三策略(hot/cold/balanced)选号+回测(组合数学理论中奖率对照)。
- 输出: `output/{game}_analysis.json` / `_report.md` / `_report.html`(图表 base64 内嵌) + 4张 PNG。
- 依赖 matplotlib(已装项目 venv)；运行需 `--refresh` 重新抓取。
- 新增彩种只需在 `config.py` 的 LOTTERIES/SOURCE_500/TIER_FUNC 注册, 核心算法不动。

## 统一三品种每日复盘 (2026-08-07 整合落地)
- 编排器 `unified_review.py`：每日 07:00 运行，依次 `daily_review.main()`(福彩3D) + `dlt/settle.run_daily()` + `ssq/settle.run_daily()`，汇总三品种「昨日数据摘要/复盘结论/具体盈亏」，写 `data/reports/unified_YYYY-MM-DD.md`，打印唯一【微信推送摘要】(自动化直接抓取推送)。**每月1号额外生成上月月度盈亏报告 `data/reports/YYYY-MM-monthly.md`**(替代已删除的月度盈亏自动化)。
- 福彩3D 选号规则(用户 2026-08-07): **固定 10 组组六, 每天更换**; **组六连出 > 6 期(>=7)熔断暂停**(daily_review.circuit_breaker_user_rules)。结算模块 `daily_review.py` 旧 Rule1~7 逻辑已废弃。
- 大乐透/双色球 选号规则(用户 2026-08-07): **各固定 5 组**(`dlt/config.py`/`ssq/config.py` NOTES=5); 引入持久化 `portfolio`(data/dlt_state.json/ssq_state.json), **每2周周五(ISO周偶数)轮换最冷2组**(按号码遗漏和度量冷度, 生成2注新号替换); 修复非开奖日重复堆积 pending 导致重复结算的 bug(改为按 target_issue 仅保留一条 pending)。
- 结算: 按目标期号(target=最新+1)结算 pending; 奖级 `_dlt_tier`/`_ssq_tier` + 固定奖(`DLT_PRIZE` 3~9档 / `SSQ_PRIZE` 3~6档), 一/二等奖浮动奖池记为"浮动奖"不计入PnL(保守)。
- 开奖日: 福彩3D 每日; 大乐透 周一/三/六; 双色球 周二/四/日。昨日无开奖的品种在报告中注明。
- 自动化整合(2026-08-07): **唯一彩票自动化 = `automation-1782775804842`「彩票每期复盘（福彩3D+大乐透+双色球）」**(07:00, 运行 unified_review.py + git push)。已删除冗余: 1786094467671(21:30三品种)/1782898966636(大乐透07:10)/1782899625085(大乐透月度换号)/1785907472096(月度盈亏报告)。保留非彩票: 1784424937390(快手云明夜话)/1784967703745(三平台内容复盘)。
- 运行环境: 必须用 venv `C:/Users/Administrator/.workbuddy/binaries/python/envs/default/Scripts/python.exe`(已装 requests); 裸 managed python 3.13 缺 requests 会报 ModuleNotFoundError。
