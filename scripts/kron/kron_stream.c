#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <inttypes.h>
#include <string.h>
#include "graph_generator.h"

/* Streaming Kronecker edge generator: writes edges [0, N) in chunks so peak
 * memory stays bounded regardless of scale. Each chunk uses
 * generate_kronecker_range, which is deterministic per edge index, so the
 * output equals the official graph500 generator's raw edge list. */
int main(int argc, char** argv) {
    if (argc < 5) {
        fprintf(stderr, "usage: %s SCALE EDGEFACTOR SEED OUTFILE\n", argv[0]);
        return 1;
    }
    int logN = atoi(argv[1]);
    int64_t edgefactor = atoll(argv[2]);
    uint_fast32_t seed[5] = {1, 2, 3, 4, 5};
    int64_t nedges = edgefactor * ((int64_t)1 << logN);

    FILE* out = fopen(argv[4], "w");
    if (!out) { perror("fopen"); return 1; }

    const int64_t CHUNK = 16 * 1024 * 1024; /* 16M edges per chunk */
    packed_edge* buf = malloc(CHUNK * sizeof(packed_edge));
    char* line = malloc(64 * CHUNK);
    if (!buf || !line) { fprintf(stderr, "oom\n"); return 1; }

    for (int64_t start = 0; start < nedges; start += CHUNK) {
        int64_t end = start + CHUNK < nedges ? start + CHUNK : nedges;
        int64_t cnt = end - start;
        generate_kronecker_range(seed, logN, start, end, buf);
        char* p = line;
        for (int64_t i = 0; i < cnt; ++i) {
            int64_t v0 = get_v0_from_edge(&buf[i]);
            int64_t v1 = get_v1_from_edge(&buf[i]);
            /* itoa64 */
            char tmp[24]; int n = 0;
            if (v0 == 0) tmp[n++] = '0';
            while (v0 > 0) { tmp[n++] = '0' + (int)(v0 % 10); v0 /= 10; }
            while (n > 0) *p++ = tmp[--n];
            *p++ = ' ';
            n = 0;
            if (v1 == 0) tmp[n++] = '0';
            while (v1 > 0) { tmp[n++] = '0' + (int)(v1 % 10); v1 /= 10; }
            while (n > 0) *p++ = tmp[--n];
            *p++ = '\n';
        }
        fwrite(line, 1, p - line, out);
        fprintf(stderr, "\r%lld / %lld", (long long)end, (long long)nedges);
    }
    fclose(out);
    free(buf); free(line);
    fprintf(stderr, "\nwrote %" PRId64 " edges\n", nedges);
    return 0;
}
