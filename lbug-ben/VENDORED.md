# VENDORED — lbug-ben

本目录是内联（vendored）的 LadybugDB 官方基准套件，不再是独立 git 仓库。

## 来源

- 上游仓库：`https://github.com/ladybugdb/benchmarks`
- 内联时上游 commit：`42dd2882d319c339d72b1f10f25e237eafaa1a8f`（2026-08-08，"serializer: create SERIALIZED_DIR parents with os.makedirs (#4)"）
- 内联日期：2026-11-11

## 与上游的差异（本地改动，不入上游）

1. `lsqb/benchmark_runner.py`、`lsqb/serializer.py`：`import ladybug as lb` → 导入垫片（优先 `import lbug`，回退 `import ladybug`）。PyPI wheel（ladybug==0.22.3）顶层模块实测为 `ladybug`，`import lbug` 失败；垫片保证 wheel 路径可用。
2. 删除 `lsqb/results_reporter.py`：JWT 上报服务相关，本项目不使用（根目录 `benchmark_runner.py` 内的上报函数保留，由 `DRY_RUN=true` 规避）
3. 删除 `lsqb/__pycache__/`、内联时丢弃子仓库 `.git`

## 更新上游的方法

```bash
# 本地任一目录克隆上游
git clone --depth 50 https://github.com/ladybugdb/benchmarks /tmp/upstream-benchmarks
diff -r /tmp/upstream-benchmarks lbug-ben/   # 手工对照
```

按需 cherry-pick 上游改动到本目录，并更新本文件的 commit 记录。不要用 `git pull`——本目录已并入工作区主仓库。
