# 血轨联机服务器 · WebSocket
# 依赖：pip install websockets
# 运行：python server.py [port]  默认 8765

import asyncio
import websockets
import json
import random
import string
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from game_engine import GameState
from constants import GameConfig, FACTION_RED, FACTION_DIS


# ─── 序列化 ─────────────────────────────────

def serial_units(units):
	result = []
	for u in units:
		result.append({
			"uid":          u.uid,
			"name":         u.name,
			"faction":      u.faction,
			"x":            u.x,
			"y":            u.y,
			"hp":           u.hp,
			"max_hp":       u.max_hp,
			"level":        u.level,
			"kills":        u.kills,
			"dead":         u.dead,
			"is_embryo":    u.is_embryo,
			"defending":    u.defending,
			"ranged":       u.ranged,
			"trait":        u.trait,
			"atk":          u.base_atk,
			"spd":          u.base_spd,
			"pending_evo":  getattr(u, "_pending_evo",  False),
			"pending_evo3": getattr(u, "_pending_evo3", False),
		})
	return result


def serial_base_states(game):
	result = {}
	for (x, y), bs in game.base_states.items():
		result[f"{x},{y}"] = {
			"owner":        bs.owner,
			"occupier":     bs.occupier,
			"occupy_count": bs.occupy_count,
		}
	return result


# ─── 房间 ───────────────────────────────────

def _make_id():
	return "".join(random.choices(string.ascii_uppercase, k=4))


class Room:
	def __init__(self, room_id, host_ws, host_name):
		self.room_id    = room_id
		self.host_ws    = host_ws
		self.host_name  = host_name
		self.guest_ws   = None
		self.guest_name = None
		self.ready      = {id(host_ws): False}
		self.factions   = {id(host_ws): FACTION_RED}
		self.conditions = set()
		self.game: GameState = None
		self.plans      = {}   # id(ws) → list[plan_dict]

	@property
	def is_full(self):
		return self.guest_ws is not None

	def join(self, guest_ws, guest_name):
		self.guest_ws   = guest_ws
		self.guest_name = guest_name
		self.ready[id(guest_ws)]   = False
		self.factions[id(guest_ws)] = FACTION_DIS

	def faction_of(self, ws):
		return self.factions.get(id(ws))

	def other(self, ws):
		return self.guest_ws if ws == self.host_ws else self.host_ws

	def both_ready(self):
		return len(self.ready) == 2 and all(self.ready.values())

	async def broadcast(self, msg):
		data = json.dumps(msg, ensure_ascii=False)
		for ws in (self.host_ws, self.guest_ws):
			if ws:
				try:
					await ws.send(data)
				except Exception:
					pass

	async def send_to(self, ws, msg):
		if ws:
			try:
				await ws.send(json.dumps(msg, ensure_ascii=False))
			except Exception:
				pass


# ─── 全局状态 ──────────────────────────────

rooms: dict[str, Room] = {}
ws_room: dict[int, str] = {}   # id(ws) → room_id


# ─── 处理消息 ──────────────────────────────

async def handle(ws, msg):
	t = msg.get("type")

	if t == "list_rooms":
		lst = [
			{"id": r.room_id, "host": r.host_name, "status": "等待加入"}
			for r in rooms.values()
			if not r.is_full and r.game is None
		]
		await ws.send(json.dumps({"type": "room_list", "rooms": lst}, ensure_ascii=False))

	elif t == "create_room":
		if id(ws) in ws_room:
			await ws.send(json.dumps({"type": "error", "msg": "已在房间中"}, ensure_ascii=False))
			return
		rid = _make_id()
		while rid in rooms:
			rid = _make_id()
		name = msg.get("name", "玩家")[:16]
		room = Room(rid, ws, name)
		rooms[rid] = room
		ws_room[id(ws)] = rid
		await ws.send(json.dumps({
			"type": "room_created", "room_id": rid,
			"faction": FACTION_RED, "host_name": name,
		}, ensure_ascii=False))
		print(f"[+] 房间 {rid} 由 {name} 创建")

	elif t == "join_room":
		rid = msg.get("room_id", "").upper().strip()
		if rid not in rooms:
			await ws.send(json.dumps({"type": "error", "msg": f"房间 {rid} 不存在"}, ensure_ascii=False))
			return
		room = rooms[rid]
		if room.is_full:
			await ws.send(json.dumps({"type": "error", "msg": "房间已满"}, ensure_ascii=False))
			return
		if id(ws) in ws_room:
			await ws.send(json.dumps({"type": "error", "msg": "已在其他房间中"}, ensure_ascii=False))
			return
		name = msg.get("name", "玩家2")[:16]
		room.join(ws, name)
		ws_room[id(ws)] = rid
		await ws.send(json.dumps({
			"type": "room_joined", "room_id": rid,
			"faction": FACTION_DIS,
			"host_name": room.host_name, "guest_name": name,
		}, ensure_ascii=False))
		await room.send_to(room.host_ws, {"type": "player_joined", "guest_name": name})
		print(f"[+] {name} 加入房间 {rid}")

	elif t == "set_conditions":
		rid = ws_room.get(id(ws))
		if not rid:
			return
		room = rooms[rid]
		if ws != room.host_ws:
			await ws.send(json.dumps({"type": "error", "msg": "只有房主可以设置条件"}, ensure_ascii=False))
			return
		room.conditions = set(msg.get("conditions", []))
		await room.broadcast({"type": "conditions_updated", "conditions": list(room.conditions)})

	elif t == "ready":
		rid = ws_room.get(id(ws))
		if not rid or rid not in rooms:
			return
		room = rooms[rid]
		room.ready[id(ws)] = True
		await room.broadcast({"type": "player_ready", "faction": room.faction_of(ws)})
		if room.both_ready() and room.game is None:
			await start_game(room)

	elif t == "unready":
		rid = ws_room.get(id(ws))
		if not rid or rid not in rooms:
			return
		room = rooms[rid]
		room.ready[id(ws)] = False
		await room.broadcast({"type": "player_unready", "faction": room.faction_of(ws)})

	elif t == "submit_plan":
		rid = ws_room.get(id(ws))
		if not rid or rid not in rooms:
			return
		room = rooms[rid]
		if room.game is None:
			return
		room.plans[id(ws)] = msg.get("plans", [])
		other = room.other(ws)
		await room.send_to(other, {"type": "opponent_submitted"})
		if len(room.plans) == 2:
			await execute_turn(room)

	elif t == "chat":
		rid = ws_room.get(id(ws))
		if not rid or rid not in rooms:
			return
		room = rooms[rid]
		await room.broadcast({
			"type": "chat",
			"faction": room.faction_of(ws),
			"msg": msg.get("msg", "")[:200],
		})


async def start_game(room: Room):
	cfg = GameConfig("9x9")
	cfg.conditions = room.conditions
	game = GameState(cfg)
	game.setup()
	room.game  = game
	room.plans = {}
	cond_names = {
		"abundance": "丰饶", "war_gift": "战争恩赐",
		"tide": "潮水", "extreme_terrain": "极端地形", "long_war": "长线战",
	}
	cond_str = "  |  ".join(cond_names.get(c, c) for c in room.conditions) or "标准对局"
	await room.broadcast({
		"type":       "game_start",
		"conditions": list(room.conditions),
		"cond_str":   cond_str,
		"units":      serial_units(game.units),
		"base_states": serial_base_states(game),
		"turn":       game.turn,
	})
	print(f"[*] 房间 {room.room_id} 开局  条件={list(room.conditions)}")


async def execute_turn(room: Room):
	game = room.game
	# 应用双方规划
	for ws_id, plans in room.plans.items():
		for plan in plans:
			u = game.get_unit_by_uid(plan["uid"])
			if not u:
				continue
			u.planned_dir    = tuple(plan.get("dir", [0, 0]))
			u.planned_action = plan.get("action", "none")
			evo = plan.get("evo_plan")
			if evo is not None:
				u._evo_plan = evo
	room.plans = {}
	log = game.execute_turn()
	result = {
		"type":              "turn_result",
		"turn":              game.turn,
		"log":               log,
		"units":             serial_units(game.units),
		"base_states":       serial_base_states(game),
		"winner":            game.winner,
		"win_reason":        game.win_reason,
		"attack_events":     [list(e) for e in game.last_attack_events],
		"attack_main_end":   game.last_attack_main_end,
		"heartbeat":         game.heartbeat_event,
	}
	await room.broadcast(result)
	if game.winner:
		print(f"[*] 房间 {room.room_id} 结束  胜方={game.winner}")
		await asyncio.sleep(60)
		rooms.pop(room.room_id, None)


# ─── 断线清理 ──────────────────────────────

async def cleanup(ws):
	rid = ws_room.pop(id(ws), None)
	if not rid or rid not in rooms:
		return
	room = rooms.pop(rid)
	for w in (room.host_ws, room.guest_ws):
		ws_room.pop(id(w), None) if w else None
	other = room.other(ws)
	await room.send_to(other, {"type": "opponent_disconnected"})
	print(f"[-] 房间 {rid} 解散（玩家断线）")


# ─── WebSocket 入口 ────────────────────────

async def ws_handler(ws):
	addr = getattr(ws, "remote_address", "?")
	print(f"[+] 连接 {addr}")
	try:
		async for raw in ws:
			try:
				msg = json.loads(raw)
			except Exception:
				continue
			await handle(ws, msg)
	except websockets.exceptions.ConnectionClosed:
		pass
	finally:
		await cleanup(ws)
		print(f"[-] 断线 {addr}")


async def main():
	port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
	print(f"[兵戮灾联机服务器] ws://0.0.0.0:{port}")
	async with websockets.serve(ws_handler, "0.0.0.0", port):
		await asyncio.Future()


if __name__ == "__main__":
	asyncio.run(main())
