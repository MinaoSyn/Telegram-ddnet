# main.py — запускает бота + фейковый веб-сервер для Render

import threading
import asyncio
from http.server import HTTPServer, BaseHTTPRequestHandler
from bot import main as bot_main

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, *args):
        pass

def run_web():
    HTTPServer(("0.0.0.0", 10000), Handler).serve_forever()

if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()
    bot_main()
