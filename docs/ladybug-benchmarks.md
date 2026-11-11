# LadybugDB Benchmarks 分析

仓库：`https://github.com/ladybugdb/benchmarks`  
分析 commit：`42dd2882d319c339d72b1f10f25e237eafaa1a8f`  
本地路径：`当前工作区/benchmarks`

本仓库是 LadybugDB（图数据库，前身 Kuzu）的性能基准套件。测试目标是引擎回归：固定数据集、固定查询、固定 warmup/run 次数，把编译时间、执行时间、结果行数和库体积上报，并与 `origin/master` 对比。

---

## 1. 总体架构

数据不在查询阶段现场扫描 CSV。先把源数据 COPY 进 Ladybug 原生库 `db.lbdb`，再对这份库反复跑查询。序列化结果按数据库版本缓存；`CMakeLists.txt` 中 `project(Lbug VERSION …)` 与 `SERIALIZED_DIR/<dataset>-serialized/version.txt` 一致时跳过 COPY。

运行时资源按容器限额自适应：

- CPU：优先 `os.sched_getaffinity(0)`，否则 `multiprocessing.cpu_count()`
- 内存：优先 cgroup v2 `memory.max`，其次 cgroup v1，最后 `psutil.virtual_memory().total`
- Buffer manager：可用内存的 90%（`--bm-size`）

```
源 CSV / 官方归档
        |
 serializer（CREATE TABLE + COPY，按库版本缓存）
        |
     db.lbdb
        |
 查询执行（warmup + 多次 run）
        |
 解析 compiling_time / execution_time / 结果行数
        |
 POST Benchmark Server，相对 master 对比（阈值 20%）
```

仓库内有三条相对独立的流水线：

| 流水线 | 入口 | 执行器 | 主要测什么 |
|--------|------|--------|------------|
| 主套件（算子微基准） | `benchmark_runner.py` | C++ `lbug_benchmark` | 过滤、Join、聚合、递归、最短路、图算法 |
| LSQB | `lsqb/benchmark_runner.py` | Python `ladybug` API | LDBC 社交图 9 条多跳 COUNT |
| ClickBench 独立脚本 | `click/benchmark.sh` | Python `lbug` + wall-clock | ClickHouse ClickBench 的 Cypher 移植 |

---

## 2. 主套件如何完成基准测试

入口：`benchmark_runner.py`。

必需环境变量：`CSV_DIR`、`SERIALIZED_DIR`；非 dry-run 时还要 `JWT_TOKEN` 和对应数据集的 `*_BENCHMARK_SERVER_URL`。

```bash
export CSV_DIR=/path/to/csv
export SERIALIZED_DIR=/path/to/serialized
python3 benchmark_runner.py --dataset ldbc-sf100 --thread <N>
```

### 2.1 序列化（`serializer.py` + `serialize.cypher`）

1. 比较库版本与已有 `version.txt`。
2. 不匹配则重建目录，逐条执行 Cypher。
3. 数据集自带 `schema.cypher` / `copy.cypher` 时用数据集脚本，并把相对路径改成绝对路径；否则用仓库根目录的 `serialize.cypher`（LDBC SNB 默认 schema）。
4. 每条语句单独拉起 `../build/release/tools/shell/lbug` 进程，避免内存泄漏污染后续计时。
5. `COPY` 的 stdout 写入 `/tmp/benchmark_copy_logs`，正则抽出：

```
Time: <compiling>ms (compiling), <executing>ms (executing)
```

作为 `query_group = copy` 的结果上报。

可选 `--single-thread`：先执行 `CALL THREADS=1`，让 COPY 结果更可复现。

### 2.2 查询文件（`queries/<dataset>/<group>/*.benchmark`）

```
-NAME q29
-QUERY MATCH (a:Person)-[:knows]->(b:Person) RETURN MIN(a.birthday), MIN(b.birthday)
---- 1
1980-02-01|1980-02-01
```

字段：

- `-NAME`：查询名
- `-QUERY`：Cypher（可多行）
- `---- N`：期望输出行数，用于正确性校验
- 随后是期望结果
- 可选 `-PRERUN` / `-POSTRUN`：例如先 `LOAD EXTENSION algo` 再建投影图，跑完 `DROP_PROJECTED_GRAPH`

`BenchmarkGroup` 按子目录分组加载。LDBC-sf100 的分组对应引擎算子，而不是业务场景：

| 分组 | 覆盖点 |
|------|--------|
| `scan_after_filter` / `filter` | 过滤、zonemap |
| `fixed_size_expr_evaluator` / `var_size_expr_evaluator` | 表达式求值 |
| `fixed_size_seq_scan` / `var_size_seq_scan` | 顺序扫描 |
| `join` / `multi-rel` | Join、多关系扫描 |
| `aggregation` / `order_by` / `limit` | 聚合、排序、limit 下推 |
| `recursive_join` / `shortest_path_ldbc100` | 递归、最短路 |
| `ldbc_snb_ic` / `ldbc_snb_is` | LDBC Interactive Complex / Short |

图数据集只有 `algo/`：PageRank、WCC、SCC、k-core、Louvain、加权最短路。

### 2.3 执行

调用同仓库编译产物：

```
../build/release/tools/benchmark/lbug_benchmark
  --dataset=<serialized>/db.lbdb
  --benchmark=queries/<dataset>/<group>
  --warmup=1 --run=5 --profile
  --bm-size=<90% 内存 MiB>
  --thread=<CPU 核数>
  --out=/tmp/benchmark_logs/<group>
```

配置常量：`num_warmup = 1`，`num_run = 5`。日志解析 `Status`、`Compiling time`、`Execution time`，并附带 `*_profile.txt`。

### 2.4 上报与对比

`get_run_info()` 收集 commit hash（优先 `GITHUB_SHA`）、作者、message、时间戳、`--note`、dataset。  
`get_query_info()` 合并 COPY 日志和查询日志。  
`upload_benchmark_result()` POST JSON（含序列化库总字节数）。  
`get_compare_result()` GET `/compare?master_commit_hash=…&compare_highlight_threshold=20`，写入 `compare_result.md`。

`DRY_RUN=true` 时只跑不上报。任一组 `[error]` 或非零退出码则进程以失败退出。

---

## 3. LSQB 如何完成基准测试

入口：`lsqb/benchmark_runner.py`。走 Python 绑定 `import ladybug as lb`。

```bash
export SERIALIZED_DIR=/path/to/serialized
export SCALE_FACTOR=100          # 0.1 / 0.3 / 1 / 3 / 10 / 30 / 100
export NUM_THREADS=<N>           # 默认 CPU 核数
export TIMEOUT=<ms>              # 可选
python3 lsqb/benchmark_runner.py
```

流程：

1. 从 `https://datasets.ldbcouncil.org/lsqb/social-network-sf<sf>-projected-fk.tar.zst` 下载，缓存到 `/tmp/lsqb-datasets`。已有 `Person_knows_Person.csv` 则跳过。
2. `serializer.convert()`：单向 `knows` 扩成双向；Comment/Post 合并成 Message 视图 CSV；写 `.converted` 标记。
3. 按 `schema.cypher` 建 11 类节点 + 25 类边，再 `COPY … (HEADER=True, DELIM='|')`。
4. 对 `queries/q1.cypher` … `q9.cypher`：1 次 warmup + 3 次正式。去掉最大执行/编译时间后取平均；RAM 用 `psutil` 差值，去掉 0 后再平均。
5. 结果追加 `/tmp/benchmark_result/results.csv`。`results_reporter.py` 读 CSV + `lsqb.log`，POST 到 `LSQB_BENCHMARK_SERVER_URL`。

查询形态是多跳 `MATCH … RETURN count(*)`，例如 q1 是 Country→City→Person→Forum→Post→Comment→Tag→TagClass 的 8 跳路径计数。

---

## 4. ClickBench 独立脚本如何完成基准测试

`click/benchmark.sh` 是面向 ClickHouse ClickBench 对比的端到端脚本，与主套件的 `queries/click/` 共用同一批查询语义。

```
venv + pip install lbug
wget https://datasets.clickhouse.com/hits_compatible/hits.csv.gz
gzip -d；python load.py          # CREATE hits + COPY PARALLEL=false
./run.sh | tee log.txt           # 每条查询前 drop_caches，跑 3 次
整理成 benchmarks.json
```

`load.py` 必须单线程 COPY：官方 CSV 含引号换行。`query.py` 用 `timeit.default_timer()` 记 wall-clock，打开 `mydb-<DB_Version>` 只读库。`run.sh` 每条查询前 `sync` + `sysctl vm.drop_caches=3`，测冷缓存。

主套件里另有 43 条 `queries/click/click/q*.benchmark`，走 `lbug_benchmark`（warmup=1, run=5），用于 CI 回归。

---

## 5. 计时口径

| 流水线 | 预热 | 正式次数 | 汇总方式 | 时间来源 |
|--------|------|----------|----------|----------|
| 主套件 | 1 | 5 | 每次都上报 | 引擎 compiling / executing |
| LSQB | 1 | 3 | 去掉 max 后平均 | `QueryResult.get_execution_time()` |
| Click 独立脚本 | 无（每次 drop cache） | 3 | 三次原始秒数 | Python `timeit` wall-clock |

主套件还校验 `expectedNumOutput`；图算法查询带固定 Top-N 期望值。

---

## 6. 数据源分析

主套件 **不负责下载** 除 LSQB 以外的数据。`CSV_DIR` 下的目录必须预先就位。各数据集对应的上报地址由不同环境变量给出。

### 6.1 一览

| 逻辑名 | 物理路径 | 来源 | 形态 | 谁下载 | 上报 URL 环境变量 |
|--------|----------|------|------|--------|-------------------|
| `ldbc-sf10` | `$CSV_DIR/ldbc-10/csv` | LDBC SNB Datagen SF10 | 多表 CSV，`\|` + header | 预置 | `BENCHMARK_SERVER_URL` |
| `ldbc-sf100` | `$CSV_DIR/ldbc-100/csv` | LDBC SNB Datagen SF100 | 同上 | 预置 | `BENCHMARK_SERVER_URL` |
| `click` | `$CSV_DIR/click/hits` 或脚本现下 | ClickHouse ClickBench hits | 单表宽 CSV | 独立脚本会 wget | `CLICK_BENCHMARK_SERVER_URL` |
| `graph500-27` | `$CSV_DIR/graph500-27/csv` | Graph500 Kronecker scale 27 | 投影为 person/knows | 预置 | `GRAPH500_BENCHMARK_SERVER_URL` |
| `soc-livejournal` | `$CSV_DIR/soc-livejournal/csv` | SNAP LiveJournal | 投影为 person/knows | 预置 | `SOC_LIVEJOURNAL_BENCHMARK_SERVER_URL` |
| `datagen-sf10k` | `$CSV_DIR/datagen-sf10k/csv` | LDBC SNB Datagen SF10000 | 带权图，person/knows | 预置 | `DATAGEN_SF10K_BENCHMARK_SERVER_URL` |
| `lsqb-sf*` | `/tmp/lsqb-datasets/social-network-sf*-projected-fk` | LDBC LSQB projected-fk | FK 风格多表 CSV | runner 自动下载 | `LSQB_BENCHMARK_SERVER_URL` |

### 6.2 LDBC SNB（`ldbc-sf10` / `ldbc-sf100`）

Linked Data Benchmark Council 的 Social Network Benchmark，用官方 Datagen 生成模拟社交网络。

默认 schema 来自仓库根目录 `serialize.cypher`（数据集没有自带 `schema.cypher` 时使用）：

**节点（8）**

| 表 | 关键属性 | CSV |
|----|----------|-----|
| Person | ID, firstName, lastName, gender, birthday, creationDate, locationIP, browserUsed | `person_0_0.csv` |
| Forum | ID, title, creationDate | `forum_0_0.csv` |
| Post | ID, imageFile, content, length, language, … | `post_0_0.csv` |
| Comment | ID, content, length, … | `comment_0_0.csv` |
| Tag / Tagclass | ID, name, url | `tag_0_0.csv` / `tagclass_0_0.csv` |
| Place | ID, name, url, type | `place_0_0.csv` |
| Organisation | ID, type, name, url | `organisation_0_0.csv` |

**边（约 22）**：`knows`、`likes_post` / `likes_comment`、`hasMember`、`hasInterest`、`studyAt` / `workAt`、`replyOf_*`、`containerOf`、各类 `hasTag` / `hasCreator` / `isLocatedIn` / `isPartOf`。CSV 命名 `src_rel_dst_0_0.csv`，分隔符 `|`，`HEADER=true`。

用途：主套件默认 `--dataset ldbc-sf100`，54 条 `.benchmark`，覆盖扫描、过滤、表达式、Join、聚合、递归与 LDBC Interactive 查询。sf10 与 sf100 共用同一套查询目录约定，规模差一个数量级，用来看缓存与并行是否线性。

数据需自行（或 CI）用 LDBC Datagen 生成后放到 `CSV_DIR`。仓库内没有下载逻辑。

### 6.3 LSQB projected-fk

官方归档：

```
https://datasets.ldbcouncil.org/lsqb/social-network-sf{0.1|0.3|1|3|10|30|100}-projected-fk.tar.zst
```

这是 LDBC 为 LSQB 预投影的 FK 风格社交图：每张表一张 CSV，边表用两端 ID 表示，分隔符 `|`。

**节点（11）**：Company、University、Continent、Country、City、Tag、TagClass、Forum、Comment、Post、Person。  
**边（25）**：命名即语义，如 `Person_knows_Person.csv`、`Forum_hasMember_Person.csv`。

加载前 `lsqb/serializer.py` 会本地派生：

- `Person_knows_Person_bidirectional.csv`：原边 + 反向边
- Message 视图：Comment/Post 及相关 hasCreator / hasTag / isLocatedIn / replyOf / likes 拼接
- `Forum_containerOf_Message.csv` ← `Forum_containerOf_Post.csv`

派生文件写在下载目录，并用 `.converted` 避免重复。查询 q1–q9 只做多跳 COUNT，测优化器对长路径、传递闭包式 Join 的处理。

### 6.4 ClickBench hits

来源：[ClickHouse/ClickBench](https://github.com/ClickHouse/ClickBench)，数据文件：

```
https://datasets.clickhouse.com/hits_compatible/hits.csv.gz
```

Yandex.Metrica 风格的 Web 分析事实表，约 **1 亿行**（q1 期望 `COUNT(*) = 99997497`）。单节点表 `hits`，`ID SERIAL` 主键，约 105 列：时间（EventTime/EventDate）、用户（UserID INT128）、URL/Referer、广告引擎、分辨率、UTM、耗时等。

独立脚本下载 gzip CSV；主套件期望 `$CSV_DIR/click/hits` 已解压到位。COPY 必须 `PARALLEL=false`，因为官方 CSV 含引号内换行。

43 条查询从 ClickBench SQL 改写成 Cypher：COUNT/SUM/AVG、DISTINCT、正则 `=~`、`date_part`、`REGEXP_REPLACE`、宽 `SUM(col+i)` 扫描。测的是列存扫描、过滤、聚合，几乎没有图遍历。

### 6.5 Graph500-27

[Graph500](https://graph500.org/) Kronecker 生成图，scale 27（顶点规模 2^27）。仓库把它投影成 `person` + `knows`，供 `algo` 扩展使用：

```
LOAD EXTENSION libalgo.lbug_extension;
CALL PROJECT_GRAPH('PK', ['person'], ['knows']);
CALL page_rank('PK') / weakly_connected_components('PK') / …
```

WCC 最大连通分量期望 **63,039,352**，与 scale 27 的巨型分量一致。查询：PageRank、WCC、SCC、SCC-KO、k-core。数据预置在 `$CSV_DIR/graph500-27/csv`。

### 6.6 SNAP soc-LiveJournal

斯坦福 SNAP 的 LiveJournal 社交网络（`soc-LiveJournal1`）。同样投影为 `person` / `knows`。WCC 最大分量期望 **4,843,953**，与公开统计（约 4.8M 节点）吻合。

查询比 Graph500 多一项 **Louvain** 社区发现。数据预置在 `$CSV_DIR/soc-livejournal/csv`。

### 6.7 LDBC Datagen SF10000（`datagen-sf10k`）

超大规模 LDBC 社交图（scale factor 10000），同样压成算法图。与 Graph500/LiveJournal 的差别：边带 **weight**，用于加权最短路：

```
MATCH (a{id:6})-[e* ALL WSHORTEST(weight)]->(b)
RETURN cost(e) AS cost ORDER BY cost DESC LIMIT 10
```

其余仍是 k-core / PageRank / SCC / WCC。数据预置在 `$CSV_DIR/datagen-sf10k/csv`。

### 6.8 数据在流水线中的角色

```
                    ┌─ LDBC SNB sf10/sf100 CSV ──► 算子微基准（54 queries）
预置 CSV_DIR ───────┼─ Click hits CSV ───────────► 列存扫描/聚合（43 queries）
                    ├─ Graph500-27 CSV ──────────► GDS：PR/WCC/SCC/k-core
                    ├─ soc-LiveJournal CSV ──────► GDS + Louvain
                    └─ datagen-sf10k CSV ────────► GDS + 加权最短路

自动下载 ──────────── LSQB projected-fk tar.zst ─► 9 条多跳 COUNT
独立脚本 wget ─────── ClickBench hits.csv.gz ────► drop_caches wall-clock
```

三类数据对应三种压力：

1. **多表属性图（LDBC SNB / LSQB）**：schema 复杂、边类型多，压 Cypher 优化器与混合负载。
2. **单表宽列（ClickBench hits）**：近 1 亿行、百余列，压存储扫描与向量化聚合。
3. **单关系大图（Graph500 / LiveJournal / datagen-sf10k）**：点边规模大、属性少，压 `algo` 扩展的迭代图算法。

序列化产物统一为 `db.lbdb` + `version.txt`。库版本一变，对应数据集整库重 COPY；版本不变则直接复用，避免 CI 每次重导入。

