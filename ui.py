# 血轨：UI 状态管理 v2
# 进化选择改为棋子旁悬浮面板（3选项），去掉中央弹窗

import pygame
from constants import *

EVO_TABLE = {
	(FACTION_RED, "铁卫"):   [
		{"name": "盾卫",   "desc": "铁壁：不动时相邻友方减伤1（光环）"},
		{"name": "弩卫",   "desc": "劲弩：射程2，移动后不可远攻"},
	],
	(FACTION_DIS, "散兽"):   [
		{"name": "甲兽",   "desc": "硬壳：常驻减伤1"},
		{"name": "炮兽",   "desc": "投射：射程2，移动后不可远攻"},
	],
	(FACTION_RED, "盾卫"):   [
		{"name": "盾卫3A", "desc": "路线A：保守，攻击+1"},
		{"name": "旗卫",   "desc": "路线B：战旗，距离2内友方攻+1，自身攻速+1"},
	],
	(FACTION_RED, "弩卫"):   [
		{"name": "弩卫3A", "desc": "路线A：劲弩，攻击+1"},
		{"name": "战车",   "desc": "路线B：冲阵，直线5格冲锋，撞敌停止造成伤害"},
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
EVO_BTN_H = 30
EVO_POPUP_W = 200


class UIState:
	def __init__(self, sw: int, sh: int):
		self.sw = sw
		self.sh = sh
		self.phase = "p1_plan"

		# 选中 & 拖拽
		self.selected_uid: int  = None
		self.dragging_uid: int  = None
		self.drag_pos: tuple    = None
		self.hover_cell: tuple  = None

		# 移动范围与选定目标
		self.move_hints: set       = set()
		self.selected_move_cell    = None
		self.attack_hints: set     = set()

		# 行动按钮（位于左侧面板）
		self.act_btn_rects: list   = []

		# 进化（悬浮面板，无中央弹窗）
		self.evo_uid               = None
		self.evo_options           = []   # [{"name","desc"}, ...]，最多2个，第3个是"不进化"
		self.evo_hover             = -1
		self.evo_btn_rects: list   = []   # [(idx, Rect)]，idx=0/1=进化路线，idx=2=不进化
		self.pending_evo_uids: list = []

		# 阶段横幅
		self.show_phase_banner = False
		self.banner_text       = ""

		# 确认按钮
		bw, bh = 130, 38
		self.confirm_btn_rect = pygame.Rect(sw - bw - 14, sh - bh - 8, bw, bh)

	# ──────────────── 主事件入口 ──────────────────

	def handle_event(self, event, game):
		# 进化悬浮面板优先处理
		if self.evo_uid is not None:
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

		if self.confirm_btn_rect.collidepoint(mx, my):
			return self._on_confirm(game)

		for act, label, rect in self.act_btn_rects:
			if rect.collidepoint(mx, my):
				u = game.get_unit_by_uid(self.selected_uid)
				if u:
					self._set_action(act, u, game)
				return None

		cell = game.cfg.screen_to_cell(mx, my)
		if cell:
			cx, cy = cell
			self._try_start_drag(cx, cy, pos, game)

		return None

	# ──────────────── 鼠标释放 ───────────────────

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
		self.dragging_uid = None
		self.drag_pos     = None
		return None

	# ──────────────── 开始拖拽 ────────────────────

	def _try_start_drag(self, cx, cy, screen_pos, game):
		faction = FACTION_RED if self.phase == "p1_plan" else FACTION_DIS
		units   = [u for u in game.units_at(cx, cy) if u.faction == faction]
		if not units:
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
		if u.planned_dir != DIR_NONE:
			self.selected_move_cell = (u.x + u.planned_dir[0], u.y + u.planned_dir[1])
		else:
			self.selected_move_cell = None

	# ──────────────── 移动范围 ───────────────────

	def _populate_hints(self, u, game):
		self.move_hints.clear()
		self.attack_hints.clear()
		cfg = game.cfg
		gs  = cfg.grid_size
		spd = game.effective_spd(u)
		if u.planned_action != ACT_DEFEND:
			if u.has_trait("冲阵"):
				for ddx, ddy in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
					for step in range(1, spd + 1):
						nx, ny = u.x + ddx * step, u.y + ddy * step
						if not (0 <= nx < gs and 0 <= ny < gs):
							break
						self.move_hints.add((nx, ny))
			else:
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

	# ──────────────── 行动按钮 ───────────────────

	def _build_act_buttons(self, u, game):
		self.act_btn_rects.clear()
		cfg    = game.cfg
		px, pw = 8, cfg.board_offset_x - 16
		total_h = cfg.grid_size * cfg.cell_size
		n_btns  = 2
		if cfg.is_base(u.x, u.y) and not u.is_embryo:
			n_btns += 1
		if u.level >= 2 and not u.made_unit and not u.is_embryo and getattr(u, "can_make", True):
			n_btns += 1
		start_y = cfg.board_offset_y + total_h - (n_btns * (ACT_BTN_H + 5)) - 6
		actions = [(ACT_NONE, "⚔ 自动攻击"), (ACT_DEFEND, "🛡 防御")]
		if cfg.is_base(u.x, u.y) and not u.is_embryo:
			actions.append((ACT_OCCUPY, "🚩 占领"))
		if u.level >= 2 and not u.made_unit and not u.is_embryo and getattr(u, "can_make", True):
			actions.append((ACT_MAKE, "🐣 制造"))
		for i, (act, label) in enumerate(actions):
			r = pygame.Rect(px, start_y + i * (ACT_BTN_H + 5), pw, ACT_BTN_H)
			self.act_btn_rects.append((act, label, r))

	def _set_action(self, act, u, game):
		u.planned_action = act
		if act == ACT_DEFEND:
			u.planned_dir       = DIR_NONE
			self.selected_move_cell = None
			self.move_hints.clear()
		game.log.append(
			f"{'⚔' if act==ACT_NONE else '🛡' if act==ACT_DEFEND else '🚩' if act==ACT_OCCUPY else '🐣'}"
			f" {u.name} 行动：{act}"
		)

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
				self._open_evo_popup(game)
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

	# ──────────────── 进化悬浮面板 ──────────────────

	def queue_evolutions(self, game):
		self.pending_evo_uids = []
		for u in game.alive_units():
			if hasattr(u, "_pending_evo") or hasattr(u, "_pending_evo3"):
				self.pending_evo_uids.append(u.uid)
		if self.pending_evo_uids:
			self._open_evo_popup(game)

	def _open_evo_popup(self, game):
		if not self.pending_evo_uids:
			return
		uid  = self.pending_evo_uids[0]
		u    = game.get_unit_by_uid(uid)
		opts = EVO_TABLE.get((u.faction, u.name), []) if u else []
		if not opts:
			# 无进化表项：直接跳过（仅补满血）
			game.skip_evolution(uid)
			self.pending_evo_uids.pop(0)
			if self.pending_evo_uids:
				self._open_evo_popup(game)
			return
		self.evo_uid     = uid
		self.evo_options = opts
		self.evo_hover   = -1
		self._rebuild_evo_rects(game)

	def _rebuild_evo_rects(self, game):
		"""计算进化面板按钮位置（棋子附近）"""
		self.evo_btn_rects.clear()
		if self.evo_uid is None:
			return
		u   = game.get_unit_by_uid(self.evo_uid)
		if not u:
			return
		cfg = game.cfg
		cs  = cfg.cell_size
		# 棋子中心屏幕坐标
		scx = cfg.board_offset_x + u.x * cs + cs // 2
		scy = cfg.board_offset_y + u.y * cs + cs // 2

		n_btns = len(self.evo_options) + 1  # 路线 + 不进化
		popup_h = n_btns * (EVO_BTN_H + 4) + 36
		popup_w = EVO_POPUP_W

		# 决定面板出现在棋子的哪一侧
		if scx + cs // 2 + popup_w + 8 <= cfg.screen_w - cfg.panel_width:
			px = scx + cs // 2 + 8
		else:
			px = scx - cs // 2 - popup_w - 8

		if scy + popup_h // 2 + 4 <= cfg.board_offset_y + cfg.grid_size * cs:
			py = max(cfg.board_offset_y + 4, scy - popup_h // 2)
		else:
			py = cfg.board_offset_y + cfg.grid_size * cs - popup_h - 4

		# 路线按钮
		for i, opt in enumerate(self.evo_options):
			r = pygame.Rect(px + 4, py + 32 + i * (EVO_BTN_H + 4), popup_w - 8, EVO_BTN_H)
			self.evo_btn_rects.append((i, r))
		# 不进化按钮
		skip_i = len(self.evo_options)
		r = pygame.Rect(px + 4,
			py + 32 + skip_i * (EVO_BTN_H + 4),
			popup_w - 8, EVO_BTN_H)
		self.evo_btn_rects.append((2, r))   # idx=2 固定为"不进化"

		# 存储面板左上角（渲染器用）
		self.evo_popup_rect = pygame.Rect(px, py, popup_w, popup_h)

	def _handle_evo_event(self, event, game):
		if event.type == pygame.MOUSEMOTION:
			mx, my = event.pos
			self.evo_hover = -1
			for idx, r in self.evo_btn_rects:
				if r.collidepoint(mx, my):
					self.evo_hover = idx
		if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
			mx, my = event.pos
			for idx, r in self.evo_btn_rects:
				if r.collidepoint(mx, my):
					self._apply_evo(idx, game)
					return None
		return None

	def _apply_evo(self, idx, game):
		uid = self.evo_uid
		if idx == 2:
			game.skip_evolution(uid)
		else:
			opt = self.evo_options[idx]
			game.evolve_unit(uid, opt["name"])
		self.evo_uid = None
		self.evo_btn_rects.clear()
		self.pending_evo_uids.pop(0)
		if self.pending_evo_uids:
			self._open_evo_popup(game)

	def current_faction(self):
		return FACTION_RED if self.phase in ("p1_plan", "p1_done") else FACTION_DIS
