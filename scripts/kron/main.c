#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include "make_graph.h"
#include "graph_generator.h"

int main(int argc, char** argv) {
    if (argc < 4) {
        fprintf(stderr, "usage: %s SCALE EDGEFACTOR SEED OUT\n", argv[0]);
        return 1;
    }
    int scale = atoi(argv[1]);
    int64_t edgefactor = atoll(argv[2]);
    uint64_t seed = strtoull(argv[3], NULL, 10);
    int64_t nedges;
    packed_edge* edges;
    make_graph(scale, edgefactor * ((int64_t)1 << scale), seed, seed, &nedges, &edges);
    FILE* out = fopen(argv[4], "w");
    if (!out) { perror("fopen"); return 1; }
    for (int64_t i = 0; i < nedges; ++i) {
        fprintf(out, "%" PRId64 " %" PRId64 "\n",
                get_v0_from_edge(&edges[i]), get_v1_from_edge(&edges[i]));
    }
    fclose(out);
    free(edges);
    fprintf(stderr, "wrote %" PRId64 " edges to %s\n", nedges, argv[4]);
    return 0;
}
