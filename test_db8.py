import asyncio
from app.routers.monitoring_spirit_admin import list_current_verdicts

async def main():
    try:
        verdicts = await list_current_verdicts("bypass")
        print("Success! Verdicts count:", len(verdicts))
    except Exception as e:
        import traceback
        traceback.print_exc()

asyncio.run(main())
