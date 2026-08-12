# Filename: keep_alive.py
from aiohttp import web
import os

async def handle(request):
    return web.Response(text="Bot is running smoothly. Ready for business!")

async def start_web_server():
    app = web.Application()
    app.add_routes([web.get('/', handle)])
    # Render မှပေးသော PORT ကို ရယူခြင်း (မရှိပါက 8080 ကိုသုံးမည်)
    port = int(os.environ.get('PORT', 8080))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"[System] Web server started on port {port} for Uptime Robot.")