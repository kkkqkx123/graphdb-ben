# Linkrs 对等 Ladybug 公开数据集基准：设计方案

**日期**: 2026-11-11  
**对照仓库**: `https://github.com/ladybugdb/benchmarks` @ `42dd288`  
**对照分析**: `当前工作区/docs/ladybug-benchmarks.md`  
**本仓库现状**: Linkrs 已有约 30 个 Criterion / plain-main 微基准，数据为合成图（千～万级顶点），定位防回归，不是权威吞吐。`docs/plan/large_scale_validation_plan.md` 规划了 1M/5M/10M 合成规模，尚未覆盖 Ladybug 使用的公开数据集。

目标：用 **同一批源 CSV、同一组查询语义、同一套计时口径**，在 Linkrs 上复现 Ladybug 三条流水线，使两边数字可以直接并排。

---

## 1. 为什么现有 benches 不够

| 现有能力 | 缺口 |
|----------|------|
| `olap_e2e_bench`：5k 顶点 BA 合成图，Q1–Q5 | 无 LDBC / ClickBench / Graph500 真实分布 |
| `ingest_bench` / `perf_bulk_load`：自造 GQL INSERT | 未测 `COPY FROM` 对亿级 CSV 的导入 |
| `traversal_perf_bench`：20k 顶点 | 无 8 跳 LSQB、无 LDBC IC/IS |
| `csr_perf_bench`：核心 4096 顶点 | Graph500-27 是 2^27 点量级 |
| 图函数 `pagerank` / `connected_components` | 无 k-core / SCC / Louvain；无投影图 API |
| 根 `benches/data/generate_benchmark_data.py` | 只生成 GQL INSERT，不消费外部 CSV |

对等测试必须 **复用 Ladybug 的源文件**，而不是再生成一份近似图。否则度分布、字符串基数、zonemap 选择性都不可比。

---

## 2. 公平对比的硬约束

1. **同一份 CSV**。两边都从 `$CSV_DIR`（及 LSQB 官方 tar.zst、ClickBench `hits.csv.gz`）导入。禁止各自 Datagen 再生。
2. **同一查询语义**。结果行数、Top-N 值必须与 Ladybug `.benchmark` 的 `expectedNumOutput` 对齐。对不上先修查询或标 skip，不上报。
3. **同一计时口径**。主套件：warmup=1、run=5，分开 compiling / executing。LSQB：warmup=1、run=3、去 max 再平均。Click 独立脚本：每次 `drop_caches`、3 次 wall-clock。
4. **同一硬件与构建**。同一台机器、同一 NUMA、同一磁盘。Linkrs 默认 `x86-64-v3`（AVX2）；Ladybug 按官方 release 构建。报告必须写明双方二进制、commit、线程数、buffer/内存上限。
5. **Embedded 路径，不走 HTTP/gRPC**。Ladybug 主套件调 C++ `lbug_benchmark` / shell，无网络。Linkrs 对应用 `GraphDatabase` + `session.execute`（或 `QueryPipelineManager`），避免把传输层算进查询时间。
6. **导入单独成组**。COPY 耗时上报为 `query_group=copy`，与查询时间拆开，对应 Ladybug 的 copy log。

做不到语义对齐的查询（见第 6 节）进入 **skip 清单**，对比表里标 `N/A`，不拿近似查询充数。

---

## 3. 推荐落点

跨存储 + 查询 + 导入，且要跟外部 Python runner 协作。按 `benches/README.md`：「跨 3 个以上工作区包、或触及网络传输层的端到端基准，才考虑放在根目录」。本套件符合前者。

```
benches/parity/                          # 根目录新套件，不塞进各 crate
├── README.md
├── runner.py                            # 统一入口：serialize → run → report
├── serialize.py                         # CSV → Linkrs COPY，版本缓存
├── compare.py                           # 读两边 JSON，出 markdown 对比表
├── schema/
│   ├── ldbc_snb.cypher                  # CREATE TAG/EDGE，从 serialize.cypher 翻译
│   ├── lsqb.cypher                      # 从 lsqb/schema.cypher 翻译
│   ├── click.cypher                     # hits 宽表
│   └── algo_graph.cypher                # person + knows（Graph500 / LJ / sf10k）
├── queries/                             # 与 ladybug/queries 同构
│   ├── ldbc-sf100/<group>/*.benchmark
│   ├── click/click/*.benchmark
│   ├── graph500-27/algo/*.benchmark
│   ├── soc-livejournal/algo/*.benchmark
│   ├── datagen-sf10k/algo/*.benchmark
│   └── lsqb/q1.cypher … q9.cypher
└── adapters/
    ├── dialect.py                       # Ladybug Cypher → Linkrs 方言
    └── expected.py                      # 解析 ---- N 与期望行
```

查询文件 **直接拷贝** Ladybug 的 `.benchmark` / `.cypher`，差异全部进 `adapters/dialect.py`。Ladybug 更新查询时，diff 只落在 adapter，不改两份查询正文。

执行器：新增 binary `linkrs-parity-bench`（放 `crates/linkrs-query` 或根 crate，`harness = false`），读取 `--dataset` / `--warmup` / `--run` / `--thread`，对每个 `.benchmark` 跑 session.execute，写出与 Ladybug 同结构的 log（`Status` / `Compiling time` / `Execution time`）。Python runner 只负责编排、COPY、上传。

不把这套塞进 Criterion：公开数据集要分钟～小时级，Criterion 的 1s warmup / 10s measure 窗口不适用。沿用 Ladybug 的固定次数模型。

---

## 4. 数据获取与目录约定

环境变量与 Ladybug 对齐，便于同一台机器两边共用磁盘：

| 变量 | 含义 |
|------|------|
| `CSV_DIR` | 预置 CSV 根目录 |
| `SERIALIZED_DIR` | Linkrs 持久化库缓存 |
| `SCALE_FACTOR` | LSQB 规模，默认 `100` |
| `PARITY_THREADS` | 查询线程，默认 CPU affinity |
| `DRY_RUN` | 只跑不上报 |

物理布局（与 Ladybug 相同，零拷贝共享）：

```
$CSV_DIR/
  ldbc-10/csv/*.csv
  ldbc-100/csv/*.csv
  click/hits                  # 或 hits.csv
  graph500-27/csv/
  soc-livejournal/csv/
  datagen-sf10k/csv/

/tmp/lsqb-datasets/social-network-sf<sf>-projected-fk/   # runner 自动下载
```

Linkrs 缓存：

```
$SERIALIZED_DIR/linkrs-<dataset>-serialized/
  db/                         # GraphDatabase 数据目录
  version.txt                 # cargo pkg version 或 git HEAD
  copy_logs/                  # 各表 COPY 耗时
```

版本一致则跳过 COPY。Ladybug 的 `db.lbdb` 与 Linkrs 数据目录 **不能** 互换，只共享上游 CSV。

LSQB 下载逻辑原样移植 `lsqb/benchmark_runner.py` 的 `download_dataset`（同一 URL、同一 `/tmp/lsqb-datasets` 缓存）。Click 独立脚本继续 wget `https://datasets.clickhouse.com/hits_compatible/hits.csv.gz`。

---

## 5. 导入路径（serialize）

Ladybug：`CREATE NODE/REL TABLE` + `COPY t FROM "f.csv" (HEADER=true, DELIM="|")`，每条语句一个进程。  
Linkrs：`CREATE SPACE` + `CREATE TAG/EDGE` + `COPY VERTEX/EDGE … FROM 'f.csv' WITH (HEADER true, DELIMITER '|', BATCH_SIZE n)`。

### 5.1 Schema 翻译规则

| Ladybug | Linkrs |
|---------|--------|
| `CREATE NODE TABLE Person (ID INT64, …, PRIMARY KEY(ID))` | `CREATE SPACE ldbc (vid_type=INT64)`；`CREATE TAG Person(firstName STRING, …)`；CSV 的 `ID` 列作为 **vid**，不进属性 |
| `CREATE REL TABLE knows (FROM Person TO Person, creationDate TIMESTAMP, MANY_MANY)` | `CREATE EDGE knows(creationDate TIMESTAMP)`；COPY 边 CSV 前两列映射为 `src,dst` |
| `INT64` / `STRING` / `DATE` / `TIMESTAMP` | `INT64` / `STRING` / `DATE` / `TIMESTAMP`（已对齐） |
| `INT16` / `INT128`（Click hits） | `INT` / `INT128` 或降级为 `INT64`（导入前用探针查询确认；INT128 若未实现则 skip 相关列或整套 click） |
| `SERIAL` 主键（hits.ID） | SPACE `vid_type=INT64` + 导入时生成单调 vid，或 CSV 增加一列 row number |

边 CSV：Ladybug LDBC 为 `person_knows_person_0_0.csv`，列 `Person.id|Person.id|creationDate`。Linkrs COPY EDGE 要求 header 含 `src,dst`（见 `copy_e2e.rs`）。serialize 阶段 **改写 header** 或写 sidecar CSV，不改原始文件：

```
Person.id|Person.id|creationDate   →  src|dst|creationDate
```

LSQB 边表已是 `PersonId|PersonId`，同样改名为 `src|dst`。

### 5.2 导入执行

1. `CREATE SPACE IF NOT EXISTS <dataset> (vid_type=INT64)` + `USE`。
2. 执行翻译后的 DDL。
3. `storage.begin_bulk_load()`，避免逐批 checkpoint（`perf_bulk_load.rs` 已验证缺了会 O(n²)）。
4. 先 COPY 全部顶点，再 COPY 边（边端点必须先存在）。
5. `finish` 一次 checkpoint。
6. 每张表记 compiling/executing（execute 返回前后 `Instant`；若 session 能拆 parse/plan/exec 则分开报，对齐 Ladybug）。
7. 写 `version.txt`。

Click hits：Ladybug 因引号换行强制 `PARALLEL=false`。Linkrs COPY 若不能正确处理 quoted newline，先用 Python 预处理成无内嵌换行的 CSV，或单线程 `BATCH_SIZE` 小批量；预处理步骤写入报告，避免被算成引擎优势。

LSQB 的 `Person_knows_Person_bidirectional.csv` 与 Message 视图：**复用 Ladybug serializer 的 convert()**，不要第二份转换逻辑。convert 后的 CSV 两边共用。

单线程可复现：`PARITY_THREADS=1` 时 COPY 也单线程，对应 Ladybug `--single-thread` / `CALL THREADS=1`。

---

## 6. 查询适配与 skip 清单

`adapters/dialect.py` 做机械替换，禁止手改查询语义。

### 6.1 可自动翻译（纳入对比）

| Ladybug | Linkrs | 出现位置 |
|---------|--------|----------|
| `create node/rel table` | `CREATE TAG/EDGE` | schema |
| `MATCH (a:Person)-[:knows]->(b:Person)` | 同形，标签/边名保持 | LDBC 算子组 |
| `timestamp('2010-02-14 …')` | 确认 `timestamp()` / `datetime()` 哪个可用，统一替换 | `ldbc_snb_ic` |
| `concat(a,b)` | `concat` 或 `a + b` | IC |
| `date_part("minute", t)` | `date_part`（文档称日期函数广） | Click |
| `SIZE(s)` | `size` / `length` | Click q28 |
| `REGEXP_REPLACE` / `=~` | 已支持 `=~`；函数名按绑定表替换 | Click |
| `id(a) == N` | Linkrs 用 `==`；Ladybug 用 `=`。adapter 保持各自写法 | OLAP 已有先例 |
| `* ALL WSHORTEST(weight)` | `*WEIGHTED(weight)` 或 `*WSHORTEST(weight)` | datagen-sf10k |
| `COUNT(*)` / `MIN` / `AVG` | 直接用 | 全局 |
| `LOAD EXTENSION algo; CALL page_rank('PK')` | `RETURN pagerank()` / 表函数形态，见 6.2 | algo |

LDBC-sf100 的 54 条算子查询、Click 43 条、LSQB q1–q9，预期 **大部分可跑**。第一轮先跑这三组，作为对比主体。

### 6.2 图算法（部分可对、部分 skip）

Linkrs `GraphFunction` 已有：`pagerank`、`connected_components`、`shortest_path`、`bfs`。  
Ladybug algo 扩展还有：`k-core`、`scc`、`scc-ko`、`louvain`、`PROJECT_GRAPH`。

| 查询 | 策略 |
|------|------|
| PageRank | 对等：同一图、同一 Top-10 按 rank 排序。数值允许相对误差（阻尼/迭代次数写进报告，默认阻尼 0.85、迭代对齐 Ladybug 默认） |
| WCC | 对等到 `connected_components`（若实现为弱连通）。校验最大分量大小：LJ 期望 4843953，Graph500-27 期望 63039352 |
| 加权最短路 | 对等到 `*WEIGHTED` / `FIND SHORTEST`，校验 datagen-sf10k 的 Top-10 cost |
| k-core / SCC / Louvain | **skip**，直到 Linkrs 实现同名算法。禁止用近似图函数冒充 |

`PROJECT_GRAPH`：Ladybug 先投影再跑算法。Linkrs 无投影图则对全图 `person`/`knows` 跑，语义等价（这些数据集本来就只有这一对类型）。

### 6.3 明确 skip（对比表标 N/A）

- Ladybug zonemap 专测（`zonemap-node.benchmark` 等）：Linkrs 若无 zone map，跑了也不可比。
- `CALL THREADS=` / `CALL DB_Version()` 等系统调用差异。
- Click 中依赖 INT128 精确聚合、且 Linkrs 无 INT128 的查询。
- 需要 `PROJECT_GRAPH` 多标签子集的算法（当前三份算法图不需要）。

skip 文件列表检入 `benches/parity/skip.txt`，格式：`dataset/group/name  reason`。

---

## 7. 三条流水线在 Linkrs 上的实现

### 7.1 主套件（算子微基准）

对应 `benchmark_runner.py` + `lbug_benchmark`。

```
linkrs-parity-bench \
  --dataset=$SERIALIZED_DIR/linkrs-ldbc-sf100-serialized/db \
  --benchmark=benches/parity/queries/ldbc-sf100/<group> \
  --warmup=1 --run=5 --thread=$PARITY_THREADS \
  --out=/tmp/linkrs_benchmark_logs/<group>
```

每个 `.benchmark`：

1. adapter 翻译 `-QUERY`（及 `-PRERUN`/`-POSTRUN`）。
2. warmup 1 次，丢弃时间。
3. run 5 次；每次记录 parse+plan（compiling）与 execute（executing）。若 pipeline 已有 `query_stage_bench` 的阶段拆分，直接复用。
4. 把结果行物化，与 `---- N` 及期望文本比对；失败记 `Status: error`。
5. 写 log，字段名与 Ladybug `QueryBenchmark` 一致，便于 `compare.py` 双边解析。

资源：线程数取 `sched_getaffinity`；内存上限写入报告（Linkrs 无 `--bm-size`，改报进程 RSS 峰值与 cgroup memory.max）。不要为了“看起来公平”去限制 Linkrs 内存到 Ladybug bm-size——那是不同引擎的缓冲池模型。报告里并排写双方内存，读者自己判断。

数据集优先级（工作量升序）：

1. `ldbc-sf10` 冒烟（查询与 sf100 同构，数据小）
2. `ldbc-sf100` 主对比（54 queries）
3. `click`（43 queries，导入最慢）
4. `soc-livejournal` → `graph500-27` → `datagen-sf10k`（算法组，仅 PR/WCC/WSHORTEST）

### 7.2 LSQB

对应 `lsqb/benchmark_runner.py`。

1. 下载 + convert（共享 Ladybug 脚本或 vendoring 其 convert 函数）。
2. serialize 到 `linkrs-lsqb-sf<sf>-serialized`。
3. 对 q1–q9：warmup 1 + run 3，去 max 平均；`psutil` 记 RSS 增量。
4. 写 `/tmp/benchmark_result/linkrs_lsqb.csv`，列与 Ladybug 相同：`engine, query, threads, sf, time_s, memory, output`。
5. 可选 timeout（毫秒），超时行写 `Timeout`。

查询是纯 `MATCH … RETURN count(*)`，方言几乎不用改。这是 **最先应该跑通的端到端对比**：数据官方可下、查询短、正确性就是一个整数。

### 7.3 ClickBench 独立脚本

对应 `click/benchmark.sh`。

```
create space + CREATE TAG hits(...)     # schema/click.cypher
COPY VERTEX hits FROM 'hits.csv' WITH (HEADER true, DELIMITER ',', BATCH_SIZE …)
for query in queries.cypher:
    sync; drop_caches
    跑 3 次 wall-clock（Python timeit 或 Instant）
整理 benchmarks.json，数组形状与 ClickHouse ClickBench 提交格式一致
```

主套件里的 43 条 `.benchmark` 仍走 7.1（热缓存、warmup+5）。独立脚本测冷缓存，两套都要，和 Ladybug 一样。

---

## 8. 对比产物

`compare.py` 读：

- Ladybug：其 runner 上传 JSON，或本地 `/tmp/benchmark_logs` + copy logs
- Linkrs：同结构 JSON（`benches/parity/results/<date>-<gitsha>-<dataset>.json`）

输出 `docs/archive/perf/parity/<date>-<dataset>.md`：

```
| group | query | ladybug exec ms (median of 5) | linkrs exec ms (median of 5) | ratio (linkrs/ladybug) | rows match |
```

规则：

- 只比 **execution_time** 的中位数（5 次里取中位，比 Ladybug 全量上报更稳；附录保留 5 次原始值）。
- compiling_time 另表，不并进 exec。
- COPY 另表：每张表秒数 + 总库体积。
- ratio > 1 表示 Linkrs 更慢。高亮阈值与 Ladybug 服务端一致：相对偏差 ≥ 20%。
- skip 查询出现在表底，不进入几何平均。
- 文首固定环境块：CPU、affinity、内存、磁盘、双方 commit、线程、是否 AVX2、是否 drop_caches。

LSQB 额外报各 query 的 count 值是否相等（这是正确性门，不相等则整行作废）。

不接入 Ladybug 的 JWT 上报服务。对比是离线 markdown，检入 `docs/archive/perf/parity/`。若以后要 CI 回归，再做一个「仅 LSQB-sf0.1 + LDBC-sf10」的短门，阈值放 `threshold_registry`，与现有 `olap_e2e` 门分开。

---

## 9. 实施顺序

### 第 1 步：骨架与 LSQB-sf0.1（正确性优先）

- 落地 `benches/parity/` 目录、`serialize.py`、`runner.py`、`linkrs-parity-bench` 最小实现。
- 只支持 LSQB-sf0.1：自动下载、convert、COPY、q1–q9。
- 验收：9 个 count 与 Ladybug 同规模运行结果一致；导入可跳过（version.txt）。
- 这一步不谈快慢，只证明 COPY + MATCH 闭环。

### 第 2 步：LDBC-sf10 算子组

- 翻译 `serialize.cypher` → `schema/ldbc_snb.cypher`。
- header 改写（ID→vid，边 src/dst）。
- 跑 `queries/ldbc-sf100`（sf10 共用查询）。
- 建立 skip.txt；能过 expectedNumOutput 的进对比表。
- 与 Ladybug 在同一台机器跑 sf10，出第一份 `parity` markdown。

### 第 3 步：口径对齐与 LDBC-sf100

- compiling/executing 拆分接到 `query_stage_bench` 的阶段计时。
- warmup=1 / run=5 写死为常量，与 Ladybug 相同。
- 放大到 sf100。导入必须走 `begin_bulk_load`。
- 报告库体积、RSS、COPY 分表耗时。

### 第 4 步：ClickBench

- schema 映射 105 列；INT128 探针。
- quoted newline 处理策略落地（预处理或引擎修复，二选一写进报告）。
- 主套件 43 条 + `click/run.sh` 冷缓存脚本。

### 第 5 步：算法图

- 三份 CSV 投到 `person`/`knows`。
- 只对等 PageRank、WCC、加权最短路。
- k-core/SCC/Louvain 进 skip，开 issue 跟踪实现后再纳入。

### 第 6 步：自动化

- `scripts/ci` 增加可选 job：`PARITY_QUICK=1` 只跑 LSQB-sf0.1 + 一组 LDBC-sf10 filter 查询。
- 全量对比保持手动、独占机器，写入 `docs/archive/perf/parity/`。

每步独立可交付：上一步的 JSON 格式不变，下一步只加 dataset。

---

## 10. 计时与正确性细则

**Compiling vs executing**  
Ladybug 的 compiling 含绑定+优化。Linkrs `query_stage_bench` 已拆 parse / bind / plan+optimize / execute。对比时：

- `compiling_time` = parse + bind + plan+optimize
- `execution_time` = execute（含结果物化）

物化策略与 Ladybug 对齐：必须 drain 全部 chunk（`olap_e2e_bench` 的 `run_query` 已如此），禁止只取第一行。

**中位数 vs 去 max 平均**  
主套件对外对比用 5 次中位数；LSQB 严格跟 Ladybug：4 次里去掉 max 再平均（warmup + 3 trials，实现里 warmup 单独一次，再 3 次里去 max，与 `lsqb/benchmark_runner.py` 一致——注意 Ladybug 把 warmup 也放进 4 个样本再去 max）。实现时 **逐行照抄** 该文件的样本处理，避免口径漂。

**线程**  
两边都设为同一 `N = len(sched_getaffinity(0))`。Linkrs 若 session 无线程参数，用配置项 / `UPDATE CONFIGS` 对齐，并在报告写明实际 worker 数（可参考 `parallel_scale_bench`）。

**正确性**  
- 标量/小结果：精确匹配 Ladybug `----` 块。  
- 浮点（PageRank、WSHORTEST cost）：相对误差 1e-3 或绝对值对齐到 Ladybug 打印精度（其 benchmark 文件已给出打印宽度）。  
- COUNT：必须相等。  
- 无期望文件的 Click 独立脚本：与 Ladybug 同输入跑出的 3 个秒数对比即可，正确性靠主套件 `.benchmark` 的 COUNT。

---

## 11. 风险与非目标

**风险**

- LDBC CSV 体积大（sf100 数十 GB 级），本环境不一定放得下。第 1–2 步用 sf0.1 / sf10 在小机器完成设计验证；sf100 / Graph500-27 只在独占机器跑。
- Linkrs COPY 对 `|` 分隔、引号换行、DATE/TIMESTAMP 解析可能与 Ladybug 不一致。serialize 阶段用小文件 golden test（从 `copy_e2e.rs` 扩）锁住。
- 边 CSV 无显式 `src,dst` header 时 COPY 会失败（已有测试）。header 改写必须覆盖所有 LDBC / LSQB 边文件命名。
- INT128 / SERIAL 在 Click hits 上可能卡住整组。允许先导入子集列跑 q1–q10，其余 skip。
- 图算法数值对不齐时，先对齐迭代次数与阻尼，再比时间；对不齐就 skip，不调查询去凑。

**非目标**

- 不把这套替代现有 Criterion 微基准。微基准继续守回归门。
- 不实现 Ladybug 没有的 HTTP/gRPC 对等测试。
- 不修改 Ladybug 查询语义来迁就 Linkrs 优化器。
- 不在本方案里实现 k-core/SCC/Louvain。
- 不上报 Ladybug 的 JWT 服务。
- 不拉 git submodule（tantivy/simvec 等与本套件无关）。

---

## 12. 验收

1. `PARITY_QUICK=1`：LSQB-sf0.1 九条 COUNT 与 Ladybug 一致；LDBC-sf10 至少 filter + join 两组 expectedNumOutput 通过。
2. 同一台机器上产出一份 LDBC-sf10 对比 markdown，含 COPY 表、查询中位数、20% 高亮、skip 列表、环境块。
3. 文档说明如何用同一 `CSV_DIR` 先跑 Ladybug runner 再跑 `benches/parity/runner.py`。
4. sf100 / Click / 算法图在独占机器上可按第 9 节第 3–5 步追加，JSON schema 无需再改。

先打通 LSQB-sf0.1 的 COUNT 对齐，再放大规模。规模不是第一步。

