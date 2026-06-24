# 血轨：红教团兵棋推演规程 — 主程序入口 v2.0（联机版）
# 本地 + 互联网双人对弈

import sys
import os
import time
import pygame
from constants import *
from game_engine import GameState
from unit import Unit, UNIT_TEMPLATES
from renderer import Renderer
from ui import UIState
from animator import AnimationManager
from network import NetworkClient


# ─────────────── 字体 ───────────────────

def load_fonts():
	candidates = [
		r"C:\Windows\Fonts\msyh.ttc",
		r"C:\Windows\Fonts\msyhbd.ttc",
		r"C:\Windows\Fonts\simsun.ttc",
		r"C:\Windows\Fonts\simhei.ttf",
		r"C:\Windows\Fonts\STKAITI.TTF",
	]
	fp = None
	for p in candidates:
		if os.path.isfile(p):
			fp = p; break

	def make(sz):
		if fp:
			try: return pygame.font.Font(fp, sz)
			except: pass
		return pygame.font.SysFont("arial", sz)

	return {
		"title": make(30), "bold": make(17),
		"small": make(13), "unit": make(11), "tiny": make(10),
	}


# ─────────────── 通用绘制工具 ───────────

def draw_btn(screen, fonts, rect, label, hov, active=False):
	bg  = (60, 38, 10) if active else ((45, 28, 8) if hov else (22, 14, 6))
	bdr = C_GOLD if active else (C_RED if hov else C_PANEL_BDR)
	pygame.draw.rect(screen, bg, rect, border_radius=7)
	pygame.draw.rect(screen, bdr, rect, 2, border_radius=7)
	ts = fonts["bold"].render(label, True, C_GOLD if active else C_WHITE)
	screen.blit(ts, ts.get_rect(center=rect.center))


def draw_input(screen, fonts, rect, text, active, placeholder=""):
	bg  = (30, 20, 8) if active else (18, 12, 6)
	bdr = C_GOLD if active else C_PANEL_BDR
	pygame.draw.rect(screen, bg, rect, border_radius=5)
	pygame.draw.rect(screen, bdr, rect, 2, border_radius=5)
	display = text if text else placeholder
	col = C_WHITE if text else C_GRAY
	ts = fonts["bold"].render(display, True, col)
	screen.blit(ts, (rect.x + 10, rect.centery - ts.get_height() // 2))
	if active and text is not None:
		cursor_x = rect.x + 10 + fonts["bold"].size(text)[0] + 2
		if int(time.time() * 2) % 2 == 0:
			pygame.draw.line(screen, C_GOLD,
				(cursor_x, rect.y + 6), (cursor_x, rect.bottom - 6), 2)


# ─────────────── 模式选择 ───────────────

def show_mode_select(screen, fonts, clock) -> str:
	"""返回 'local' 或 'online'"""
	sw, sh = screen.get_size()
	BTN_W, BTN_H, GAP = 380, 90, 32
	sy = sh // 2 - (BTN_H * 2 + GAP) // 2
	btn_local  = pygame.Rect(sw // 2 - BTN_W // 2, sy, BTN_W, BTN_H)
	btn_online = pygame.Rect(sw // 2 - BTN_W // 2, sy + BTN_H + GAP, BTN_W, BTN_H)

	while True:
		clock.tick(60)
		mx, my = pygame.mouse.get_pos()
		for event in pygame.event.get():
			if event.type == pygame.QUIT:
				pygame.quit(); sys.exit(0)
			if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
				if btn_local.collidepoint(mx, my):  return "local"
				if btn_online.collidepoint(mx, my): return "online"

		screen.fill(C_BG_MENU)
		title = fonts["title"].render("兵戮灾 · 红之纷争", True, C_GOLD)
		screen.blit(title, title.get_rect(center=(sw // 2, sy - 52)))
		sub = fonts["small"].render("v2.0  选择游戏模式", True, C_GRAY)
		screen.blit(sub, sub.get_rect(center=(sw // 2, sy - 24)))

		for btn, label, desc, col in [
			(btn_local,  "本地对战",  "双人共用键鼠 / 单人与 AI",  C_RED),
			(btn_online, "互联网对战", "通过服务器与远程玩家对弈", C_DIS),
		]:
			hov = btn.collidepoint(mx, my)
			draw_btn(screen, fonts, btn, "", hov)
			ls = fonts["bold"].render(label, True, col)
			screen.blit(ls, ls.get_rect(center=(btn.centerx, btn.y + 28)))
			ds = fonts["small"].render(desc, True, C_GRAY)
			screen.blit(ds, ds.get_rect(center=(btn.centerx, btn.y + 58)))

		pygame.display.flip()


# ─────────────── 开局条件选择 ──────────────

def show_condition_select(screen, fonts, clock) -> set:
	"""开局条件勾选界面，返回选中条件字符串集合。"""
	sw, sh = screen.get_size()
	CONDITIONS = [
		("abundance",       "丰饶",     "每回合结束，所有存活单位 +1 HP"),
		("war_gift",        "战争恩赐", "每回合结束，所有存活 lv1/lv2 单位 +1 经验"),
		("tide",            "潮水",     "双方初始 7 个基础兵种，分布更分散"),
		("extreme_terrain", "极端地形", "随机生成高地与战壕（中间带）"),
		("long_war",        "长线战",   "每 3 回合，本阵未被占领时补充 1 个基础兵种"),
	]
	selected = set()
	BTN_W, BTN_H, GAP = 500, 46, 8
	total_h = len(CONDITIONS) * (BTN_H + GAP) + 70
	base_y  = sh // 2 - total_h // 2

	cond_rects = [(cid,
		pygame.Rect(sw // 2 - BTN_W // 2,
			base_y + 50 + i * (BTN_H + GAP), BTN_W, BTN_H))
		for i, (cid, _, _) in enumerate(CONDITIONS)]
	start_rect = pygame.Rect(sw // 2 - 130,
		base_y + 50 + len(CONDITIONS) * (BTN_H + GAP) + 12, 260, 46)

	while True:
		clock.tick(60)
		mx, my = pygame.mouse.get_pos()
		for event in pygame.event.get():
			if event.type == pygame.QUIT:
				pygame.quit(); sys.exit(0)
			if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
				for cid, r in cond_rects:
					if r.collidepoint(mx, my):
						selected.discard(cid) if cid in selected else selected.add(cid)
				if start_rect.collidepoint(mx, my):
					return selected

		screen.fill(C_BG_MENU)
		title = fonts["title"].render("开局条件", True, C_GOLD)
		screen.blit(title, title.get_rect(center=(sw // 2, base_y + 14)))
		sub = fonts["small"].render("可叠加多项 · 点击切换 · 确认后点击「开始战局」", True, C_GRAY)
		screen.blit(sub, sub.get_rect(center=(sw // 2, base_y + 36)))

		for (cid, r), (_, name, desc) in zip(cond_rects, CONDITIONS):
			is_sel = cid in selected
			hov    = r.collidepoint(mx, my)
			bg  = (50, 32, 10) if is_sel else ((28, 18, 8) if hov else (16, 10, 6))
			bdr = C_GOLD if is_sel else (C_RED if hov else C_PANEL_BDR)
			pygame.draw.rect(screen, bg,  r, border_radius=6)
			pygame.draw.rect(screen, bdr, r, 2, border_radius=6)
			cb = pygame.Rect(r.x + 10, r.centery - 9, 18, 18)
			if is_sel:
				pygame.draw.rect(screen, C_GOLD, cb, border_radius=3)
				pygame.draw.line(screen, C_BG, (cb.x+3, cb.centery), (cb.centerx-1, cb.bottom-4), 2)
				pygame.draw.line(screen, C_BG, (cb.centerx-1, cb.bottom-4), (cb.right-3, cb.y+4), 2)
			else:
				pygame.draw.rect(screen, C_GRAY, cb, 2, border_radius=3)
			ns = fonts["bold"].render(name, True, C_GOLD if is_sel else C_WHITE)
			screen.blit(ns, (r.x + 36, r.y + 6))
			ds = fonts["tiny"].render(desc, True, (180, 160, 130) if is_sel else C_GRAY)
			screen.blit(ds, (r.x + 36, r.y + 26))

		hov_s = start_rect.collidepoint(mx, my)
		pygame.draw.rect(screen, (60, 36, 8) if hov_s else (30, 18, 5), start_rect, border_radius=8)
		pygame.draw.rect(screen, C_GOLD if hov_s else C_PANEL_BDR, start_rect, 2, border_radius=8)
		st = fonts["bold"].render("开始战局 →", True, C_GOLD)
		screen.blit(st, st.get_rect(center=start_rect.center))
		pygame.display.flip()


# ═══════════════════════════════════════════
# 联机相关界面
# ═══════════════════════════════════════════

DEFAULT_SERVER = "ws://localhost:8765"
COND_NAMES = {
	"abundance": "丰饶", "war_gift": "战争恩赐",
	"tide": "潮水", "extreme_terrain": "极端地形", "long_war": "长线战",
}
CONDITIONS_DEF = [
	("abundance",       "丰饶",     "每回合结束，所有存活单位 +1 HP"),
	("war_gift",        "战争恩赐", "每回合结束，所有存活 lv1/lv2 单位 +1 经验"),
	("tide",            "潮水",     "双方初始 7 个基础兵种，分布更分散"),
	("extreme_terrain", "极端地形", "随机生成高地与战壕（中间带）"),
	("long_war",        "长线战",   "每 3 回合，本阵未被占领时补充 1 个基础兵种"),
]


def show_online_setup(screen, fonts, clock):
	"""输入玩家名 + 服务器地址，返回 (name, server_url)；按 ESC 返回 None。"""
	sw, sh = screen.get_size()
	W = 480
	cx = sw // 2

	fields = [
		{"label": "玩家名称", "text": "", "ph": "输入你的名称", "max": 16},
		{"label": "服务器地址", "text": DEFAULT_SERVER, "ph": DEFAULT_SERVER, "max": 80},
	]
	focus   = 0
	ERR_H   = 26
	base_y  = sh // 2 - 120
	f_rects = [
		pygame.Rect(cx - W // 2, base_y + 60 + i * 80, W, 40)
		for i in range(len(fields))
	]
	ok_rect = pygame.Rect(cx - 110, base_y + 60 + len(fields) * 80 + 16, 220, 44)
	error   = ""

	while True:
		clock.tick(60)
		mx, my = pygame.mouse.get_pos()
		for event in pygame.event.get():
			if event.type == pygame.QUIT:
				pygame.quit(); sys.exit(0)
			if event.type == pygame.KEYDOWN:
				if event.key == pygame.K_ESCAPE:
					return None
				elif event.key == pygame.K_TAB:
					focus = (focus + 1) % len(fields)
				elif event.key == pygame.K_RETURN:
					if focus < len(fields) - 1:
						focus += 1
					else:
						goto_connect = True
				elif event.key == pygame.K_BACKSPACE:
					fields[focus]["text"] = fields[focus]["text"][:-1]
				else:
					ch = event.unicode
					if ch and len(fields[focus]["text"]) < fields[focus]["max"]:
						fields[focus]["text"] += ch
			if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
				for i, r in enumerate(f_rects):
					if r.collidepoint(mx, my):
						focus = i
				if ok_rect.collidepoint(mx, my):
					name = fields[0]["text"].strip()
					url  = fields[1]["text"].strip() or DEFAULT_SERVER
					if not name:
						error = "请输入玩家名称"
					else:
						return name, url

		screen.fill(C_BG_MENU)
		title = fonts["title"].render("联机对战 · 连接设置", True, C_GOLD)
		screen.blit(title, title.get_rect(center=(cx, base_y + 14)))
		sub = fonts["small"].render("填写名称与服务器地址，ESC 返回", True, C_GRAY)
		screen.blit(sub, sub.get_rect(center=(cx, base_y + 40)))

		for i, (f, r) in enumerate(zip(fields, f_rects)):
			ls = fonts["small"].render(f["label"], True, C_GRAY)
			screen.blit(ls, (r.x, r.y - 18))
			draw_input(screen, fonts, r, f["text"], focus == i, f["ph"])

		if error:
			es = fonts["small"].render(error, True, (220, 80, 60))
			screen.blit(es, es.get_rect(center=(cx, ok_rect.y - 14)))

		hov = ok_rect.collidepoint(mx, my)
		draw_btn(screen, fonts, ok_rect, "确认并连接 →", hov)
		pygame.display.flip()


def show_connecting(screen, fonts, clock, net: NetworkClient, url: str):
	"""显示连接中动画，成功返回 True，失败返回 False，ESC 取消。"""
	sw, sh = screen.get_size()
	cx, cy = sw // 2, sh // 2
	dots   = 0
	timer  = 0.0

	while True:
		dt = clock.tick(60) / 1000.0
		timer += dt
		if timer > 0.4:
			timer = 0; dots = (dots + 1) % 4

		for event in pygame.event.get():
			if event.type == pygame.QUIT:
				pygame.quit(); sys.exit(0)
			if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
				return False

		if net.connected:
			return True
		if net.error:
			# 显示错误 2 秒后返回
			screen.fill(C_BG_MENU)
			es = fonts["bold"].render(f"连接失败：{net.error}", True, (220, 80, 60))
			screen.blit(es, es.get_rect(center=(cx, cy)))
			hs = fonts["small"].render("按任意键返回", True, C_GRAY)
			screen.blit(hs, hs.get_rect(center=(cx, cy + 30)))
			pygame.display.flip()
			waiting = True
			while waiting:
				clock.tick(60)
				for ev in pygame.event.get():
					if ev.type in (pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN):
						waiting = False
					if ev.type == pygame.QUIT:
						pygame.quit(); sys.exit(0)
			return False

		screen.fill(C_BG_MENU)
		ts = fonts["bold"].render(f"正在连接{' .' * dots}", True, C_GOLD)
		screen.blit(ts, ts.get_rect(center=(cx, cy - 16)))
		us = fonts["small"].render(url, True, C_GRAY)
		screen.blit(us, us.get_rect(center=(cx, cy + 16)))
		hint = fonts["tiny"].render("ESC 取消", True, C_DARK_GRAY)
		screen.blit(hint, hint.get_rect(center=(cx, cy + 42)))
		pygame.display.flip()


def show_online_lobby(screen, fonts, clock, net: NetworkClient, player_name: str):
	"""
	大厅界面：创建房间 / 加入房间 / 房间列表。
	返回 room_info dict 或 None（返回上一级）。
	"""
	sw, sh = screen.get_size()
	cx     = sw // 2
	W      = 520
	base_y = 60

	join_text  = ""
	join_focus = False
	join_rect  = pygame.Rect(cx - W // 2, base_y + 116, W - 160, 40)
	join_btn   = pygame.Rect(cx - W // 2 + W - 154, base_y + 116, 148, 40)
	create_btn = pygame.Rect(cx - W // 2, base_y + 64, W, 44)
	back_btn   = pygame.Rect(cx - 80, sh - 56, 160, 38)

	rooms      = []
	last_req   = 0.0
	error_msg  = ""
	info_msg   = ""

	def req_list():
		net.send({"type": "list_rooms"})

	req_list()

	while True:
		now = time.time()
		if now - last_req > 2.5:
			req_list(); last_req = now

		clock.tick(60)
		mx, my = pygame.mouse.get_pos()

		for msg in net.poll():
			t = msg.get("type")
			if t == "room_list":
				rooms = msg.get("rooms", [])
			elif t == "room_created":
				return {"action": "created", **msg}
			elif t == "room_joined":
				return {"action": "joined", **msg}
			elif t == "error":
				error_msg = msg.get("msg", "")
				info_msg  = ""

		for event in pygame.event.get():
			if event.type == pygame.QUIT:
				pygame.quit(); sys.exit(0)
			if event.type == pygame.KEYDOWN:
				if event.key == pygame.K_ESCAPE:
					return None
				if join_focus:
					if event.key == pygame.K_BACKSPACE:
						join_text = join_text[:-1]
					elif event.key == pygame.K_RETURN:
						if join_text.strip():
							net.send({"type": "join_room",
								"room_id": join_text.strip().upper(),
								"name": player_name})
					else:
						ch = event.unicode.upper()
						if ch.isalpha() and len(join_text) < 4:
							join_text += ch
			if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
				error_msg = ""
				if join_rect.collidepoint(mx, my):
					join_focus = True
				else:
					join_focus = False
				if create_btn.collidepoint(mx, my):
					net.send({"type": "create_room", "name": player_name})
				if join_btn.collidepoint(mx, my) and join_text.strip():
					net.send({"type": "join_room",
						"room_id": join_text.strip().upper(),
						"name": player_name})
				if back_btn.collidepoint(mx, my):
					return None
				# 点击房间列表中的房间
				for i, r in enumerate(rooms):
					row = pygame.Rect(cx - W // 2, base_y + 188 + i * 48, W, 42)
					if row.collidepoint(mx, my):
						net.send({"type": "join_room",
							"room_id": r["id"],
							"name": player_name})

		# ── 绘制 ──────────────────────────────
		screen.fill(C_BG_MENU)
		title = fonts["title"].render("联机大厅", True, C_GOLD)
		screen.blit(title, title.get_rect(center=(cx, base_y + 22)))
		name_s = fonts["small"].render(f"玩家：{player_name}", True, C_GRAY)
		screen.blit(name_s, (cx - W // 2, base_y + 42))

		# 创建房间按钮
		hov_c = create_btn.collidepoint(mx, my)
		draw_btn(screen, fonts, create_btn, "＋  创建新房间", hov_c)

		# 加入房间输入框
		label = fonts["small"].render("房间代码（4位字母）", True, C_GRAY)
		screen.blit(label, (cx - W // 2, base_y + 98))
		draw_input(screen, fonts, join_rect, join_text, join_focus, "ABCD")
		hov_j = join_btn.collidepoint(mx, my)
		draw_btn(screen, fonts, join_btn, "加入 →", hov_j)

		# 房间列表标题
		sep_y = base_y + 168
		pygame.draw.line(screen, C_PANEL_BDR, (cx - W // 2, sep_y), (cx + W // 2, sep_y))
		ls = fonts["small"].render("公开房间列表（每2.5秒刷新）", True, C_GRAY)
		screen.blit(ls, (cx - W // 2, sep_y + 6))

		if rooms:
			for i, r in enumerate(rooms):
				row = pygame.Rect(cx - W // 2, base_y + 188 + i * 48, W, 42)
				hov = row.collidepoint(mx, my)
				bg  = (38, 24, 8) if hov else (20, 13, 6)
				pygame.draw.rect(screen, bg, row, border_radius=5)
				pygame.draw.rect(screen, C_PANEL_BDR, row, 1, border_radius=5)
				id_s  = fonts["bold"].render(r["id"],   True, C_GOLD)
				hos_s = fonts["small"].render(r["host"], True, C_WHITE)
				sta_s = fonts["tiny"].render(r["status"], True, C_DIS)
				screen.blit(id_s,  (row.x + 12,  row.centery - 8))
				screen.blit(hos_s, (row.x + 72,  row.centery - 8))
				screen.blit(sta_s, (row.right - 90, row.centery - 5))
		else:
			ns = fonts["small"].render("暂无公开房间", True, C_DARK_GRAY)
			screen.blit(ns, ns.get_rect(center=(cx, base_y + 210)))

		if error_msg:
			es = fonts["small"].render(f"⚠ {error_msg}", True, (220, 80, 60))
			screen.blit(es, es.get_rect(center=(cx, sh - 80)))

		hov_b = back_btn.collidepoint(mx, my)
		draw_btn(screen, fonts, back_btn, "← 返回", hov_b)
		pygame.display.flip()


def show_room_waiting(screen, fonts, clock, net: NetworkClient, room_info: dict, player_name: str):
	"""
	房间等待界面：显示房间代码、双方就绪状态、条件配置（房主可改）。
	返回 game_start dict 或 None（断线/返回）。
	"""
	sw, sh    = screen.get_size()
	cx        = sw // 2
	faction   = room_info.get("faction")
	room_id   = room_info.get("room_id", "????")
	is_host   = (faction == FACTION_RED)
	host_name = room_info.get("host_name", "?")
	guest_name= room_info.get("guest_name", "")
	is_ready  = {FACTION_RED: False, FACTION_DIS: False}
	conditions= set()
	error_msg = ""

	# 条件复选框
	COND_W, COND_H, COND_GAP = 480, 38, 6
	cond_base_y = sh // 2 - 20
	cond_rects  = [(cid,
		pygame.Rect(cx - COND_W // 2, cond_base_y + i * (COND_H + COND_GAP), COND_W, COND_H))
		for i, (cid, _, _) in enumerate(CONDITIONS_DEF)]

	ready_btn = pygame.Rect(cx - 120, sh - 90, 240, 46)

	while True:
		clock.tick(60)
		mx, my = pygame.mouse.get_pos()

		for msg in net.poll():
			t = msg.get("type")
			if t == "player_joined":
				guest_name = msg.get("guest_name", "")
			elif t == "player_ready":
				is_ready[msg.get("faction")] = True
			elif t == "player_unready":
				is_ready[msg.get("faction")] = False
			elif t == "conditions_updated":
				conditions = set(msg.get("conditions", []))
			elif t == "game_start":
				return msg
			elif t == "opponent_disconnected":
				error_msg = "对方已断开连接"
			elif t == "error":
				error_msg = msg.get("msg", "")

		for event in pygame.event.get():
			if event.type == pygame.QUIT:
				pygame.quit(); sys.exit(0)
			if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
				return None
			if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
				error_msg = ""
				if ready_btn.collidepoint(mx, my):
					my_ready = is_ready.get(faction, False)
					if my_ready:
						net.send({"type": "unready"})
						is_ready[faction] = False
					else:
						net.send({"type": "ready"})
						is_ready[faction] = True
				# 条件切换（仅房主）
				if is_host:
					for cid, r in cond_rects:
						if r.collidepoint(mx, my):
							if cid in conditions:
								conditions.discard(cid)
							else:
								conditions.add(cid)
							net.send({"type": "set_conditions",
								"conditions": list(conditions)})
							# 如果已就绪，切换条件后取消就绪
							if is_ready.get(FACTION_RED):
								net.send({"type": "unready"})
								is_ready[FACTION_RED] = False

		# ── 绘制 ──────────────────────────────
		screen.fill(C_BG_MENU)

		# 标题 + 房间代码
		title = fonts["title"].render("等待房间", True, C_GOLD)
		screen.blit(title, title.get_rect(center=(cx, 36)))
		code_s = fonts["bold"].render(f"房间代码：{room_id}", True, C_WHITE)
		screen.blit(code_s, code_s.get_rect(center=(cx, 68)))
		hint = fonts["tiny"].render("将房间代码发给好友，邀请对方加入", True, C_GRAY)
		screen.blit(hint, hint.get_rect(center=(cx, 88)))

		# 玩家状态
		py = 118
		for fname, pname, col in [
			(FACTION_RED, host_name,  C_RED),
			(FACTION_DIS, guest_name or "等待加入...", C_DIS),
		]:
			ready = is_ready.get(fname, False)
			you   = "(你)" if fname == faction else ""
			ns = fonts["bold"].render(f"{pname} {you}", True, col)
			ready_col  = C_DIS if ready else C_DARK_GRAY
			ready_text = "✓ 已就绪" if ready else "○ 未就绪"
			rs = fonts["small"].render(ready_text, True, ready_col)
			screen.blit(ns, (cx - 220, py))
			screen.blit(rs, (cx + 80,  py + 2))
			py += 32

		# 分隔线
		pygame.draw.line(screen, C_PANEL_BDR, (cx - 240, 188), (cx + 240, 188))

		# 开局条件
		cond_title = fonts["small"].render(
			"开局条件（房主可配置）" if is_host else "开局条件（仅房主可修改）",
			True, C_GOLD)
		screen.blit(cond_title, cond_title.get_rect(center=(cx, cond_base_y - 22)))

		for (cid, r), (_, name, desc) in zip(cond_rects, CONDITIONS_DEF):
			is_sel = cid in conditions
			can    = is_host
			hov    = r.collidepoint(mx, my) and can
			bg  = (50, 32, 10) if is_sel else ((28, 18, 8) if hov else (16, 10, 6))
			bdr = C_GOLD if is_sel else (C_RED if hov else C_PANEL_BDR)
			pygame.draw.rect(screen, bg, r, border_radius=5)
			pygame.draw.rect(screen, bdr, r, 1, border_radius=5)
			cb = pygame.Rect(r.x + 8, r.centery - 7, 14, 14)
			if is_sel:
				pygame.draw.rect(screen, C_GOLD, cb, border_radius=2)
			else:
				pygame.draw.rect(screen, C_GRAY, cb, 1, border_radius=2)
			ns = fonts["small"].render(name, True, C_GOLD if is_sel else C_WHITE)
			ds = fonts["tiny"].render(desc, True, (180, 160, 130) if is_sel else C_DARK_GRAY)
			screen.blit(ns, (r.x + 30, r.y + 3))
			screen.blit(ds, (r.x + 30 + ns.get_width() + 12, r.y + 5))

		# 就绪/取消按钮
		my_ready = is_ready.get(faction, False)
		hov_r = ready_btn.collidepoint(mx, my)
		draw_btn(screen, fonts, ready_btn,
			"取消就绪" if my_ready else "✓  准备就绪", hov_r, active=my_ready)

		waiting_str = "等待对方就绪..." if not all(is_ready.values()) else "双方已就绪，等待开局..."
		ws = fonts["tiny"].render(waiting_str, True, C_GRAY)
		screen.blit(ws, ws.get_rect(center=(cx, sh - 36)))

		if error_msg:
			es = fonts["small"].render(f"⚠ {error_msg}", True, (220, 80, 60))
			screen.blit(es, es.get_rect(center=(cx, sh - 58)))

		pygame.display.flip()


# ═══════════════════════════════════════════
# 联机游戏辅助：同步服务器状态到本地 GameState
# ═══════════════════════════════════════════

def _unit_from_server(su: dict, faction: str) -> Unit:
	name = su["name"]
	if name not in UNIT_TEMPLATES:
		name = "胚体"
	u = Unit(name, faction or su["faction"], su["x"], su["y"])
	u.uid     = su["uid"]
	u.hp      = su["hp"]
	u.max_hp  = su["max_hp"]
	u.kills   = su["kills"]
	u.dead    = su.get("dead", False)
	u.base_atk= su["atk"]
	u.base_spd= su["spd"]
	u.trait   = su["trait"]
	u.ranged  = su["ranged"]
	if su.get("pending_evo"):
		u._pending_evo = True
	if su.get("pending_evo3"):
		u._pending_evo3 = True
	return u


def apply_server_state(game: GameState, msg: dict):
	"""将服务端回合结果同步到本地 game 对象，供动画 + 渲染使用。"""
	server_map = {su["uid"]: su for su in msg["units"]}
	existing   = {u.uid: u for u in game.units}

	for uid, su in server_map.items():
		if uid in existing:
			u = existing[uid]
			u.x, u.y  = su["x"], su["y"]
			u.hp       = su["hp"]
			u.max_hp   = su["max_hp"]
			u.level    = su.get("level", u.level)
			u.kills    = su["kills"]
			u.dead     = su.get("dead", False)
			u.defending= su.get("defending", False)
			u.name     = su["name"]
			u.base_atk = su["atk"]
			u.base_spd = su["spd"]
			u.trait    = su["trait"]
			u.ranged   = su["ranged"]
			for attr in ("_pending_evo", "_pending_evo3"):
				if hasattr(u, attr):
					delattr(u, attr)
			if su.get("pending_evo"):
				u._pending_evo = True
			if su.get("pending_evo3"):
				u._pending_evo3 = True
		else:
			# 新生成的单位（长线战增援等）
			new_u = _unit_from_server(su, su["faction"])
			game.units.append(new_u)

	# 同步 base_states
	if "base_states" in msg:
		for key, bsd in msg["base_states"].items():
			x, y = map(int, key.split(","))
			if (x, y) in game.base_states:
				bs = game.base_states[(x, y)]
				bs.occupier     = bsd["occupier"]
				bs.occupy_count = bsd["occupy_count"]

	game.last_attack_events  = [tuple(e) for e in msg.get("attack_events", [])]
	game.last_attack_main_end= msg.get("attack_main_end", 0)
	game.winner    = msg.get("winner")
	game.win_reason= msg.get("win_reason", "")
	game.turn      = msg.get("turn", game.turn)
	game.heartbeat_event = msg.get("heartbeat", False)


def create_game_from_server(cfg: GameConfig, msg: dict) -> GameState:
	"""根据 game_start 消息重建本地 GameState（不调用 setup，使用服务器状态）。"""
	game = GameState(cfg)
	game.units = []
	for su in msg["units"]:
		u = _unit_from_server(su, su["faction"])
		game.units.append(u)
	if "base_states" in msg:
		for key, bsd in msg["base_states"].items():
			x, y = map(int, key.split(","))
			if (x, y) in game.base_states:
				bs = game.base_states[(x, y)]
				bs.occupier     = bsd["occupier"]
				bs.occupy_count = bsd["occupy_count"]
	game.turn = msg.get("turn", 1)
	return game


# ═══════════════════════════════════════════
# 联机游戏主循环
# ═══════════════════════════════════════════

def run_online_game(screen, fonts, clock,
					net: NetworkClient, faction: str,
					game: GameState, cfg: GameConfig,
					cond_str: str):
	"""
	联机对弈循环。
	faction：本机控制的阵营（FACTION_RED 或 FACTION_DIS）。
	game：已由服务器 game_start 消息初始化的 GameState。
	"""
	ui       = UIState(cfg.screen_w, cfg.screen_h)
	renderer = Renderer(screen, fonts)
	anim     = AnimationManager()

	# 红方视角：己方在地图下方（y=1 在底部），翻转棋盘
	cfg.view_flip = (faction == FACTION_RED)

	# 联机模式标记，供 UIState/renderer 知道只渲控制己方
	ui.online_mode    = True
	ui.online_faction = faction

	ui.show_phase_banner = True
	ui.banner_text = f"兵戮灾 · {cond_str}  |  你是 {'红骑士团' if faction == FACTION_RED else '灾兽群'}  · 点击开始"

	pre_snap      = {}
	submitted     = False    # 本回合是否已提交
	opp_submitted = False    # 对方是否已提交
	disconnect    = False

	# 进入规划阶段（仅本方可规划）
	for u in game.alive_units():
		u.clear_turn_state()
	ui.begin_turn(game, faction)

	running = True
	while running:
		dt = clock.tick(60) / 1000.0

		# ── 处理网络消息 ──────────────────────
		for msg in net.poll():
			t = msg.get("type")
			if t == "turn_result":
				apply_server_state(game, msg)
				anim.setup(pre_snap, game)
				ui.phase     = "animating"
				submitted    = False
				opp_submitted= False
			elif t == "opponent_submitted":
				opp_submitted = True
			elif t == "opponent_disconnected":
				disconnect = True
				ui.show_phase_banner = True
				ui.banner_text = "⚠ 对方已断开连接  |  本局结束"
				ui.phase = "game_over"
			elif t == "chat":
				# 简单聊天提示（TODO：全功能聊天框）
				who = "红" if msg.get("faction") == FACTION_RED else "灾"
				ui.show_phase_banner = True
				ui.banner_text = f"[{who}] {msg.get('msg', '')}"

		# ── Pygame 事件 ───────────────────────
		for event in pygame.event.get():
			if event.type == pygame.QUIT:
				running = False; continue

			# 联机模式：只有本方未提交时才响应规划操作
			if submitted:
				# 只允许翻阅日志 / 关闭横幅
				if event.type == pygame.MOUSEBUTTONDOWN:
					ui.show_phase_banner = False
				continue

			signal = ui.handle_event(event, game)

			if signal == "execute":
				# 收集本方规划并发送至服务器
				pre_snap = {u.uid: (u.x, u.y, u.hp) for u in game.alive_units()}
				plans = []
				for u in game.faction_units(faction):
					plan = {
						"uid":    u.uid,
						"dir":    list(u.planned_dir),
						"action": u.planned_action,
					}
					evo = getattr(u, "_evo_plan", None)
					if evo is not None:
						plan["evo_plan"] = evo
					plans.append(plan)
				net.send({"type": "submit_plan", "plans": plans})
				submitted = True
				ui.show_phase_banner = True
				ui.banner_text = "规划已提交，等待对方..."

			elif signal == "new_round":
				# result 阶段点击确认 → 进入下一回合规划
				for u in game.alive_units():
					u.clear_turn_state()
				ui.begin_turn(game, faction)

		# ── 动画更新 ──────────────────────────
		if ui.phase == "animating":
			done = anim.update(dt, game)
			if done:
				if game.winner:
					ui.phase = "game_over"
					wname = "红骑士团" if game.winner == FACTION_RED else "灾兽群"
					you   = "（你获胜！）" if game.winner == faction else "（对方获胜）"
					ui.show_phase_banner = True
					ui.banner_text = f"🏆 {wname} 获胜！{you}  {game.win_reason}  |  关闭窗口退出"
				elif game.heartbeat_event:
					ui.phase = "result"
					ui.show_phase_banner = True
					ui.banner_text = "💗 战争的心跳加重了 —— 点击继续"
					game.heartbeat_event = False
				else:
					ui.phase = "result"

		# ── 渲染 ─────────────────────────────
		# 在提交等待期间，叠加"等待对方"半透明遮罩
		renderer.draw(game, ui, anim if anim.is_playing else None)
		if submitted and ui.phase not in ("animating", "game_over"):
			_draw_waiting_overlay(screen, fonts, opp_submitted)
		pygame.display.flip()

	pygame.quit()
	sys.exit(0)


def _draw_waiting_overlay(screen, fonts, opp_submitted: bool):
	"""半透明等待提示遮罩。"""
	sw, sh  = screen.get_size()
	overlay = pygame.Surface((sw, 50), pygame.SRCALPHA)
	overlay.fill((0, 0, 0, 140))
	screen.blit(overlay, (0, sh // 2 - 25))
	dots = "." * (int(time.time() * 2) % 4)
	msg  = f"对方已提交，等待服务器结算{dots}" if opp_submitted else f"等待对方提交规划{dots}"
	ts   = fonts["bold"].render(msg, True, C_GOLD)
	screen.blit(ts, ts.get_rect(center=(sw // 2, sh // 2)))


# ═══════════════════════════════════════════
# 本地游戏主循环（原逻辑不变）
# ═══════════════════════════════════════════

def run_local_game(screen, fonts, clock, cfg: GameConfig):
	game     = GameState(cfg)
	game.setup()
	ui       = UIState(cfg.screen_w, cfg.screen_h)
	renderer = Renderer(screen, fonts)
	anim     = AnimationManager()

	cond_names = {"abundance":"丰饶","war_gift":"战争恩赐","tide":"潮水",
		"extreme_terrain":"极端地形","long_war":"长线战"}
	cond_str = "  |  ".join(cond_names[c] for c in cfg.conditions) if cfg.conditions else "标准对局"
	ui.show_phase_banner = True
	ui.banner_text = f"兵戮灾 · 红之纷争  {cond_str}  |  点击开始"

	running  = True
	pre_snap = {}

	while running:
		dt = clock.tick(60) / 1000.0

		for event in pygame.event.get():
			if event.type == pygame.QUIT:
				running = False; continue

			signal = ui.handle_event(event, game)

			if signal == "execute":
				pre_snap = {u.uid: (u.x, u.y, u.hp) for u in game.alive_units()}
				game.execute_turn()
				anim.setup(pre_snap, game)
				ui.phase = "animating"

			elif signal == "new_round":
				for u in game.alive_units():
					u.clear_turn_state()
				ui.begin_turn(game, FACTION_RED)

			elif signal == "begin_dis_turn":
				ui.begin_turn(game, FACTION_DIS)

		if ui.phase == "animating":
			done = anim.update(dt, game)
			if done:
				if game.winner:
					ui.phase = "game_over"
					wname = "红骑士团" if game.winner == FACTION_RED else "灾兽群"
					ui.show_phase_banner = True
					ui.banner_text = f"🏆 {wname} 获胜！  {game.win_reason}  |  关闭窗口退出"
				elif game.heartbeat_event:
					ui.phase = "result"
					ui.show_phase_banner = True
					ui.banner_text = "💗 战争的心跳加重了 —— 点击继续"
					game.heartbeat_event = False
				else:
					ui.phase = "result"

		renderer.draw(game, ui, anim if anim.is_playing else None)
		pygame.display.flip()

	pygame.quit()
	sys.exit(0)


# ═══════════════════════════════════════════
# 程序入口
# ═══════════════════════════════════════════

def main():
	pygame.init()
	cfg    = GameConfig("9x9")
	screen = pygame.display.set_mode((cfg.screen_w, cfg.screen_h))
	pygame.display.set_caption("兵戮灾 · 红之纷争  v2.0")
	clock  = pygame.time.Clock()
	fonts  = load_fonts()

	mode = show_mode_select(screen, fonts, clock)

	if mode == "local":
		cfg.conditions = show_condition_select(screen, fonts, clock)
		run_local_game(screen, fonts, clock, cfg)

	else:  # online
		while True:
			setup = show_online_setup(screen, fonts, clock)
			if setup is None:
				# 返回模式选择
				mode = show_mode_select(screen, fonts, clock)
				if mode == "local":
					cfg.conditions = show_condition_select(screen, fonts, clock)
					run_local_game(screen, fonts, clock, cfg)
					return
				continue

			player_name, server_url = setup

			net = NetworkClient()
			net.connect(server_url)
			ok = show_connecting(screen, fonts, clock, net, server_url)
			if not ok:
				continue

			room_info = show_online_lobby(screen, fonts, clock, net, player_name)
			if room_info is None:
				continue

			start_msg = show_room_waiting(screen, fonts, clock, net, room_info, player_name)
			if start_msg is None:
				continue

			# 用服务器给的状态重建本地游戏
			conditions = set(start_msg.get("conditions", []))
			cfg.conditions = conditions
			game = create_game_from_server(cfg, start_msg)

			faction  = room_info.get("faction")
			cond_str = start_msg.get("cond_str", "标准对局")

			run_online_game(screen, fonts, clock, net, faction, game, cfg, cond_str)
			return


if __name__ == "__main__":
	main()
