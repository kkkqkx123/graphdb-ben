#!/bin/bash
# Graph500 Kronecker 边表生成器（与官方 graph500 v3.0.0 规范一致）
# 用法: ./build_and_generate.sh [SCALE] [EDGEFACTOR] [SEED] [OUTFILE]
#   默认: SCALE=27 EDGEFACTOR=16 SEED=42 → 约 21.5 亿条边, 原始 CSV 约 39GB
# 说明: kron_stream 按块流式输出, 内存占用约 130MB+256MB, 与 scale 无关;
#       输出为原始 RMAT 边表(含自环/重复边), 严格 Graph500 语义需自行去重去自环。
set -e
cd "$(dirname "$0")"

SCALE=${1:-27}
EDGEFACTOR=${2:-16}
SEED=${3:-42}
OUT=${4:-knows.csv}

gcc -O3 -o kron_stream kron_stream.c graph_generator.c splittable_mrg.c utils.c
./kron_stream "$SCALE" "$EDGEFACTOR" "$SEED" "$OUT"

# 生成节点表: 0 .. 2^SCALE - 1
seq 0 $(( (1 << SCALE) - 1 )) > "${OUT%/*}/person.csv" 2>/dev/null || seq 0 $(( (1 << SCALE) - 1 )) > person.csv
echo "done: knows.csv + person.csv"
