# AGENTS.md — graphdb-ben Workspace

This repository is a **graph database benchmarking workspace**. Its goal is to use the same set of public datasets to complete peer-to-peer benchmarking of three graph database engines — **Linkrs, Neug, and Ladybug (lbug)** — and to produce comparison reports that can be read side by side directly.

## Top-Level Structure

```
graphdb-ben/
├── AGENTS.md                 # This file
├── docs/                     # Analysis and planning documents
│   ├── ladybug-benchmarks.md             # Analysis of the LadybugDB benchmarks repository (three pipelines, data sources, timing methodology)
│   ├── linkrs-ladybug-parity-benchmark.md # Linkrs parity benchmark design plan (authoritative design document)
│   └── spec/                             # Specification documents (sync plan, git notes)
├── lbug-ben/                 # Ladybug official benchmark suite (vendored inline, see lbug-ben/VENDORED.md)
│   ├── benchmark_runner.py   # Main suite entry point (ldbc-sf100 / click / graph500-27 / soc-livejournal / datagen-sf10k)
│   ├── lsqb/                 # LSQB pipeline (data downloaded automatically from the public internet)
│   ├── click/                # ClickBench standalone script
│   └── serializer.py         # CSV → db.lbdb serialization
├── scripts/                  # Data generation/processing scripts (no large files committed)
│   └── kron/                 # Graph500 Kronecker generator (streaming, low memory)
└── data/                     # Local data directory (large files not committed to git, reusable)
```

## Benchmarking Goals

Perform a three-way parity reproduction of the three Ladybug pipelines in `docs/linkrs-ladybug-parity-benchmark.md`:

| Pipeline | Ladybug Entry Point | Dataset | Queries |
|----------|----------------------|---------|---------|
| Main suite (operator microbenchmarks) | `lbug-ben/benchmark_runner.py` + `lbug_benchmark` | ldbc-sf100, click, algorithm graphs | warmup=1, run=5, compiling/executing timed separately |
| LSQB | `lbug-ben/lsqb/benchmark_runner.py` (Python bindings) | LDBC LSQB projected-fk (downloaded automatically from the public internet) | q1–q9 multi-hop COUNT, warmup=1, run=3 averaged after dropping the max |
| ClickBench standalone script | `lbug-ben/click/benchmark.sh` | ClickHouse hits | drop_caches per query, 3 wall-clock runs |

Hard constraints for fair comparison (see Section 2 of the parity design document): the same CSV, the same query semantics, the same timing methodology, the same hardware, the embedded path, and COPY timing reported as a separate group. Queries whose semantics cannot be aligned go on a skip list; approximate queries are not used as substitutes.

## Data Preparation

Data is stored uniformly under `./data` for reuse by all three engines (zero-copy shared CSV; each engine's serialized artifacts are kept separate).

### Ready

| Directory | Size | Source/How to Obtain |
|-----------|------|----------------------|
| `data/social-network-sf{0.1,1}-projected-fk/` | 52MB / 562MB | `https://datasets.ldbcouncil.org/lsqb/social-network-sf{sf}-projected-fk.tar.zst` (proxy required) |
| `data/social_network-sf1-CsvComposite-StringDateFormatter/` | 1.1GB | Neug dataset: `https://neug.oss-cn-beijing.aliyuncs.com/datasets/ldbc-snb-sf1-lsqb.tar.gz` (**direct connection within China**; the original URL returned 403 because the bucket enforces the Beijing endpoint; includes dynamic/ + static/ + updateStream, standard LDBC SNB format) |
| `data/soc-livejournal/csv/` | 1.1GB, person 4.85M / knows 68.99M | Snap `soc-LiveJournal1.txt.gz`, already converted to person/knows |
| `data/soc-pokec/csv/` | ~1.2GB, person 1.63M / knows 30.6M | Snap soc-Pokec, already converted to person/knows |
| `data/graph500-27/csv/` | schema/copy.cypher only | Generated on site with `scripts/kron/build_and_generate.sh` (~40GB, do not generate locally) |

### Acquisition/Generation Conventions

1. **Publicly downloadable** (external network requires a proxy: `export http_proxy=http://localhost:7890 https_proxy=http://localhost:7890`; domestic sources such as Alibaba Cloud OSS connect directly):
   - LSQB at various scales (the `download_dataset` logic in `lsqb/benchmark_runner.py` can be reused)
   - Snap: `https://snap.stanford.edu/data/`
   - ClickBench: `https://datasets.clickhouse.com/hits_compatible/hits.csv.gz`
   - Neug: Alibaba Cloud OSS Beijing endpoint (see above)
2. **Locally generated**: Use `scripts/kron/build_and_generate.sh` for the Graph500 Kronecker graph (official graph500 v3.0.0 reference implementation, streaming output, ~400MB memory, full scale 27 takes about 25 minutes). The output is a raw RMAT edge list (including self-loops/duplicate edges); strict semantics require deduplication and self-loop removal.
3. **Algorithm graph format convention**: a `person` node table (single column `id`) + a `knows` edge table (two columns `src,dst`, no header), with `schema.cypher` / `copy.cypher` in each directory, aligned with `PROJECT_GRAPH('PK', ['person'], ['knows'])` in `lbug-ben/queries/<dataset>/algo/*.benchmark`.
4. **Not publicly obtainable**: ldbc-sf10/sf100 (generated by Datagen), pre-extracted click, datagen-sf10k depends on an internal server (`*_BENCHMARK_SERVER_URL`).

### Large File Rules

- Large files under `data/` **are not committed to git** (already covered by .gitignore; newly added large directories are likewise ignored).
- When syncing to other machines, **transfer only scripts + archives**, see `docs/spec/sync-plan.md`.

## Runtime Environment Notes

- Python dependencies: `lbug` (Ladybug Python bindings), `psutil`; the current environment has no `pip` command, use `python3 -m pip`.
- The package name in the two scripts under `lbug-ben/lsqb/` has been corrected to `import lbug as lb` (`ladybug` is the old name); `lsqb/results_reporter.py` (JWT reporting) has been deleted, and local runs always use `DRY_RUN=true`.
- The `data_base_dir` in `lsqb/benchmark_runner.py` is hardcoded to `/tmp/lsqb-datasets`; to reuse `./data`, change that line or create a symlink.
- Network-restricted machines (such as devs) cannot download from the public internet; data is synced via archives, see `docs/spec/sync-plan.md`.

## Next Steps (per Section 9 of the parity design document)

1. Skeleton + LSQB-sf0.1 COUNT alignment (correctness first)
2. LDBC-sf10 operator group → first comparison markdown
3. Methodology alignment + LDBC-sf100
4. ClickBench
5. Algorithm graphs (only PR/WCC/WSHORTEST have parity; skip k-core/SCC/Louvain)
6. Automation (PARITY_QUICK short gate)

Current progress: data preparation (LSQB sf0.1/sf1, Neug SF1, Snap dual datasets) is complete; the Graph500-27 generation script is ready, and the data is generated on site on the compilation server.
