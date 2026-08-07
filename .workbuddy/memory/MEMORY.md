# 3D彩票分析器 - 项目记忆

## 熔断规则版本 (福彩3D)
- v9 (2026-08-07, 用户新规则): **常态每天推 10 组组六(每天更换)**; **仅当组六连续开出 > 6 期(即>=7期)时熔断暂停(0注)**, 回避极端连开; 形态打断(出组三/豹子)即恢复。旧 Rule1~7/形态自适应逻辑全部废弃。
- 用户只推组六, 不推组三。

## 选号算法版本
- v3 (2026-08-07, 用户要求"抓住规律推测"): analyze.py `generate_recommendations` 升级为**经验分布采样** —— 经验数位频率乘积(联合分布, 独立假设下=各数位边际乘积)作主权重 + 硬约束**先剔除越界候选再选号**: 和值锁 9~20(占82%) / 跨度锁 3~7(占73%) / 奇偶均衡(剔除全奇全偶) + 0~9 每数字精确3次(10注)。摒弃旧软惩罚(避免多样性加分把极端号捞回)。仍属"分布对齐"≠预测。
- v2 (2026-08-06): analyze.py `generate_recommendations` 重构 —— 枚举全量候选(组六120/组三90)→ 统计合理性打分(和值贴近近期中区10~17 / 跨度4~6最优 / 遗漏仅作弱tie-breaker, 摒弃"冷号必出"赌徒谬误)→ 多样性贪心筛选(分数主导, 乘性微调: 优先引入未覆盖数字、惩罚过度使用数字, 使0~9分布均衡)。输出组数严格等于熔断给的 count, 不写死。
- 组六×5: 0~9全覆盖, 单数字1~2次, 和值13~17; 组六×10: 每数字精确3次; 组三×10: 全覆盖, 4~2次。
- v1 (废弃): 固定策略顺序(遗漏回补/冷热搭配/和值回归/跨度修正/位置独立/补位)拼接后截断, 无均衡约束, 偏赌徒谬误。

## 大乐透/双色球 选号器 (selector.py)
- v2 (2026-08-07): 在经验频率加权(已有)基础上新增 `_valid_note` **硬均衡**: 红球奇偶/大小不极端(2..RED_COUNT-2)、和值经验区间(10~90分位, 剔除极端和值)、后区奇偶/大小严格1:1。与3D经验分布思路一致。已有: 频率归一+冷号补偿+随机扰动+软均衡惩罚。

## 技术备忘
- git push: 统一用 `git pull --rebase` + `git push origin master`; Python API 兜底已废弃(token 失效)
- 微信推送(automation push_to_wechat): 自动化回复禁止调用 present_files(微信不渲染文件卡片→空白), 改为纯文本自包含输出
- 数据源: **已切换为 huiniao 官方镜像** `http://api.huiniao.top/interface/home/lotteryHistory?type=fcsd&page=1&limit=100` (fetch_data.py `fetch_huiniao`, 免鉴权, ~5分钟同步, 返回 `data.data.list[].{code,day,one,two,three}`)。东方财富兜底仍保留但已过期卡在 2026199。huiniao 实测最新 2026208(2026-08-06开)。出号前拉100期做走势研判(`analyze.trend_analysis`)。
- 走势研判: `analyze.trend_analysis(records, window=100)` 输出热冷号/和值跨度均值与趋势/组六连出/最大遗漏, 经 daily_review 与 unified_review 进入报告与微信摘要。
- 数据校验/官网抓取: 中福彩官网(cwl.gov.cn)子路径对无头浏览器 **403(WAF)**, 体彩官方 API(webapi.sporttery.cn) **E0001(需签名)** —— 二者均无法直接自动化抓取。权威替代源: **huiniao 镜像(即中福彩官方数据)** 支持 `type=fcsd/ssq/dlt` 三品种, 响应为 `data.data.list`(两层 data), 期号 3D/双色球7位、大乐透6位(比对归一化后5位); **500彩票网**(官方聚合) 需带 `User-Agent` 否则触发反爬挑战页。双源交叉校验脚本见 `verify_data.py`(内部完整性+一致性)。
- 每日7点自动执行: **`automation-1786103338209`「彩票每期复盘（福彩3D+大乐透+双色球）」**(ACTIVE, 列表可见, validFrom=2026-08-08北京时间, 有效期至2026-09-30); 旧 `automation-1782775804842` 经核实已**删除(not found)**, 无遗留重复任务。

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
- 大乐透/双色球 选号规则(用户 2026-08-07, 2026-08-07再确认): **各固定 5 组**(`dlt/config.py`/`ssq/config.py` NOTES=5); 引入持久化 `portfolio`(data/dlt_state.json/ssq_state.json), **每2周周五轮换最冷2组**: 轮换日判定改为「以 2026-08-14 为锚点、每14天一次」(`_is_rotation_day`: `ROTATION_ANCHOR=date(2026,8,14)`, `diff>=0 and diff%14==0`), 首次轮换=08-14/08-28/09-11/09-25… (旧 ISO 偶周逻辑已废弃, 因与锚点错开一周); 换号逻辑 `_rotate_portfolio` 按号码遗漏和(冷度)降序取最冷2组替换为新号, 即「换掉概率最低的2注」。修复非开奖日重复堆积 pending 导致重复结算的 bug(改为按 target_issue 仅保留一条 pending)。
- 结算: 按目标期号(target=最新+1)结算 pending; 奖级 `_dlt_tier`/`_ssq_tier` + 固定奖(`DLT_PRIZE` 3~9档 / `SSQ_PRIZE` 3~6档), 一/二等奖浮动奖池记为"浮动奖"不计入PnL(保守)。
- 开奖日: 福彩3D 每日; 大乐透 周一/三/六; 双色球 周二/四/日。昨日无开奖的品种在报告中注明。
- 自动化整合(2026-08-07): **唯一彩票自动化 = `automation-1786103338209`「彩票每期复盘（福彩3D+大乐透+双色球）」** ACTIVE(列表可见, DAILY;BYHOUR=7), 运行 unified_review.py + git push, 有效期至 2026-09-30。旧重复任务 `automation-1782775804842`(隐藏/未在列表) 已于 2026-08-07 晚经用户确认**删除**, 重复触发风险解除。已删除冗余: 1786094467671/1782898966636/1782899625085/1785907472096/1782775804842。保留非彩票: 1786099733599(注册安全师打卡)/1784424937390(快手云明夜话)/1784967703745(三平台内容复盘)。
- 运行环境: 必须用 venv `C:/Users/Administrator/.workbuddy/binaries/python/envs/default/Scripts/python.exe`(已装 requests); 裸 managed python 3.13 缺 requests 会报 ModuleNotFoundError。

## 用户对"彩票规律/预测"的立场与我的应对 (2026-08-07 两次强调)
- 用户立场: 彩票有规律, 要求我抓住已知规律"正确推测号码", 不接受"无法预测"的推脱。
- 我的立场(有主见, 不附和): 公平随机抽奖每期独立, 过去无法预测下一期具体开奖, 任何组合理论中奖率恒定, 选号策略不改变负EV(3D组六单注≈-1.04元)。但**边际分布规律真实可用**: 组六占比高(基线押组六)、和值聚集中区(3D实测均值14, 密集带9-20)、跨度典型3-7、数字长周期趋近均匀、奇偶/大小≈50:50。
- 落地: 选号引擎(v2)已对齐这些边际规律(中区和值/典型跨度/0-9均衡/组六基线)。可进一步升级为"经验联合分布采样"(数字对频率+更紧和值/跨度带+组六基线), 使每注最大化"形态典型"——但属分布对齐, **不等于预测**。
- 边界: 坦诚说明无法真正预测, 不因用户要求谎称能预测(避免诱导加注扩大亏损; 当前净亏-436)。对话中用真实数据展示规律, 不空谈。
