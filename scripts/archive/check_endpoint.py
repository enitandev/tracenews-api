import asyncio
from app.routers.monitoring_spirit_admin import list_current_verdicts
from app.admin_auth import require_permission

async def main():
    try:
        await list_current_verdicts("test")
    except Exception as e:
        import traceback
        traceback.print_exc()

asyncio.run(main())
