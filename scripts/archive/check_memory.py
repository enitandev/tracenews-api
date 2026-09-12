import tracemalloc
import gc
import logging
logging.getLogger().setLevel(logging.CRITICAL)

from app.fetcher import run_fetch
from app.clusterer import run_clustering
from app.scorer import run_scoring
from app.framer import run_framing_job

tracemalloc.start()

def print_mem(label):
    current, peak = tracemalloc.get_traced_memory()
    print(f"{label}: Current: {current / 10**6:.2f}MB, Peak: {peak / 10**6:.2f}MB")

print_mem("Initial RSS")

print("Running fetch...")
run_fetch()
gc.collect()
print_mem("After fetch")

print("Running clustering...")
run_clustering()
gc.collect()
print_mem("After clustering")

print("Running scoring...")
run_scoring()
gc.collect()
print_mem("After scoring")

print("Running framing...")
run_framing_job()
gc.collect()
print_mem("After framing")

print("\n--- Loop 2 ---")
run_fetch()
gc.collect()
print_mem("After fetch 2")

run_clustering()
gc.collect()
print_mem("After clustering 2")

run_scoring()
gc.collect()
print_mem("After scoring 2")

run_framing_job()
gc.collect()
print_mem("After framing 2")

print("\n--- Loop 3 ---")
run_fetch()
gc.collect()
print_mem("After fetch 3")

run_clustering()
gc.collect()
print_mem("After clustering 3")
