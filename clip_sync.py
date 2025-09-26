import asyncio, json, uuid, time, argparse, hmac, hashlib
import websockets
import pyperclip

POLL_SEC = 0.25

class ClipSync:
    def __init__(self, secret: str | None):
        self.node_id = str(uuid.uuid4())
        self.secret = secret.encode("utf-8") if secret else None
        self.last_text = None  # 延迟获取，避免启动时立刻风暴
        self.last_set_from = None

    def _sign(self, payload_bytes: bytes) -> str | None:
        if not self.secret:
            return None
        return hmac.new(self.secret, payload_bytes, hashlib.sha256).hexdigest()

    def _verify(self, payload_bytes: bytes, sig: str | None) -> bool:
        if not self.secret:
            return True
        if not sig:
            return False
        try:
            return hmac.compare_digest(self._sign(payload_bytes), sig)
        except Exception:
            return False

    def make_message(self, text: str) -> str:
        obj = {"type": "text", "text": text, "from": self.node_id, "ts": time.time()}
        payload = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return json.dumps({"payload": obj, "sig": self._sign(payload)}, ensure_ascii=False)

    async def producer(self, ws: websockets.WebSocketClientProtocol):
        # 首次读入现有剪贴板，避免刚连上就把历史内容发出去
        if self.last_text is None:
            try:
                self.last_text = pyperclip.paste()
            except Exception:
                self.last_text = ""
        while True:
            await asyncio.sleep(POLL_SEC)
            try:
                current = pyperclip.paste()
            except Exception:
                continue
            if not isinstance(current, str):
                # 只同步文本；其他类型忽略
                continue
            if current != self.last_text:
                self.last_text = current
                await ws.send(self.make_message(current))

    async def consumer(self, ws: websockets.WebSocketClientProtocol):
        async for message in ws:
            try:
                wrapper = json.loads(message)
                obj = wrapper.get("payload", {})
                sig = wrapper.get("sig")
                raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                if not self._verify(raw, sig):
                    continue
                if obj.get("type") != "text":
                    continue
                if obj.get("from") == self.node_id:
                    continue
                text = obj.get("text", "")
                if text != self.last_text:
                    pyperclip.copy(text)
                    self.last_text = text
            except Exception:
                # 为简洁省略日志；生产可加 logging
                continue

    async def run_server(self, host: str, port: int):
        async def handler(ws):
            prod = asyncio.create_task(self.producer(ws))
            cons = asyncio.create_task(self.consumer(ws))
            done, pending = await asyncio.wait({prod, cons}, return_when=asyncio.FIRST_COMPLETED)
            for t in pending: t.cancel()
        async with websockets.serve(handler, host, port, ping_interval=20, ping_timeout=20):
            print(f"Listening on {host}:{port}")
            await asyncio.Future()  # run forever

    async def run_client(self, url: str):
        while True:
            try:
                async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
                    print(f"Connected to {url}")
                    prod = asyncio.create_task(self.producer(ws))
                    cons = asyncio.create_task(self.consumer(ws))
                    done, pending = await asyncio.wait({prod, cons}, return_when=asyncio.FIRST_COMPLETED)
                    for t in pending: t.cancel()
            except Exception:
                print("Disconnected; reconnecting in 2s...")
                await asyncio.sleep(2)

def parse_addr(addr: str) -> tuple[str,int]:
    host, port = addr.rsplit(":", 1)
    return host, int(port)

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Cross-OS clipboard sync (text only)")
    ap.add_argument("--listen", help="host:port to listen on")
    ap.add_argument("--connect", help="ws://host:port to connect to")
    ap.add_argument("--secret", help="shared secret for HMAC (optional)")
    args = ap.parse_args()

    if not args.listen and not args.connect:
        ap.error("Provide --listen or --connect")

    app = ClipSync(secret=args.secret)
    if args.listen:
        h, p = parse_addr(args.listen)
        asyncio.run(app.run_server(h, p))
    else:
        asyncio.run(app.run_client(args.connect))
