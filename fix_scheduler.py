with open("app/scheduler.py", "r") as f:
    content = f.read()

import_statement = "from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError\n"
if "ThreadPoolExecutor" not in content:
    content = import_statement + content

old_fetch_job = """def run_fetch_job():
    try:
        fetch_result = run_fetch()
        logger.info(f"Fetch result: {fetch_result}")
    except Exception as e:
        logger.error(f"Fetch job failed: {e}")"""

new_fetch_job = """def run_fetch_job():
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(run_fetch)
        try:
            result = future.result(timeout=480)  # 8 minute max
            logger.info(f"Fetch result: {result}")
        except FuturesTimeoutError:
            logger.error("[fetch] Job timed out after 8 minutes - cancelling")
            future.cancel()
        except Exception as e:
            logger.error(f"[fetch] Job failed: {e}")"""

content = content.replace(old_fetch_job, new_fetch_job)

old_registration = """    # 1. Fetch Job - High priority, runs strictly on schedule
    scheduler.add_job(
        run_fetch_job,
        "interval",
        minutes=interval,
        id="run_fetch_job",
        replace_existing=True,
    )"""

new_registration = """    # 1. Fetch Job - High priority, runs strictly on schedule
    scheduler.add_job(
        run_fetch_job,
        "interval",
        minutes=interval,
        id="run_fetch_job",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=60
    )"""

content = content.replace(old_registration, new_registration)

with open("app/scheduler.py", "w") as f:
    f.write(content)

