# devs 服务器同步方案

**目标机器**: `ssh devs`（不可访问外网）
**目标路径**: `/data/kkkqkx/graphdb-ben`（与本仓库同名路径结构）

## 1. 原则

1. **数据不进 git**。devs 上通过**压缩包传输**获得数据文件；git 只跟踪代码、脚本、schema/copy.cypher 和文档。
2. dev 侧生成数据依赖外网的部分（下载、Kronecker 生成）**在本地完成后打包**，或只传脚本在 devs 上用本地 CPU 生成（生成不依赖外网）。
3. 压缩包传输后必须校验（大小 + 行数抽查），并记录清单，避免三个引擎因数据版本不一致导致结果不可比。

## 2. 目录布局（devs 上）

```
/data/kkkqkx/graphdb-ben/
├── AGENTS.md
├── docs/
├── lbug-ben/                     # git 同步（已内联为普通目录，见 lbug-ben/VENDORED.md）
├── scripts/                      # git 同步
├── data/                         # 仅压缩包解压，不进 git
│   ├── social-network-sf0.1-projected-fk/
│   ├── social-network-sf1-projected-fk/
│   ├── social_network-sf1-CsvComposite-StringDateFormatter/
│   ├── soc-livejournal/csv/
│   ├── soc-pokec/csv/
│   ├── snap/                     # 原始 Snap 归档（可选，供重新转换）
│   ├── graph500-27/csv/          # 在 devs 上用 scripts/kron 现场生成（无需传输）
│   └── ldbc-10/csv/              # LDBC Datagen 生成后传输
└── packages/                     # 传输用压缩包缓存（解压后可删）
```

## 3. 同步内容分类

| 类别 | 内容 | 同步方式 |
|------|------|----------|
| 代码/文档 | AGENTS.md、docs/、lbug-ben/、scripts/ | git（见 git 说明）或压缩包 |
| 小数据 | LSQB sf0.1（52MB）、schema/copy.cypher | tar 包直接传 |
| 中数据 | LSQB sf1（562MB）、Neug SF1（1.1GB）、soc-pokec（~1.2GB） | tar.zst 压缩后传 |
| 大数据 | soc-livejournal（1.1GB 已转换 / 原始 260MB gz） | 优先传原始 gz + 转换脚本，在 devs 解压转换 |
| 特大数据 | graph500-27（~40GB） | **不传**，在 devs 上运行 `scripts/kron/build_and_generate.sh` 现场生成 |
| LDBC sf10/sf100 | 本地 Datagen 生成 | 生成后 tar.zst 传输（sf100 数十 GB，确认磁盘后执行） |

优先传**原始归档 + 脚本**而非展开后的 CSV：体积小、可校验、可复现。已转换的 person/knows CSV 由 `scripts/` 里的转换命令在 devs 重做（转换逻辑写入 sync 清单附带的脚本）。

## 4. 传输流程

### 4.1 打包（本地，需外网/代理的步骤先完成）

```bash
cd /home/kkkqkx/code/graphdb-ben
mkdir -p /tmp/sync-pkgs

# 小数据：LSQB sf0.1
tar --zstd -cf /tmp/sync-pkgs/lsqb-sf0.1.tar.zst -C data social-network-sf0.1-projected-fk

# 中数据示例：LSQB sf1
tar --zstd -cf /tmp/sync-pkgs/lsqb-sf1.tar.zst -C data social-network-sf1-projected-fk

# 原始归档直传（Snap / Neug / ClickBench 本身就是压缩包）
cp data/snap/*.gz /tmp/sync-pkgs/
cp data/social_network-sf1-CsvComposite-StringDateFormatter.tar.gz /tmp/sync-pkgs/   # 保留原始包时

# 生成校验清单
( cd /tmp/sync-pkgs && sha256sum * > SHA256SUMS )
```

### 4.2 传输

```bash
scp /tmp/sync-pkgs/* devs:/data/kkkqkx/graphdb-ben/packages/
```

单包超过 ~2GB 时改用 `rsync --partial --append-verify`（可断点续传）：

```bash
rsync -avP --append-verify /tmp/sync-pkgs/ devs:/data/kkkqkx/graphdb-ben/packages/
```

### 4.3 解压与校验（devs 上）

```bash
cd /data/kkkqkx/graphdb-ben/packages
sha256sum -c SHA256SUMS                     # 完整性
tar --zstd -xf lsqb-sf0.1.tar.zst -C ../data/
gzip -dc snap/soc-LiveJournal1.txt.gz | tail -n +5 | wc -l   # 应为 68993773
```

各数据集的抽查基线（wc -l）：

| 文件 | 期望行数 |
|------|----------|
| soc-livejournal knows.csv | 68,993,773 |
| soc-livejournal person.csv | 4,847,572 |
| soc-pokec knows.csv | 30,622,563 |
| soc-pokec person.csv | 1,632,803 |
| graph500-27 knows.csv（生成后） | 2,147,483,648 |
| graph500-27 person.csv（生成后） | 134,217,728 |

### 4.4 graph500-27 在 devs 上生成

```bash
cd /data/kkkqkx/graphdb-ben/scripts/kron
./build_and_generate.sh 27 16 42 ../../data/graph500-27/csv/knows.csv
```

内存约 400MB，无需外网；生成约 25 分钟。CSV 头两行与 SEED 绑定，可在本地对 scale 3 先做一次对拍确认工具链一致。

## 5. 反向同步（结果回传）

基准结果（JSON / markdown / copy logs）体积小，直接：

```bash
rsync -avP devs:/data/kkkqkx/graphdb-ben/results/ ./results/
```

结果进 git（结果文件较小且有追溯价值），或作为对比报告附在 `docs/archive/perf/` 下。

## 6. 已知限制

- devs 无外网：任何 `wget`/`curl`/pip 安装步骤都要在本地完成后随包传输（包括 Python wheel：`pip download lbug psutil -d wheels/` 后传输离线安装）。
- 传输通道是 ssh，大批量数据安排在非高峰时段；断点用 rsync。
- Neug 原始 URL 的 403 是 bucket 强制 `oss-cn-beijing` endpoint 所致，devs 上若重新下载同样要换 endpoint（但 devs 本就无外网，直接传包）。
