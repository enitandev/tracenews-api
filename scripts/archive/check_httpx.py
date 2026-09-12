import asyncio
import httpx

client = httpx.AsyncClient()

async def fetch():
    r = await client.get("https://example.com")
    print(r.status_code)

asyncio.run(fetch())
asyncio.run(fetch())
