import asyncio
from app.routers.monitoring_spirit_admin import list_current_verdicts

async def main():
    try:
        res = await list_current_verdicts("test")
        print("Success:", res)
    except Exception as e:
        import traceback
        traceback.print_exc()

asyncio.run(main())
