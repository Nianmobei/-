# 血轨：UI 状态管理
# 操作：拖拽棋子到目标格（菱形移动范围）
# 行动按钮：在左侧面板，不浮在棋盘上

import pygame
from constants import *

EVO_TABLE = {
	(FACTION_RED, "铁卫"):   [
		{"name": "盾卫",   "desc": "铁壁：不动时反击近战"},
		{"name": "弩卫",   "desc": "劲弩：射程2，移动后不可远攻"},
	],
	(FACTION_DIS, "散兽"):   [
		{"name": "甲兽",   "desc": "硬壳：常驻减伤1"},
		{"name": "炮兽",   "desc": "投射：射程2，移动后不可远攻"},
	],
	(FACTION_RED, "盾卫"):   [
		{"name": "盾卫3A", "desc": "路线A：保守，攻击+1"},
		{"name": "旗卫",   "desc": "路线B：战旗，相邻友方攻击+1"},
	],
	(FACTION_RED, "弩卫"):   [
		{"name": "弩卫3A", "desc": "路线A：保守，攻击+1"},
		{"name": "连弩",   "desc": "路线B：齐射，相邻友方时伤害+1"},
	],
	(FACTION_DIS, "甲兽"):   [
		{"name": "甲兽3A", "desc": "路线A：保守，攻击+1"},
		{"name": "恐兽",   "desc": "路线B：威压，攻击后目标无法移动"},
	],
	(FACTION_DIS, "炮兽"):   [
		{"name": "炮兽3A", "desc": "路线A：保守，攻击+1"},
		{"name": "猎群兽", "desc": "路线B：集群，攻击溅射相邻1点"},
	],
}

ACT_BTN_H = 28


class UIState:
	def __init__(self, sw: int, sh: int):
		self.sw = sw
		self.sh = sh
		self.phase = "p1_plan"

		# 选中 & 拖拽
		self.selected_uid: int  = None
		self.dragging_uid: int  = None
		self.drag_pos: tuple    = None   # 鼠标屏幕坐标（拖动中）
		self.hover_cell: tuple  = None   # 鼠标悬停格

		# 移动范围与选定目标
		self.move_hints: set       = set()  # 菱形范围内可到达的格
		self.selected_move_cell    = None   # (cx,cy) 已规划目的地
		self.attack_hints: set     = set()  # 攻击范围预览

		# 行动按钮（位于左侧面板）
		self.act_btn_rects: list   = []     # [(act, label, Rect)]

		# 进化
		self.show_evo_dialog       = False
		self.evo_uid               = None
		self.evo_options           = []
		self.evo_hover             = -1
		self.pending_evo_uids: list = []

		# 阶段横幅
		self.show_phase_banner = False
		self.banner_text       = ""

		# 确认按钮
		bw, bh = 130, 38
		self.confirm_btn_rect = pygame.Rect(sw - bw - 14, sh - bh - 8, bw, bh)

	# ──────────────── 主事件入口 ──────────────────

	def handle_event(self, event, game):
		if self.show_evo_dialog:
			return self._handle_evo_event(event, game)

		if self.show_phase_banner:
			if event.type in (pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN):
				self.show_phase_banner = False
				if self.phase == "p1_done":
					self.phase = "p2_plan"
			return None

		if self.phase in ("game_over", "animating"):
			return None

		if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
			return self._handle_mousedown(event.pos, game)

		if event.type == pygame.MOUSEMOTION:
			mx, my = event.pos
			self.hover_cell = game.cfg.screen_to_cell(mx, my)
			if self.dragging_uid is not None:
				self.drag_pos = event.pos
			return None

		if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
			return self._handle_mouseup(event.pos, game)

		if event.type == pygame.KEYDOWN:
			if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
				return self._on_confirm(game)

		return None

	# ──────────────── 鼠标按下 ────────────────────

	def _handle_mousedown(self, pos, game):
		mx, my = pos

		# 确认按钮
		if self.confirm_btn_rect.collidepoint(mx, my):
			return self._on_confirm(game)

		# 行动按钮（左侧面板）
		for act, label, rect in self.act_btn_rects:
			if rect.collidepoint(mx, my):
				u = game.get_unit_by_uid(self.selected_uid)
				if u:
					self._set_action(act, u, game)
				return None

		# 棋盘区域
		cell = game.cfg.screen_to_cell(mx, my)
		if cell:
			cx, cy = cell
			self._try_start_drag(cx, cy, pos, game)

		return None

	# ──────────────── 鼠标释放（完成拖拽） ───────────

	def _handle_mouseup(self, pos, game):
		if self.dragging_uid is None:
			return None

		mx, my = pos
		u = game.get_unit_by_uid(self.dragging_uid)
		cell = game.cfg.screen_to_cell(mx, my)

		if u and cell:
			cx, cy = cell
			if (cx, cy) in self.move_hints:
				u.planned_dir = (cx - u.x, cy - u.y)
				self.selected_move_cell = (cx, cy)
				game.log.append(f"📍 {u.name} 计划移动→({cx},{cy})")
			elif (cx, cy) == (u.x, u.y):
				u.planned_dir = DIR_NONE
				self.selected_move_cell = None
				game.log.append(f"📍 {u.name} 原地不动")
			# 释放在非法格：保持当前规划不变

		# 清除拖拽状态（保留选中）
		self.dragging_uid = None
		self.drag_pos     = None
		return None

	# ──────────────── 开始拖拽 ────────────────────

	def _try_start_drag(self, cx, cy, screen_pos, game):
		faction = FACTION_RED if self.phase == "p1_plan" else FACTION_DIS
		units   = [u for u in game.units_at(cx, cy) if u.faction == faction]
		if not units:
			# 点击非己方格 → 取消选中
			self.selected_uid = None
			self.dragging_uid = None
			self.move_hints.clear()
			self.attack_hints.clear()
			self.act_btn_rects.clear()
			self.selected_move_cell = None
			return
		u = units[0]
		self.selected_uid = u.uid
		self.dragging_uid = u.uid
		self.drag_pos     = screen_pos
		self._populate_hints(u, game)
		self._build_act_buttons(u, game)
		# 同步已规划的目的地
		if u.planned_dir != DIR_NONE:
			self.selected_move_cell = (u.x + u.planned_dir[0], u.y + u.planned_dir[1])
		else:
			self.selected_move_cell = None

	# ──────────────── 移动范围（菱形） ───────────────

	def _populate_hints(self, u, game):
		self.move_hints.clear()
		self.attack_hints.clear()
		cfg = game.cfg
		gs  = cfg.grid_size
		spd = game.effective_spd(u)

		if u.planned_action != ACT_DEFEND:
			for dx in range(-spd, spd + 1):
				for dy in range(-spd, spd + 1):
					if abs(dx) + abs(dy) <= spd and (dx, dy) != (0, 0):
						nx, ny = u.x + dx, u.y + dy
						if 0 <= nx < gs and 0 <= ny < gs:
							self.move_hints.add((nx, ny))

		rng = u.attack_range()
		for ax in range(gs):
			for ay in range(gs):
				d = abs(ax - u.x) + abs(ay - u.y)
				if 1 <= d <= rng:
					self.attack_hints.add((ax, ay))

	# ──────────────── 行动按钮（左侧面板） ───────────

	def _build_act_buttons(self, u, game):
		self.act_btn_rects.clear()
		cfg   = game.cfg
		px    = 8
		pw    = cfg.board_offset_x - 16
		bw    = pw
		# 按钮起始 Y：面板底部向上留空
		total_h = cfg.grid_size * cfg.cell_size
		n_btns  = 2
		if cfg.is_base(u.x, u.y) and not u.is_embryo:
			n_btns += 1
		if u.level >= 2 and not u.made_unit and not u.is_embryo:
			n_btns += 1
		start_y = cfg.board_offset_y + total_h - (n_btns * (ACT_BTN_H + 5)) - 6

		actions = [(ACT_NONE, "⚔ 自动攻击"), (ACT_DEFEND, "🛡 防御")]
		if cfg.is_base(u.x, u.y) and not u.is_embryo:
			actions.append((ACT_OCCUPY, "🚩 占领"))
		if u.level >= 2 and not u.made_unit and not u.is_embryo:
			actions.append((ACT_MAKE, "🐣 制造"))

		for i, (act, label) in enumerate(actions):
			r = pygame.Rect(px, start_y + i * (ACT_BTN_H + 5), bw, ACT_BTN_H)
			self.act_btn_rects.append((act, label, r))

	def _set_action(self, act, u, game):
		u.planned_action = act
		if act == ACT_DEFEND:
			u.planned_dir       = DIR_NONE
			self.selected_move_cell = None
			self.move_hints.clear()
		game.log.append(f"{'⚔' if act==ACT_NONE else '🛡' if act==ACT_DEFEND else '🚩' if act==ACT_OCCUPY else '🐣'} {u.name} 行动：{act}")

	# ──────────────── 阶段推进 ────────────────────

	def _on_confirm(self, game):
		self._clear_drag()
		if self.phase == "p1_plan":
			self.phase = "p1_done"
			self.show_phase_banner = True
			self.banner_text = "红方规划完成 —— 请灾方接手，点击任意处继续"
			return None
		elif self.phase == "p2_plan":
			self.phase = "p2_done"
			return "execute"
		elif self.phase in ("p2_done", "result"):
			if self.pending_evo_uids:
				self._open_evo_dialog(game)
				return None
			return "new_round"
		return None

	def _clear_drag(self):
		self.selected_uid = None
		self.dragging_uid = None
		self.drag_pos     = None
		self.move_hints.clear()
		self.attack_hints.clear()
		self.act_btn_rects.clear()
		self.selected_move_cell = None

	# ──────────────── 进化对话框 ──────────────────

	def queue_evolutions(self, game):
		self.pending_evo_uids = []
		for u in game.alive_units():
			if hasattr(u, "_pending_evo") or hasattr(u, "_pending_evo3"):
				self.pending_evo_uids.append(u.uid)
		if self.pending_evo_uids:
			self._open_evo_dialog(game)

	def _open_evo_dialog(self, game):
		if not self.pending_evo_uids:
			return
		uid  = self.pending_evo_uids[0]
		u    = game.get_unit_by_uid(uid)
		opts = EVO_TABLE.get((u.faction, u.name), []) if u else []
		if not opts:
			self.pending_evo_uids.pop(0)
			return
		self.show_evo_dialog = True
		self.evo_uid         = uid
		self.evo_options     = opts
		self.evo_hover       = 0

	def _handle_evo_event(self, event, game):
		n   = len(self.evo_options)
		dw  = 520
		dh  = 60 + n * 84 + 28
		dx  = (self.sw - dw) // 2
		dy  = (self.sh - dh) // 2
		if event.type == pygame.MOUSEMOTION:
			mx, my = event.pos
			for i in range(n):
				if pygame.Rect(dx+24, dy+56+i*84, dw-48, 72).collidepoint(mx, my):
					self.evo_hover = i
		if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
			mx, my = event.pos
			for i, opt in enumerate(self.evo_options):
				if pygame.Rect(dx+24, dy+56+i*84, dw-48, 72).collidepoint(mx, my):
					game.evolve_unit(self.evo_uid, opt["name"])
					self.show_evo_dialog = False
					self.pending_evo_uids.pop(0)
					if self.pending_evo_uids:
						self._open_evo_dialog(game)
					return None
		return None

	def current_faction(self):
		return FACTION_RED if self.phase in ("p1_plan", "p1_done") else FACTION_DIS
