# Git 说明

本工作区是**单一 git 仓库**。Ladybug 官方基准套件已内联为普通目录 `lbug-ben/`（不再是子仓库/嵌套仓库），来源与上游 commit 记录在 `lbug-ben/VENDORED.md`。

## 1. 跟踪范围

| 跟踪 | 不跟踪（.gitignore） |
|------|----------------------|
| `AGENTS.md`、`docs/`（含 `docs/spec/`） | `data/` 下所有大数据文件（CSV/gz/tar/zst） |
| `lbug-ben/` 全部代码与查询文件（.py/.cypher/.sh/.md，含 `VENDORED.md`） | `data/**` 的数据集目录（schema/copy.cypher 白名单例外） |
| `scripts/` 全部（含 kron 生成器源码） | `__pycache__/`、序列化产物、benchmark 日志、bundle |

关键规则：**数据文件一律不进 git**，仓库只保留获取/生成脚本与 schema。任何新数据集，提交时附上：下载 URL（或生成命令）、校验行数、目录布局说明（写入 AGENTS.md 或 sync-plan.md）。

## 2. .gitignore 约定

```
data/**
!data/**/
!data/**/schema.cypher
!data/**/copy.cypher
!data/**/source.md
__pycache__/
*.lbdb
results/
packages/
*.bundle
```

（`data/` 整体忽略、cypher 白名单例外，已验证生效。）

## 3. 提交规范

- Conventional Commits（`feat:` / `fix:` / `docs:` / `chore:` / `data:`（数据脚本类））。
- 修改 `lbug-ben/` 内 vendored 代码时，单独提交并在 message 中注明上游 commit（当前 `42dd288`），便于日后对照上游（对照方法见 `lbug-ben/VENDORED.md`）。
- 不要在 `lbug-ben/` 里做与基准无关的清理，保持与上游可对照。

## 4. 同步到 devs 的 git 流程

devs 不可访问外网，用 **git bundle** 离线同步（配合 `docs/spec/sync-plan.md` 的压缩包数据）：

```bash
# 本地：打 bundle（增量：git bundle create incr.bundle <last-sha>..HEAD）
git bundle create graphdb-ben.bundle --all
scp graphdb-ben.bundle devs:/data/kkkqkx/graphdb-ben/packages/

# devs：首次
git clone graphdb-ben.bundle /data/kkkqkx/graphdb-ben
# devs：后续更新
cd /data/kkkqkx/graphdb-ben && git fetch ../packages/graphdb-ben.bundle 'refs/heads/*:refs/remotes/bundle/*' && git merge bundle/main
```

每次 bundle 附 SHA256，与数据包同一份 `SHA256SUMS` 管理。

## 5. 数据集版本化的替代方案

数据不进 git，但需要**可追溯**：

1. 每个数据集在其目录内留一份 `source.md`：URL、下载/生成命令、SHA256（或行数基线）、生成时间。
2. Neug/Snap/ClickBench 等上游重新发布时，先更新 `source.md` 再重跑三引擎，避免新旧数据混比。
3. `graph500-27` 由 SEED 决定内容：固定 `SEED=42`（见 `scripts/kron/build_and_generate.sh`），任何机器生成都逐字节一致，天然可复现；若换 SEED 必须同步更新文档。
