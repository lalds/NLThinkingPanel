import asyncio
import json
import os
from aiohttp import web
import aiohttp
from core.logger import logger

class WebPanel:
    """Веб-сервер для визуальной панели аватара."""
    
    def __init__(self, host='0.0.0.0', port=5000):
        self.host = host
        self.port = port
        self.app = web.Application()
        self.websockets = set()
        
        # Настройка маршрутов
        self.app.router.add_get('/ws', self.websocket_handler)
        
        # Статические файлы
        static_path = os.path.join(os.getcwd(), 'web')
        self.app.router.add_static('/', static_path, show_index=True)
        
        self.runner = None
        self.site = None

    async def websocket_handler(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        
        self.websockets.add(ws)
        logger.info(f"Новое подключение к веб-панели (всего: {len(self.websockets)})")
        
        try:
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    if msg.data == 'close':
                        await ws.close()
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.error(f'ws connection closed with exception {ws.exception()}')
        finally:
            self.websockets.remove(ws)
            logger.info(f"Подключение закрыто (осталось: {len(self.websockets)})")
            
        return ws

    async def broadcast(self, data: dict):
        """Отправка данных всем подключенным клиентам."""
        if not self.websockets:
            return
            
        message = json.dumps(data)
        disconnected = set()
        
        for ws in self.websockets:
            try:
                await ws.send_str(message)
            except Exception:
                disconnected.add(ws)
        
        for ws in disconnected:
            self.websockets.remove(ws)

    async def start(self):
        """Запуск веб-сервера."""
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, self.host, self.port)
        await self.site.start()
        logger.info(f"🚀 Веб-панель аватара запущена на http://{self.host}:{self.port}")

    async def stop(self):
        """Остановка веб-сервера."""
        if self.runner:
            await self.runner.cleanup()

# Глобальный экземпляр
web_panel = WebPanel()
