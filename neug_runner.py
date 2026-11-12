"""Neug/Ladybug parity COUNT runner for LSQB projected-fk (design: docs/tests/benches/devs_lbug_neug_parity_design.md).

Parses the same `qN.benchmark` files as linkrs-parity-bench (single source of
truth for query semantics), loads the projected-fk CSVs, then runs each query
with warmup 1 + run 3 (drop-max average, LSQB runner convention).

Timing:
  * neug    -- no internal timer; wall-clock via perf_counter around full
               result materialization. AP queries are single-threaded
               (max_thread_num only caps TP slots) -- report accordingly.
  * ladybug -- QueryResult.get_execution_time() (internal), same as the LSQB
               runner.

Usage:
  python neug_runner.py --engine neug \
      --data /data/kkkqkx/graphdb-ben/data/social-network-sf0.1-projected-fk \
      --queries /data/kkkqkx/linkrs/repo/benches/parity/queries/lsqb \
      --out results/2026-11-12-neug-lsqb-sf0.1.json
"""
import argparse
import glob
import json
import os
import statistics
import sys
import time

DATA_DEFAULT = "/data/kkkqkx/graphdb-ben/data/social-network-sf0.1-projected-fk"

# Parity schema: q1-q9 only count vertices/edges, so node tables carry just
# the `id` key and rel tables are bare endpoint pairs (mirrors
# benches/parity/schema/lsqb.cypher; one rel table per endpoint pair).
NODES = ["Person", "Comment", "Post", "Forum"]
RELS = [
    ("KNOWS", "Person", "Person", "Person_knows_Person.csv"),
    ("HASCREATOR_COMMENT", "Comment", "Person", "Comment_hasCreator_Person.csv"),
    ("HASCREATOR_POST", "Post", "Person", "Post_hasCreator_Person.csv"),
    ("REPLYOF_COMMENT", "Comment", "Comment", "Comment_replyOf_Comment.csv"),
    ("REPLYOF_POST", "Comment", "Post", "Comment_replyOf_Post.csv"),
    ("CONTAINEROF", "Forum", "Post", "Forum_containerOf_Post.csv"),
]

# Reserved word in Linkrs only; Ladybug/Neug accept `Comment` directly.


def parse_benchmark(path):
    blocks = {}
    key = None
    with open(path) as f:
        for line in f:
            line = line.rstrip("\n")
            if line.startswith("----"):
                key = line[4:].strip()
                blocks[key] = []
            elif key is not None:
                blocks[key].append(line)
    return {
        "name": "\n".join(blocks.get("name", [])).strip(),
        "query": "\n".join(blocks.get("query", [])).strip(),
        "expected": "\n".join(blocks.get("expected", [])).strip(),
    }


def load_queries(queries_dir):
    out = []
    for path in sorted(glob.glob(os.path.join(queries_dir, "q*.benchmark"))):
        q = parse_benchmark(path)
        q["file"] = os.path.basename(path)
        out.append(q)
    return out


def ddl_ladybug(data):
    stmts = [f"CREATE NODE TABLE {n} (id INT64, PRIMARY KEY(id))" for n in NODES]
    stmts += [
        f"CREATE REL TABLE {name} (FROM {src} TO {dst})" for name, src, dst, _ in RELS
    ]
    stmts += [f"COPY {n} FROM '{os.path.join(data, n + '.csv')}' (HEADER=true, DELIM='|')" for n in NODES]
    stmts += [
        f"COPY {name} FROM '{os.path.join(data, csv)}' (HEADER=true, DELIM='|')"
        for name, _, _, csv in RELS
    ]
    return stmts


def ddl_neug(data):
    # Neug dialect (validated by packages/smoke_bench.py): DELIMITER/HEADER
    # kwargs, uppercase identifiers accepted as-is.
    stmts = [f"CREATE NODE TABLE {n} (id INT64, PRIMARY KEY(id))" for n in NODES]
    stmts += [
        f"CREATE REL TABLE {name} (FROM {src} TO {dst})" for name, src, dst, _ in RELS
    ]
    stmts += [
        f"COPY {n} FROM '{os.path.join(data, n + '.csv')}' (DELIMITER='|', HEADER=true)"
        for n in NODES
    ]
    stmts += [
        f"COPY {name} FROM '{os.path.join(data, csv)}' (DELIMITER='|', HEADER=true)"
        for name, _, _, csv in RELS
    ]
    return stmts


def materialize_ladybug(res):
    rows = []
    while res.has_next():
        rows.append(res.get_next())
    return rows


def run_engine(engine, data, queries, db_path, num_threads):
    result = {"engine": engine, "database": db_path, "queries": {}}
    if engine == "neug":
        import neug

        db = neug.Database(db_path, max_thread_num=num_threads)
        conn = db.connect()
        stmts = ddl_neug(data)

        def execute(q):
            t0 = time.perf_counter()
            res = conn.execute(q)
            rows = [r for r in res]  # full materialization
            return rows, (time.perf_counter() - t0) * 1000.0
    elif engine == "ladybug":
        import ladybug as lb

        db = lb.Database(db_path)
        conn = lb.Connection(db, num_threads=num_threads)
        stmts = ddl_ladybug(data)

        def execute(q):
            res = conn.execute(q)
            rows = materialize_ladybug(res)
            return rows, float(res.get_execution_time())  # ms
    else:
        raise ValueError(f"unknown engine {engine}")

    load_ms = []
    for stmt in stmts:
        t0 = time.perf_counter()
        conn.execute(stmt)
        load_ms.append((time.perf_counter() - t0) * 1000.0)
    result["load_statements_ms"] = load_ms
    result["load_total_ms"] = sum(load_ms)

    for q in queries:
        entry = {"file": q["file"], "name": q["name"], "query": q["query"]}
        # `Comment_` is a Linkrs-only reserved-word rewrite; Ladybug/Neug
        # accept `Comment` directly.
        query = q["query"].replace("Comment_", "Comment")
        try:
            rows, _ = execute(query)  # warmup (1 run)
            runs = []
            for _ in range(3):
                rows, ms = execute(query)
                runs.append(ms)
            worst = max(runs)
            runs.remove(worst)  # drop max, average the rest
            entry["status"] = "ok"
            entry["runs_ms"] = runs + [worst]
            entry["avg_ms"] = sum(runs) / len(runs)
            entry["value"] = rows[0][0] if rows else None
            entry["expected"] = q["expected"]
            entry["match"] = str(entry["value"]) == q["expected"]
        except Exception as e:  # noqa: BLE001 - record and continue
            entry["status"] = "error"
            entry["error"] = repr(e)
        result["queries"][q["file"]] = entry
        print(
            f"[{engine}] {q['file']}: {entry.get('value')} "
            f"match={entry.get('match')} avg={entry.get('avg_ms', 'NA'):.3f}ms"
            if entry["status"] == "ok"
            else f"[{engine}] {q['file']}: ERROR {entry.get('error')}",
            flush=True,
        )
    conn.close()
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", choices=["neug", "ladybug"], required=True)
    ap.add_argument("--data", default=DATA_DEFAULT)
    ap.add_argument("--queries", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--db", default=None, help="database file/dir path")
    args = ap.parse_args()

    db_path = args.db or os.path.join(
        "/tmp", f"parity-{args.engine}-{int(time.time())}"
    )
    queries = load_queries(args.queries)
    if not queries:
        sys.exit(f"no q*.benchmark files under {args.queries}")

    result = run_engine(args.engine, args.data, queries, db_path, args.threads)
    result["threads"] = args.threads
    result["date"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    result["timing_basis"] = (
        "wall-clock full materialization" if args.engine == "neug" else "get_execution_time (internal)"
    )

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(result, f, indent=2)
    print(f"results -> {args.out}", flush=True)


if __name__ == "__main__":
    main()
