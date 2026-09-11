from app.scorer import run_scoring

def run():
    print("Starting backfill for all clusters (all_time=True)...")
    result = run_scoring(all_time=True)
    print("Backfill complete! Result:")
    print(result)

if __name__ == "__main__":
    run()
