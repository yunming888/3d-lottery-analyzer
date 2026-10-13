# 出号逻辑深度审计报告

**审计日期**：2026-10-13
**审计范围**：福彩3D（钟摆v2）+ 大乐透 v3 + 双色球 v3 的号码生成全链路
**方法**：3 个并行子代理分头审计 + 主控亲自复核关键行号与实测数据
**代码基线**：`6166f85`（本次审计未修改任何源码，纯只读）

---

## 0. 结论先行

| # | 结论 | 严重度 | 证据 |
|---|---|---|---|
| 1 | **跨年期号推算必错**，约 12/28 起结算全线静默失效 | 🔴 致命（定时炸弹） | 实测确认期号格式为 `2026271`(YYYYNNN) / `26116`(YYNNN)，代码仅做 `+1` |
| 2 | **状态文件损坏 → 静默清空全部历史** | 🔴 致命 | `dlt/settle.py:67-68` `except: pass` → 返回空状态 → `:443` 覆盖写回 |
| 3 | **编排层零异常隔离**，一个品种挂掉全盘无输出 | 🟠 高 | `unified_review.py:80-91` 无 try/except；已验证 2 条必崩路径 |
| 4 | **数据源滞后 → 重复 pending → 重复结算**，成本/奖金双计 | 🟠 高 | `dlt/settle.py:424-425` 无单调性保护；子代理已注入复现 |
| 5 | **全链路零原子写、零文件锁** | 🟠 高 | 实测 9 处 `json.dump` 全为 `open(w)` 直接覆盖 |
| 6 | z 值方差被放大 1.43 倍，`\|z\|>2` 触发率 10% vs 理论 4.55% | 🟡 中 | 实测 30 个 z 样本 sd=1.195 |
| 7 | 组合变更时 `cost` 不同步；`rotation` 去重不完整 | 🟡 中 | `dlt/settle.py:433`；当前数据 0 例，但轮换日会触发 |
| 8 | `_rotate_portfolio` 空列表 → IndexError 未捕获 | 🟡 中 | `dlt/settle.py:242` `extra[0]` 无保护 |
| 9 | v2 路径完全绕过号码校验；`import` 失败静默回退 v6 | 🟡 中 | `analyze.py:291-295`、`:298-307` |
| 10 | 首抽均衡惩罚分支反转 → ssq 蓝球分布严重畸变 | 🟡 中 | 实测 ssq 蓝球 13/15 号出现率 20.8%/24.8% |

---

## 1. 完整调用链路

### 1.1 顶层编排

```
unified_review.main()  [unified_review.py:413]
  └─ build_summary()   [:80]
       ├─ [1/3] daily_review.main()   [:85]   ← 3D
       ├─ [2/3] dlt_run()               [:87]
       └─ [3/3] ssq_run()               [:89]
     ⚠️ 三者之间【无 try/except】，任一抛异常 → 全脚本非零退出
  └─ wechat_block()     [:415]  ← 摘要文本在此生成
  └─ write_unified_report() [:416]
  └─ print(wechat)      [:418]
  └─ 每月1号: 月度报告   [:423]
```

### 1.2 福彩3D 出号链

```
daily_review.main()  [daily_review.py:475]
  ├─ fetch_data.load_or_fetch()          [:480] → data/3d_history.json（降序163期）
  ├─ load_json(profit_loss.json)         [:498]
  ├─ trading_day.is_trading_day(today)   [:508] → is_holiday（纯日历，不看周末）
  ├─ expected_qihao_for_date()           [:521] → gap>1 ? data_stale
  ├─ settle_pending(history, pl)         [:542] → 只结算第一条命中
  ├─ calc_summary(pl)                    [:546]
  ├─ direct_push_status(history)         [:573] → stop 恒 False [:243]
  ├─ analyze.generate_recommendations()  [:594]  ◄── 唯一出号入口
  │    └─ analyze.py:174
  │        ├─ :198  info["stop"] → return []        【静默出口①】
  │        ├─ :201  len(records)<4 → return []      【静默出口②】
  │        └─ :205  PENDULUM_MODE=True → _generate_v2()  [:282]
  │             ├─ :291  import pendulum_v2（失败 → 静默回退 v6 8注）⚠️
  │             └─ :297  P2.analyze_v2(asc, per_pos=(3,3,2), max_notes=20)
  │                  └─ pendulum_v2.py:174
  │                       ├─ :186 每位 fused_profile → score_zones_v2 → pick_digits_v2
  │                       │      └─ :84  position_profile 窗口 (10,30,60)
  │                       │         :86  n_eff = 1/Σ(w²/n) = 64
  │                       │         :90  freq_p = Σ w·(count_i/n_i)
  │                       │         :92  sd = √(0.09/n_eff)
  │                       │         :93  z = (freq_p-0.1)/sd
  │                       ├─ :198 和值带 = 近100期 P20~P80  [实测 11~18]
  │                       ├─ :203 combos = 3×3×2 = 18 组合
  │                       ├─ :210 tier1(和值带∧跨区) or tier2(宽带) or tier3(仅跨区) or tier4(原样)
  │                       └─ :222 U5 三区互异补入（实测 112/112 天补入为空）
  ├─ target_qihao = int(history[0].qihao)+1   [:607]  ⚠️ 跨年失效
  ├─ 幂等刷新判定：r["notes"] != len(recs)    [:628]  ⚠️ 只比数量
  └─ save_json(profit_loss.json)         [:670]
```

### 1.3 大乐透/双色球 出号链

```
dlt/settle.run_daily()  [:359]
  ├─ fetch_history(100)         [:367] → 当日缓存优先 [fetcher.py:77]
  ├─ load_state()               [:371] ⚠️ 损坏→静默空状态 [:67-68]
  ├─ _settle(st, records)       [:373] → pending→settled
  ├─ _is_rotation_day(today)    [:379] → 锚点 2026-08-14，每14天周五
  ├─ _rotate_portfolio()        [:382] → 换最冷2组 ⚠️ extra[0] 无保护 [:242]
  ├─ 热号核心校验/重建          [:400-421] → 跨月或缺核心号 → 重建5组
  │                                ⚠️ except:pass [:420]
  ├─ next_target = issue+1      [:424]  ⚠️ 无单调性保护
  ├─ pending 查重(按target)     [:427-430]
  │    └─ 轮换/重建时覆盖 notes [:433] ⚠️ 不同步 cost
  ├─ _make_pending() 追加       [:437]  cost = 注数×2
  ├─ _calc_summary(st)          [:442]
  ├─ save_state(st)             [:443] ⚠️ 非原子
  └─ _write_report()            [:446]

内部：selector.generate_notes()  [dlt/selector.py:200]
  ├─ :215 rng = Random(SEED=None)          ← 系统熵，每次不同
  ├─ :216 build_weights  w = freq归一 + 冷号加成0.12 + 扰动U(-0.18,0.18)
  ├─ :217 _red_sum_band  P10~P90（实测 dlt [62,121]）
  ├─ :222 hot_core.get_dlt_core → forced_red = TOP2
  ├─ :254 加权无放回抽样 → _valid_note 过滤（合法率实测45.1%）
  └─ :259 覆盖最大化贪心（val = 新覆盖数 + 0.03×score）
```

---

## 2. 每步判定依据与数据来源

### 2.1 数据源

| 环节 | 来源 | 缓存 | 失败回退 |
|---|---|---|---|
| 3D 主源 | `api.huiniao.top` limit=100 | `data/3d_history.json` | 东财 → 500彩票网 → 本地缓存 |
| 大乐透 | `dlt/fetcher.py:67` | `data/dlt_history.json` | 缓存（`meta.fallback=True`） |
| 双色球 | `ssq/fetcher.py` | `data/ssq_history.json` | 缓存 |

### 2.2 3D 关键参数（实测确认）

```
窗口 WINDOWS=(10,30,60)  权重 (0.25,0.50,0.25)
n_eff = 1/(0.0625/10 + 0.25/30 + 0.0625/60) = 64.0   ⚠️ > 最大窗口60
sd = √(0.09/64) = 0.0375
每位候选 PER_POS=(3,3,2) → 候选池恒 18
和值带 = 近100期 P20~P80  [实测 11~18]
分区：左(0-3) 中(4-6) 右(7-9)
区域分 = 100×(0.45×回摆匹配 + 0.30×区域欠账 + 0.25×区域遗漏)
数字分 = 0.45×区域分/100 + 0.30×相对热度 + 0.25×遗漏归一
过热 |z|>2 罚×0.80   过冷 |z|<-2 罚×0.90
```

### 2.3 大乐透/双色球 `_valid_note` 硬约束

| 约束 | 大乐透 | 双色球 |
|---|---|---|
| 红/前区奇数个数 | 2~3 | 2~4 |
| 红/前区大号个数 | 2~3（阈值18） | 2~4（阈值17） |
| 和值区间 | P10~P90（实测62~121） | 同 |
| 后区/蓝球奇偶 | **严格 1:1** | 无 |
| 后区/蓝球大小 | **严格 1:1** | 无 |
| 连号/AC值/区间比 | 均未校验 | 均未校验 |

### 2.4 轮换锚点（实测确认）

```
ROTATION_ANCHOR = 2026-08-14（周五）
_is_rotation_day: weekday==4 且 (d-anchor).days % 14 == 0
序列：08-14 / 08-28 / 09-11 / 09-25 / 10-09(已过) / 10-23(下次) / 11-06 / 11-20
轮换量 n_replace=2 硬编码于调用处 [:382]
幂等守卫：st["last_rotation_date"] != today
当前实测：dlt/ssq 均为 2026-10-09，core_ym=2026-10 ✅
```

---

## 3. 逻辑漏洞与边界情况

### 🔴 P0-1 跨年期号推算必错（**约 12/28 定时爆发**）

**实测证据**：
```
3D_history.json  期号长度集合 = {7}，范围 2026109~2026271  → 格式 YYYYNNN
dlt_history.json 期号长度集合 = {5}，最新 26116            → 格式 YYNNN

代码：daily_review.py:607  str(int(history[0]["qihao"]) + 1)
      dlt/settle.py:425    str(latest_issue + 1)
      ssq/settle.py:407    str(latest_issue + 1)
      trading_day.py:128   anchor_qihao + td
```

**推演**：
- 3D：`2026351 + 1 = 2026352`，真实下期是 `2027001` → `daily_review.py:96-101` 的 `endswith` 永久匹配不上 → 每天走「⏸ 目标期号尚未抓到」→ **结算永久卡死**，pending 持续堆积（每次只清一条）。
- 大乐透/双色球：`26151 + 1 = 26152`，真实下期 `27001` → 按 `target_issue` 查重永远命中不了旧 pending → **组合永久冻结**，直到手工修数据。
- 触发时间：3D 约 **2026-12-31**，大乐透/双色球约 **2026-12-28**。

**附带**：`holidays.json` 只覆盖 2026 年（实测 14 项），`trading_day.py:28-34` 的 `_FALLBACK_HOLIDAYS` 同样硬编码 2026 → **2027 年春节 3D 会在官方休市日"出号"，产生假亏损记录**。

### 🔴 P0-2 状态文件损坏 → 静默清空全部历史

`dlt/settle.py:57-70`（`ssq/settle.py:45-57` 同构）：
```python
try:
    st = json.load(f)
    ...
except Exception:
    pass                      # ← 静默
return {... "records": [] ...}   # ← 返回全新空状态
```
配合 `save_state` [:73-76] 的 `open(path,"w")` 直接覆盖 → **下一行代码就把 26 条结算历史（含累计 -235 元）彻底抹除，且推送摘要照常输出**。

子代理实测：把文件截断成半截 JSON 后再跑，`records` 从 26 → 1，summary 全归零，`error` 字段为 `False`（即"一切正常"）。

### 🟠 P1-1 编排层零异常隔离（2 条已验证必崩路径）

```python
# unified_review.py:80-91
r3 = daily_review.main()   # :85
rd = dlt_run()             # :87
rs = ssq_run()             # :89
# 【无 try/except】
```

**路径 A（必崩）**：`daily_review.py:481-483` 抓取失败时 `return`（隐式 `None`）→ `unified_review.py:103` `r3.get("yesterday_draw")` → `AttributeError: 'NoneType' object has no attribute 'get'`。

**路径 B（必崩）**：`dlt/settle.py:368-369` 抓取失败返回 `{"error":..., "notes":[]}`，**缺 `summary` 键** → `unified_review.py:166` `rd["summary"]` → `KeyError`。

**失败模式是"静默失联"**：摘要打印在最后（`:418`），异常在 `:418` 之前 → **微信侧完全收不到当日消息**，且无任何日志。

### 🟠 P1-2 数据源滞后 → 重复结算、成本双计

`dlt/settle.py:424-425`：
```python
latest_issue = int(records[0]["issue"])
next_target = str(latest_issue + 1)     # ⚠️ 无单调性保护
```
`_settle` [:110-160] 只判断 `tgt > latest_issue → continue` 和 `draw is None → continue`，**无 target 唯一性约束**。

**放大器**：`fetcher.py:77-88` 同一天复用缓存 → 当日 07:00 抓到旧数据后，当天再跑永远拿同一份旧数据。

子代理注入滞后一期后实测：`target=26116` 出现 2 条记录，summary `rounds 25→26, total_cost 260→270, total_prize 25→30`。

**当前状态实测**：`dlt` 26 条 / `ssq` 25 条，**重复 target = 0**，cost 与注数不符 = 0 例 → 尚未发生，但结构性缺陷存在。

### 🟠 P1-3 全链路零原子写、零文件锁

**实测 9 处写盘点全部为 `open(path,"w") + json.dump`**：
```
daily_review.py:66   data/profit_loss.json     (105 KB)
hot_core.py:74       data/hot_core.json
dlt/settle.py:75     data/dlt_state.json        ( 43 KB)
ssq/settle.py:63     data/ssq_state.json        ( 42 KB)
fetch_data.py:357    data/3d_history.json
dlt/fetcher.py:107   dlt_history.json
ssq/fetcher.py:119   ssq_history.json
（+ 3 处报告 md）
```
实测全仓无 `flock` / `msvcrt` / `os.replace` / `.tmp` 匹配，无任何 `.lock` 文件。

**并发最坏场景**（自动化 05:00 + 用户手动跑）：
1. A 读到 S0（26条含 pending 26117）
2. A 结算 26117 为 settled，准备写盘
3. B 在 A 落盘前读到同样的 S0
4. **A、B 都判定"不存在 target=26118"，各自 append 一条**
5. B 的版本覆盖 A → **A 的 `last_rotation_date` 轮换结果丢失**
6. 3D 侧更糟：A 已把昨日 `hits/prize/daily_pnl` 写好，B 的陈旧副本 `today_exists=False` → append 同 date 记录 → **昨日结算被回滚，次日重复结算**

叠加非原子写：Windows 下 `open(w)` 立即截断，两进程 `json.dump` 交错 → **必然产生损坏文件** → 触发 P0-2 级联。

### 🟡 P2-1 z 值方差被系统性放大

`pendulum_v2.py:86-93`：
```python
inv = Σ w²/n_i
n_eff = 1/inv          # = 64.0  ⚠️ 但最大窗口只有 60
sd = √(0.1*0.9/n_eff)
z = (freq_p - 0.1)/sd
```
`n_eff=64 > 60` 在数学上不成立——重叠嵌套窗口不可能比最长窗口更独立。该公式假设三窗口独立。

**主控实测（163期×3位置×10数字 = 30 样本）**：
```
z mean = -0.0000    sd = 1.1953    方差放大 1.43 倍
|z|>2 占比 = 10.0%  （正态理论 4.55%）
```
（注：子代理报 sd=1.484，主控用 163 期实测为 1.195；量级结论一致，具体数值以实测为准。）

**后果**：`HOT_CAP=2.0` 的过热/过冷判定从 4.55% 触发率升到 10%，罚分被施加到不该触发的数字上。

### 🟡 P2-2 U5 多样性约束 100% 空转

子代理 160 天回放实测：U5 判定触发 112/160 天（70%），但**补入列表 112/112 天全为空**，实际增加注数 0 天。原因：`need = int((1/3)·len(notes))` 取整后常为 0，或候选池物理上无更多三区互异组合（62/160 天候选池三区互异数为 0）。代码空转一次 `for` 循环，**无任何记录**。

### 🟡 P2-3 v2 路径完全绕过号码校验

```python
# analyze.py:298-307
res = P2.analyze_v2(...)
for n in res["notes"]:
    notes.append(_mk_note([b,s_,g], logic))   # 无去重/无越位/无上限/无校验
```
`_validate_direct_notes` 只在 `_generate_direct`（v6 路径）内被调用。且其失败处理是 `analyze.py:372-373`——**仅拼字符串后照常返回、照常下注**。

更危险的是 `analyze.py:291-295`：`import pendulum_v2` 失败 → **静默回退 v6（8注，读 `hot_core` 的 `3d_pos`）**。而 `data/hot_core.json` 里 `3d_pos.ym` 仍是 `2026-09` → **10 月的 3D 会用 9 月的热号出号，且报告里完全看不出来**。

`LAST_GEN` 虽记录了这些诊断，但 `daily_review.main()` **从不读取它** → 诊断信息不进报告、不进 profit_loss.json。

### 🟡 P2-4 首抽均衡惩罚分支反转

`dlt/selector.py:117-132` / `ssq/selector.py:114-129`：
```python
if totals["b_odd"] > totals["b_even"]:   # 首抽时 0 > 0 == False
    惩罚奇数
else:
    惩罚偶数                            # ← 首抽总是走这里
```
子代理实测 40000 次：
| 指标 | 理论 | 实测 |
|---|---|---|
| ssq 蓝球奇数占比 | 50% | **75.47%** |
| ssq 蓝球大号(≥9)占比 | 50% | **81.05%** |
| ssq 蓝球 13号/15号 | 6.25% | **20.76% / 24.80%** |

ssq 因 `_valid_note` 对蓝球无约束，**畸变直接进入出号结果**。

### 🟡 P2-5 其他已确认问题

| 问题 | 位置 | 说明 |
|---|---|---|
| 轮换/重建覆盖 `notes` 不同步 `cost` | `dlt/settle.py:433` | 当前 0 例（实测 cost 全部 = 注数×2），但轮换日会触发 |
| `_rotate_portfolio` 空列表 IndexError | `dlt/settle.py:242` `extra[0]` | 轮换日 + 池空 → 崩溃，`last_rotation_date` 不推进 |
| 去重基准只含 `remaining` | `dlt/settle.py:216` | 可能换回刚换掉的号 |
| 僵尸元数据 | `profit_loss.json` | `end_date='2026-08-31'` 但记录到 10-13；`prize_per_hit=160` vs 实际 1040 |
| `last_gen_desc` 不被调用 | `analyze.py:210` | 引擎降级/和值带/候选池比全部不可见 |
| 步骤[5/7]固定文案「推8注」 | `daily_review.py` | 实际今日 13 注（已连续多日不符） |
| `.edge_profile` 810 文件入库 | git | 占跟踪文件 63%，13MB+，浏览器 profile 误提交 |

---

## 4. 优化建议与实现方案

### 🟢 A 类：零风险（不改出号结果，只加健壮性/锁/告警）

#### A1. 原子写 + 文件锁（修 P0-2、P1-3）★ 最高优先级

新建 `atomic_io.py`，全仓替换 9 处写盘点：

```python
# atomic_io.py
import json, os, tempfile, time

def _lock(path, timeout=30):
    """跨进程排他锁；Windows 用 msvcrt，POSIX 用 fcntl。"""
    import sys
    lk = os.path.join(os.path.dirname(path), "." + os.path.basename(path) + ".lock")
    f = open(lk, "a+b")
    f.seek(0, os.SEEK_END)
    if f.tell() == 0:
        f.write(b"\0"); f.flush()
    deadline = time.time() + timeout
    while True:
        try:
            f.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return f
        except OSError:
            if time.time() > deadline:
                f.close()
                raise TimeoutError("获取锁超时: %s" % lk)
            time.sleep(0.2)

def _unlock(f):
    import sys
    try:
        if os.name == "nt":
            import msvcrt
            f.seek(0); msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    finally:
        f.close()

def save_json_atomic(path, data):
    """tmp + os.replace 原子写。读者永远看到完整的旧版或新版。"""
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix="." + os.path.basename(path), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush(); os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise

def save_locked(path, data):
    """带锁的原子写（用于单次读改写事务）。"""
    f = _lock(path)
    try:
        save_json_atomic(path, data)
    finally:
        _unlock(f)
```

**必须同时修 `load_state`**（否则"损坏→清空"级联仍在）：
```python
# dlt/settle.py:57 / ssq/settle.py:45
def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                st = json.load(f)
        except json.JSONDecodeError as e:
            # 不再静默返回空状态：备份后抛出，交由编排层捕获并跳过本品种
            bad = STATE_FILE + ".corrupt-" + __import__("time").strftime("%Y%m%d%H%M%S")
            os.replace(STATE_FILE, bad)
            raise RuntimeError("状态文件损坏，已备份至 %s：%s" % (bad, e))
        st.setdefault("records", []); st.setdefault("summary", _empty_summary())
        st.setdefault("portfolio", []); st.setdefault("last_rotation_date", None)
        return st
    return {...}
```

**收益**：消除不可逆数据丢失 + 并发写损坏。
**风险**：`.lock` 文件会驻留 `data/`，需 `.gitignore` 加 `data/*.lock` 与 `data/.*.tmp`。

#### A2. 编排层阶段化隔离 + 失败显式标注（修 P1-1）

```python
# 新建 alerts.py（独立模块，避免与 unified_review 循环导入）
class Alerts:
    def __init__(self): self.items = []
    def add(self, sev, scope, msg): self.items.append((sev, scope, msg))
    def render(self):
        if not self.items: return []
        out = ["━━ ⚠️ 运行告警 %d 条 ━━" % len(self.items)]
        for sev, scope, msg in self.items:
            out.append("  [%s] %s：%s" % (sev, scope, msg))
        out.append("  ⚠️ 以上异常可能导致数据不完整，号码与盈亏不可作为完整依据。")
        return out

ALERTS = Alerts()
```

```python
# unified_review.py:80-91 替换
def _stage(name, fn):
    try:
        return fn()
    except Exception as e:
        print("  ❌ %s 失败：%s: %s" % (name, type(e).__name__, e))
        ALERTS.add("ERROR", name, "运行失败：%s: %s" % (type(e).__name__, e))
        return _err(name)

def _err(name):
    """失败占位：语义明确为'运行失败'，绝不复用'无待结算'。"""
    return {"game": name, "failed": True,
            "yesterday_draw": None, "settled": None, "recommendations": [],
            "notes": [], "target": None, "latest_issue": None, "trend": None,
            "summary": {"net_pnl": 0, "total_hits": 0, "total_bets": 0,
                        "rounds": 0, "pending_rounds": 0}}

def build_summary():
    ...
    r3 = _stage("福彩3D", daily_review.main)
    rd = _stage("大乐透", dlt_run)
    rs = _stage("双色球", ssq_run)
    return today, yesterday, r3, rd, rs
```

配套：
- `wechat_block` 中**先判 `failed` 再判空**，杜绝「待None期开奖」
- 合计行追加「（含 N 个品种运行失败，合计偏低）」
- `dlt/settle.py:369` / `ssq/settle.py:351` 的 error dict **补齐 `summary` 等缺失键**
- `unified_review.py` 末尾、`ALERTS.render()` 插入到免责行之前

**收益**：任一品种失败不再拖垮全局，且推送侧可见。
**风险**：无（纯新增分支）。

#### A3. 跨年期号修复（修 P0-1）★ 12/28 前必须完成

```python
# 新建 period_util.py
def next_qihao_3d(cur: str) -> str:
    """3D: YYYYNNN，2026351 -> 2027001"""
    y, n = int(cur[:4]), int(cur[4:])
    n += 1
    if n > 366:                      # 3D 全年约 351 期，366 为安全上界
        y, n = y + 1, 1
    return "%d%03d" % (y, n)

def next_issue_yy(cur: str) -> str:
    """大乐透/双色球: YYNNN，26151 -> 27001"""
    y, n = int(cur[:2]), int(cur[2:])
    n += 1
    if n > 155:                      # YYNNN 上限约 151~155
        y, n = (y + 1) % 100, 1
    return "%02d%03d" % (y, n)
```

**替换点**：`daily_review.py:607`、`:349`、`dlt/settle.py:425`、`ssq/settle.py:407`；`trading_day.py:128` 的 `expected_qihao_for_date` 需同步跨年进位。

**上线前必须跑历史回归**（对全部 163 期 + 100 期逐期断言 `next_*(h[i]) == h[i-1]`）。当前 2026 年内数据不会触发进位分支 → **对当期出号零影响**。

#### A4. target 单调性守卫（修 P1-2）

```python
# dlt/settle.py:424 前插入
latest_issue = int(records[0]["issue"])
next_target = str(latest_issue + 1)

max_target = max((int(r["target_issue"]) for r in st["records"]), default=0)
if int(next_target) <= max_target:
    # 数据源滞后 → 复用已有 pending，不新建（避免对已开奖期号下注 + 重复结算）
    pend = [r for r in st["records"] if r.get("status") == "pending"]
    if pend:
        newest = max(pend, key=lambda r: int(r["target_issue"]))
        notes, target = newest["notes"], newest["target_issue"]
        _calc_summary(st); save_state(st)
        ALERTS.add("WARN", "大乐透",
                   "数据源滞后（最新期 %s < 已挂 %s），复用已有 pending，未新增注"
                   % (latest_issue, max_target))
        return _finish(...)
```

同时 `_settle` 内增加已结算 target 的去重防护（`seen_settled` 集合）。

#### A5. 静默失败 → 结构化告警

逐个替换当前的 `except: pass`：
| 位置 | 改为 |
|---|---|
| `unified_review.py:134/169/224` hot_core 异常 | `ALERTS.add("WARN", "热号", str(e))` |
| `unified_review.py:369/381` 月度聚合失败 | `ALERTS.add("ERROR", ...)` |
| `dlt/settle.py:420` 核心号校验异常 | `ALERTS.add("WARN","大乐透","核心号校验异常：%s" % e)` |
| `daily_review.py:532` 期号推算 ValueError | `data_stale = True`（当前是 `pass`，导致用过期数据出号） |
| `dlt/ssq settle.run_daily` 返回 | 增加 `warnings: []` 字段（EMPTY_PORTFOLIO / PARTIAL_NOTES / DATA_FALLBACK / THIN_HISTORY / CORE_YM_DRIFT / PENDING_ZERO_NOTES） |

#### A6. 让出号诊断可见

`analyze.py:303-306` 的 `LAST_GEN` 已有全部诊断信息，但 `daily_review` 从不读取。改为把它拼进 `reason` 与报告的「出号判定」节，并写入 `profit_loss.json`：
```python
# daily_review.py:600 附近
from analyze import last_gen_desc
reason = (f"{info['push_type']}{len(recs)}注随机采样｜{last_gen_desc()}｜"
          + "; ".join(cb["rules_fired"] or ["正常出号"]))
```
**收益**：和值带、候选池→注数比、引擎降级第一次可见。**风险：无**（纯附加）。

### 🔴 B 类：会改变出号结果（需明确决策）

| # | 位置 | 改动 | 影响 | 风险 |
|---|---|---|---|---|
| B1 | `pendulum_v2.py:86-87` | `n_eff = min(1/Σ(w²/n), max_window)` → 64 降到 60 | sd +3.2%，部分数字过热/过冷状态翻转 | **160/160 天出号全变**，必须先回测 |
| B2 | `pendulum_v2.py:222-226` | U5 改为「在已选 notes 内替换」而非「补入」 | 注数不变，三区互异占比真正达 1/3 | 112/160 天号码改变 |
| B3 | `ssq/dlt selector.py:117-132` | 修首抽分支反转（`>` → 首抽跳过惩罚） | ssq 蓝球分布回归正常 | **全部历史号码改变** |
| B4 | `dlt/settle.py:169-172` | 放宽后区严格 1:1 | 合法率 45%→~100%，池更大 | 违背 v3「均衡」设计意图 |
| B5 | `pendulum_v2.py:216-219` | 记录实际生效 tier（纯附加字段） | 无出号影响 | 归 A 类更合适 |
| B6 | `analyze.py:291-295` | v2 导入失败改为抛错而非静默回退 v6 | 消除「用 9 月热号出 10 月号」风险 | 抛错会中断 3D 全链路，需权衡 |

**我的判断**：B1/B2/B3 都是**在修正统计缺陷**，不是提升预测力——修完之后每注中奖概率依然恒定（直选 0.1%、ROI 52%）。但既然目的是「不改变已有行为」，建议 **A 类全部先落地，B 类单独排期并带回测**。

---

## 5. 建议实施顺序

| 优先级 | 项 | 理由 |
|---|---|---|
| **P0** | A1 原子写+锁+损坏即停 | 唯一会导致**不可逆数据丢失**的路径 |
| **P0** | A3 跨年期号 | **12/28 前必须完成**，之后结算全线静默失效 |
| **P1** | A2 编排隔离+告警 | 让失败可见，杜绝静默失联 |
| **P1** | A4 target 单调性守卫 | 防成本/奖金系统性双计 |
| **P2** | A5 静默失败告警 | 可观测性 |
| **P2** | A6 出号诊断入报告 | 审计可信度 |
| **待决策** | B1~B4 | 改变出号结果，需回测 + 明确授权 |
| **顺手** | 步骤[5/7]固定文案；`.edge_profile` 出库；清理僵尸元数据 | 不改逻辑 |

---

## 6. 本次审计未能确认的点

1. **自动化任务的工作目录（CWD）**——`daily_review.py:53-55` 与 `fetch_data.py:21` 用相对路径 `"data/..."`。若定时任务非从项目根启动，将读写**另一份 data/**。**这是最高优先的待确认项。**
2. **`verify_data.py` 是否被自动化调用**——不在 `unified_review.py` 的 import 链中，双源校验形同虚设。
3. **B2（U5 替换）对成本/中奖率的实际影响**——需跑 walk-forward 回测。
4. **`n_eff` 自相关在更长历史（`backtest_3d_long.json`）上是否同样成立**——仅验证了 163 期。
5. **子代理报 sd=1.484 vs 主控实测 1.195** 的差异原因——可能源于样本区间不同（子代理可能用了不同切片），**以主控实测为准，但值得复核**。
6. **`fix_settlement.py` / `settle_and_report.py` 的历史运行记录**——二者 import 即执行顶层写盘语句，若曾与自动化并发可能解释 `target_qihao` 重复（实测历史有 `2026190`×2、`2026199`×3，均在 2026-08 前）。
7. **月度报告历史产出情况**——`data/reports/` 下 304 个 md 中未见 `*-monthly.md`，10-01 是否真的生成了待确认。

---

*报告生成：小窦 | 审计基线 6166f85 | 本次未修改任何源码*
