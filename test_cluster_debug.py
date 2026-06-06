from app.clusterer import run_clustering
import logging
import sys

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
res = run_clustering()
print("Result:", res)
