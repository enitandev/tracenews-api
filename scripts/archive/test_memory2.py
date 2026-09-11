import tracemalloc
import gc
import logging
logging.getLogger().setLevel(logging.CRITICAL)

from app.clusterer import run_clustering
from app.scorer import run_scoring
from app.framer import run_framing_job

tracemalloc.start()

def print_mem(label):
    current, peak = tracemalloc.get_traced_memory()
    print(f"{label}: Current: {current / 10**6:.2f}MB, Peak: {peak / 10**6:.2f}MB")

print_mem("Initial")

for i in range(1, 10):
    run_clustering()
    gc.collect()
    print_mem(f"After clustering {i}")

    run_scoring()
    gc.collect()
    print_mem(f"After scoring {i}")

    run_framing_job()
    gc.collect()
    print_mem(f"After framing {i}")
