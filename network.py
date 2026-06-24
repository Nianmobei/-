# 血轨联机客户端 · 网络层
# 在后台线程运行 asyncio WebSocket，主线程通过 send/poll 交互
# 依赖：pip install websockets

import asyncio
import threading
import json
from queue import Queue, Empty


class NetworkClient:
	def __init__(self):
		self._recv_q  = Queue()
		self._send_q  = Queue()
		self.connected  = False
		self.error: str = None
		self._thread    = None

	# ─── 主线程调用 ────────────────────────

	def connect(self, url: str):
		"""开启后台线程建立 WebSocket 连接。"""
		self.url     = url
		self.error   = None
		self.connected = False
		self._thread = threading.Thread(target=self._run, daemon=True)
		self._thread.start()

	def send(self, msg: dict):
		self._send_q.put(msg)

	def poll(self) -> list:
		"""取出所有待处理消息，主循环每帧调用。"""
		msgs = []
		while True:
			try:
				msgs.append(self._recv_q.get_nowait())
			except Empty:
				break
		return msgs

	@property
	def is_alive(self) -> bool:
		return self._thread is not None and self._thread.is_alive()

	@property
	def is_connecting(self) -> bool:
		return self.is_alive and not self.connected and self.error is None

	# ─── 后台线程 ──────────────────────────

	def _run(self):
		loop = asyncio.new_event_loop()
		asyncio.set_event_loop(loop)
		try:
			loop.run_until_complete(self._main())
		except Exception as e:
			self.error = str(e)
		finally:
			self.connected = False

	async def _main(self):
		import websockets
		try:
			async with websockets.connect(
				self.url,
				ping_interval=20,
				ping_timeout=10,
				open_timeout=8,
			) as ws:
				self.connected = True
				await asyncio.gather(
					self._send_loop(ws),
					self._recv_loop(ws),
				)
		except Exception as e:
			self.error = str(e)
			self.connected = False

	async def _send_loop(self, ws):
		while True:
			try:
				msg = self._send_q.get_nowait()
				await ws.send(json.dumps(msg, ensure_ascii=False))
			except Empty:
				await asyncio.sleep(0.02)
			except Exception:
				break

	async def _recv_loop(self, ws):
		try:
			async for raw in ws:
				try:
					self._recv_q.put(json.loads(raw))
				except Exception:
					pass
		except Exception:
			self.connected = False
