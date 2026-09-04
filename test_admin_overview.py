import asyncio
from app.routers.admin_overview import get_overview

async def main():
    try:
        res = await get_overview("dummy")
        print("Success!")
    except Exception as e:
        import traceback
        traceback.print_exc()

asyncio.run(main())
