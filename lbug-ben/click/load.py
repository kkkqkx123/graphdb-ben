#!/usr/bin/env python3

try:
    import lbug
except ImportError:
    # PyPI wheel (ladybug==0.22.3) exposes the top-level module as `ladybug`
    import ladybug as lbug
import timeit
import psutil

db = lbug.Database("mydb")
con = lbug.Connection(db)

start = timeit.default_timer()
con.execute(open("create.cypher").read())
con.execute("COPY hits FROM 'hits.csv' (PARALLEL=false);")
end = timeit.default_timer()
print(end - start)
