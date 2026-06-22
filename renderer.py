# 血轨：渲染器（动画 + 拖拽预览 + 规划指示）

import pygame
import math
from constants import *
from animator import AnimPhase


def _lerp_color(c1, c2, t):
	return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))


class Renderer:
	def __init__(self, screen: pygame.Surface, fonts: dict):
		self.screen = screen
		self.fonts  = fonts

	# ──────────────────── 主入口 ─────────────────────

	def draw(self, game, ui, anim=None):
		self.screen.fill(C_BG)
		self._draw_board(game, ui, anim)
		self._draw_plan_overlays(game, ui)        # 规划指示层
		self._draw_drag_piece(game, ui)           # 拖拽中的棋子
		self._draw_left_panel(game, ui)
		self._draw_right_panel(game, ui)
		self._draw_bottom_bar(game, ui)
		if anim and anim.is_playing:
			self._draw_damage_tags(game, ui, anim)
		if ui.show_evo_dialog:
			self._draw_evo_dialog(game, ui)
		if ui.show_phase_banner:
			self._draw_phase_banner(game, ui)

	# ──────────────────── 棋盘格 ─────────────────────

	def _draw_board(self, game, ui, anim):
		cfg   = game.cfg
		cs    = cfg.cell_size
		ox    = cfg.board_offset_x
		oy    = cfg.board_offset_y
		gs    = cfg.grid_size

		for cy in range(gs):
			for cx in range(gs):
				rx = ox + cx * cs
				ry = oy + cy * cs
				rect = pygame.Rect(rx, ry, cs, cs)

				# 底色
				terrain = cfg.terrain_at(cx, cy)
				if cfg.is_base(cx, cy):
					color = cfg.base_color(cfg.base_owner(cx, cy))
				elif terrain == "trench":
					color = C_TERRAIN_TRENCH
				elif terrain == "high":
					color = C_TERRAIN_HIGH
				elif (cx + cy) % 2 == 0:
					color = C_CELL
				else:
					color = C_CELL_ALT
				pygame.draw.rect(self.screen, color, rect)

				# 移动范围高亮
				if (cx, cy) in ui.move_hints:
					s = pygame.Surface((cs, cs), pygame.SRCALPHA)
					alpha = 55 if (cx, cy) != ui.hover_cell else 90
					s.fill((*C_MOVE_HINT, alpha))
					self.screen.blit(s, (rx, ry))

				# 选定目标格
				if ui.selected_move_cell and (cx, cy) == ui.selected_move_cell:
					s = pygame.Surface((cs, cs), pygame.SRCALPHA)
					s.fill((*C_MOVE_SEL, 80))
					self.screen.blit(s, (rx, ry))

				# 攻击范围（选中后轻微红色）
				if (cx, cy) in ui.attack_hints and (cx, cy) not in ui.move_hints:
					s = pygame.Surface((cs, cs), pygame.SRCALPHA)
					s.fill((*C_ATK_HINT, 25))
					self.screen.blit(s, (rx, ry))

				pygame.draw.rect(self.screen, C_GRID, rect, 1)

				# 本阵标签
				if cfg.is_base(cx, cy):
					owner = cfg.base_owner(cx, cy)
					lbl   = "红阵" if owner == FACTION_RED else ("灾阵" if owner == FACTION_DIS else "本阵")
					col   = C_RED   if owner == FACTION_RED else (C_DIS   if owner == FACTION_DIS else C_GOLD)
					fkey  = "small" if cs >= 80 else "tiny"
					self._text(rx + cs // 2, ry + cs - 12, lbl, self.fonts[fkey], col, center=True)
					bs = game.base_states.get((cx, cy))
					if bs and bs.occupier:
						fc  = C_OCCUPY_RED if bs.occupier == FACTION_RED else C_OCCUPY_DIS
						tag = ("红" if bs.occupier == FACTION_RED else "灾") + f"·{bs.occupy_count}/2"
						self._text(rx + cs // 2, ry + 8, tag, self.fonts["tiny"], fc, center=True)

				# 地形标签
				if terrain == "trench":
					self._text(rx + 3, ry + cs - 12, "壕", self.fonts["tiny"], (140, 170, 220))
				elif terrain == "high":
					self._text(rx + 3, ry + cs - 12, "高", self.fonts["tiny"], (220, 190, 80))

				# 棋子
				self._draw_units_in_cell(game.units_at(cx, cy), rx, ry, game, ui, anim, cs)

	def _draw_units_in_cell(self, units, rx, ry, game, ui, anim, cs):
		if not units:
			return
		n = len(units)
		for i, u in enumerate(units):
			# 拖拽中的棋子不在原格绘制（改为跟随鼠标）
			if u.uid == ui.dragging_uid:
				# 画一个半透明轮廓表示原始位置
				scx = rx + cs // 2
				scy = ry + cs // 2 - 5
				r   = max(8, int(18 * cs / 110))
				ghost = pygame.Surface((r*2+4, r*2+4), pygame.SRCALPHA)
				pygame.draw.circle(ghost, (*C_GHOST, 60), (r+2, r+2), r)
				pygame.draw.circle(ghost, (*C_WHITE, 80), (r+2, r+2), r, 2)
				self.screen.blit(ghost, (scx - r - 2, scy - r - 2))
				continue

			# 动画视觉位置
			if anim and anim.is_playing:
				vgx, vgy = anim.get_vpos(u.uid, u.x, u.y)
				scx = int(game.cfg.board_offset_x + vgx * cs + cs // 2)
				scy = int(game.cfg.board_offset_y + vgy * cs + cs // 2) - 5
			else:
				ox2 = (i - (n - 1) / 2) * (cs // max(n + 1, 2))
				scx = rx + cs // 2 + int(ox2)
				scy = ry + cs // 2 - 5

			self._draw_single_unit(u, scx, scy, game, ui, anim, cs)

			# HP 条
			bar_w = cs - 14
			bar_x = rx + 7
			bar_y = ry + cs - 9 - i * 7
			hp_r  = u.hp / max(u.max_hp, 1)
			pygame.draw.rect(self.screen, C_DARK_GRAY, (bar_x, bar_y, bar_w, 4))
			pygame.draw.rect(self.screen, C_HP_GREEN if hp_r > 0.4 else C_HP_RED,
				(bar_x, bar_y, int(bar_w * hp_r), 4))

	def _draw_single_unit(self, u, scx, scy, game, ui, anim, cs):
		scale  = cs / 110
		radius = max(8, int((24 if u.level >= 3 else (20 if u.level == 2 else 16)) * scale))

		selected = (u.uid == ui.selected_uid)
		if u.is_embryo:
			color = C_EMBYO
		elif u.faction == FACTION_RED:
			color = C_RED_LITE if selected else C_RED
		else:
			color = C_DIS_LITE if selected else C_DIS

		# 死亡淡出
		dead_a = anim.dead_alpha(u.uid) if anim else (0 if u.dead else 255)
		if dead_a == 0:
			return

		# 受击闪白
		flash = anim.hit_brightness(u.uid) if anim else 0.0
		if flash > 0:
			color = _lerp_color(color, (255, 255, 255), flash)

		if selected:
			pygame.draw.circle(self.screen, C_SEL, (scx, scy), radius + 5, 3)

		surf = pygame.Surface((radius * 2 + 2, radius * 2 + 2), pygame.SRCALPHA)
		pygame.draw.circle(surf, (*color, dead_a), (radius + 1, radius + 1), radius)
		pygame.draw.circle(surf, (*C_WHITE, dead_a), (radius + 1, radius + 1), radius, 2)
		self.screen.blit(surf, (scx - radius - 1, scy - radius - 1))

		# 兵种名
		fkey = "unit" if cs >= 80 else "tiny"
		self._text(scx, scy - 4, u.name[:2], self.fonts[fkey], C_WHITE, center=True)

		# 等级点
		for lv in range(u.level):
			pygame.draw.circle(self.screen, C_GOLD,
				(scx - (u.level - 1) * 4 + lv * 8, scy + radius - 4), 2)

		# 行动图标
		icon = {ACT_DEFEND: "🛡", ACT_OCCUPY: "🚩", ACT_MAKE: "🐣"}.get(u.planned_action)
		if icon:
			self._text(scx + radius, scy - radius, icon, self.fonts["tiny"], C_GOLD)

	# ──────────────────── 规划覆盖层 ─────────────────

	def _draw_plan_overlays(self, game, ui):
		"""规划阶段：所有单位的移动/攻击预览指示（结算前保留）"""
		if ui.phase not in ("p1_plan", "p2_plan", "p1_done"):
			return
		cfg = game.cfg

		for u in game.alive_units():
			if u.is_embryo:
				continue
			if u.uid == ui.dragging_uid:
				continue  # 正在拖拽时跳过
			ux, uy = cfg.cell_center(u.x, u.y)

			# ── 移动预览：半透明箭头线 ──────────────
			if u.planned_dir != DIR_NONE:
				dx, dy = u.planned_dir
				tx, ty = cfg.cell_center(u.x + dx, u.y + dy)
				# 虚线
				self._draw_dashed_line(ux, uy - 5, tx, ty - 5, C_MOVE_SEL, 80)
				# 目的地幽灵
				radius = max(6, int(14 * cfg.cell_size / 110))
				gs = pygame.Surface((radius * 2 + 2, radius * 2 + 2), pygame.SRCALPHA)
				fc = C_RED if u.faction == FACTION_RED else C_DIS
				pygame.draw.circle(gs, (*fc, 70), (radius + 1, radius + 1), radius)
				pygame.draw.circle(gs, (*C_WHITE, 100), (radius + 1, radius + 1), radius, 1)
				self.screen.blit(gs, (tx - radius - 1, ty - radius - 6))

			# ── 攻击预览：自动攻击目标红虚线 ──────────
			t = game.predict_attack_target(u)
			if t:
				tx, ty = cfg.cell_center(t.x, t.y)
				self._draw_dashed_line(ux, uy - 5, tx, ty - 5, C_ATK_PREV, 60, dash=4)

	def _draw_dashed_line(self, x1, y1, x2, y2, color, alpha, dash=6):
		"""绘制虚线"""
		import math
		dx, dy = x2 - x1, y2 - y1
		length = math.hypot(dx, dy)
		if length == 0:
			return
		steps = int(length / (dash * 2))
		for i in range(steps):
			t0 = i * dash * 2 / length
			t1 = (i * dash * 2 + dash) / length
			t1 = min(t1, 1.0)
			ax, ay = int(x1 + dx * t0), int(y1 + dy * t0)
			bx, by = int(x1 + dx * t1), int(y1 + dy * t1)
			s = pygame.Surface((abs(bx - ax) + 2, abs(by - ay) + 2), pygame.SRCALPHA)
			pygame.draw.line(s, (*color, alpha), (0, 0), (abs(bx - ax), abs(by - ay)), 2)
			self.screen.blit(s, (min(ax, bx), min(ay, by)))

	# ──────────────────── 拖拽棋子 ───────────────────

	def _draw_drag_piece(self, game, ui):
		if ui.dragging_uid is None or ui.drag_pos is None:
			return
		u = game.get_unit_by_uid(ui.dragging_uid)
		if not u:
			return
		mx, my = ui.drag_pos
		cfg    = game.cfg
		cs     = cfg.cell_size
		scale  = cs / 110
		radius = max(8, int((24 if u.level >= 3 else (20 if u.level == 2 else 16)) * scale))
		color  = C_RED_LITE if u.faction == FACTION_RED else C_DIS_LITE

		# 投影（简单阴影）
		shadow = pygame.Surface((radius * 2 + 8, radius * 2 + 8), pygame.SRCALPHA)
		pygame.draw.circle(shadow, (0, 0, 0, 70), (radius + 4, radius + 8), radius)
		self.screen.blit(shadow, (mx - radius - 4, my - radius - 4 + 6))

		# 棋子主体
		surf = pygame.Surface((radius * 2 + 2, radius * 2 + 2), pygame.SRCALPHA)
		pygame.draw.circle(surf, (*color, 230), (radius + 1, radius + 1), radius)
		pygame.draw.circle(surf, (*C_WHITE, 230), (radius + 1, radius + 1), radius, 2)
		self.screen.blit(surf, (mx - radius - 1, my - radius - 1))
		self._text(mx, my - 2, u.name[:2], self.fonts["unit"], C_WHITE, center=True)

		# 目标格高亮
		cell = game.cfg.screen_to_cell(mx, my)
		if cell and cell in ui.move_hints:
			cx, cy = cell
			rx = cfg.board_offset_x + cx * cs
			ry = cfg.board_offset_y + cy * cs
			hl = pygame.Surface((cs, cs), pygame.SRCALPHA)
			hl.fill((*C_MOVE_SEL, 100))
			self.screen.blit(hl, (rx, ry))
			pygame.draw.rect(self.screen, C_MOVE_SEL,
				pygame.Rect(rx, ry, cs, cs), 2)

	# ──────────────────── 伤害数字 ───────────────────

	def _draw_damage_tags(self, game, ui, anim):
		alpha, y_off = anim.damage_alpha_offset()
		if alpha <= 0:
			return
		cfg = game.cfg
		for tag in anim.damage_tags:
			scx, scy = cfg.cell_center(tag.gx, tag.gy)
			scy += y_off - 20
			text = f"-{tag.amount}"
			surf = self.fonts["bold"].render(text, True, (255, 80, 60))
			surf.set_alpha(alpha)
			rect = surf.get_rect(center=(scx, scy))
			self.screen.blit(surf, rect)

	# ──────────────────── 左侧面板 ───────────────────

	def _draw_left_panel(self, game, ui):
		cfg = game.cfg
		x, y = 6, cfg.board_offset_y
		w    = cfg.board_offset_x - 12
		h    = cfg.grid_size * cfg.cell_size
		pygame.draw.rect(self.screen, C_PANEL_BG, (x, y, w, h))
		pygame.draw.rect(self.screen, C_PANEL_BDR, (x, y, w, h), 1)

		self._text(x + w // 2, y + 13, f"第 {game.turn} 回合", self.fonts["bold"], C_GOLD, center=True)
		self._text(x + w // 2, y + 30, "地形", self.fonts["small"], C_WHITE, center=True)
		for i, line in enumerate(["壕(4,4)：驻守减伤1", "高(0,4)(8,4)：攻击+1"]):
			self._text(x + 5, y + 47 + i * 13, line, self.fonts["tiny"], C_GRAY)

		camp_names = {1: "废墟据点", 2: "简易兵营", 3: "前线营地"}
		self._text(x + 5, y + 86, "营地", self.fonts["tiny"], C_GRAY)
		self._text(x + 5, y + 99, camp_names[game.camp_level], self.fonts["small"], C_GOLD)

		py = y + 118
		self._text(x + 5, py, "本阵占领", self.fonts["tiny"], C_GRAY)
		py += 13
		for bpos, bstate in game.base_states.items():
			lbl = ("红阵" if bstate.owner == FACTION_RED
				else "灾阵" if bstate.owner == FACTION_DIS else "共享")
			if bstate.occupier:
				oc = "红" if bstate.occupier == FACTION_RED else "灾"
				fc = C_OCCUPY_RED if bstate.occupier == FACTION_RED else C_OCCUPY_DIS
				self._text(x + 5, py, f"{lbl}：{oc}方 {bstate.occupy_count}/2", self.fonts["tiny"], fc)
			else:
				self._text(x + 5, py, f"{lbl}：无", self.fonts["tiny"], C_GRAY)
			py += 13

		# 选中单位信息卡
		if ui.selected_uid:
			u = game.get_unit_by_uid(ui.selected_uid)
			if u and not u.dead:
				self._draw_unit_card(x + 4, py + 4, w - 8, u, game)

		# 行动按钮（在面板底部）
		for act, label, rect in ui.act_btn_rects:
			u = game.get_unit_by_uid(ui.selected_uid)
			active = (u and u.planned_action == act)
			bg = (60, 44, 14) if active else (30, 20, 12)
			bd = C_GOLD if active else C_PANEL_BDR
			pygame.draw.rect(self.screen, bg, rect, border_radius=4)
			pygame.draw.rect(self.screen, bd, rect, 2, border_radius=4)
			self._text(rect.x + 7, rect.centery, label,
				self.fonts["small"], C_GOLD if active else C_WHITE)

	def _draw_unit_card(self, x, y, w, u, game):
		fc = C_RED if u.faction == FACTION_RED else C_DIS
		available_h = min(130, game.cfg.grid_size * game.cfg.cell_size - (y - game.cfg.board_offset_y) - 2)
		if available_h < 40:
			return
		pygame.draw.rect(self.screen, (34, 22, 13), (x, y, w, available_h), border_radius=4)
		pygame.draw.rect(self.screen, fc, (x, y, w, available_h), 1, border_radius=4)
		self._text(x + 5, y + 6,  u.name, self.fonts["bold"], fc)
		self._text(x + 5, y + 22, f"HP {u.hp}/{u.max_hp}", self.fonts["small"], C_WHITE)
		self._text(x + 5, y + 37, f"ATK {game.effective_atk(u)}  SPD {game.effective_spd(u)}",
			self.fonts["small"], C_WHITE)
		if available_h > 70:
			self._text(x + 5, y + 52, f"特：{u.trait}", self.fonts["tiny"], C_GOLD)
			self._text(x + 5, y + 66, f"杀：{u.kills}", self.fonts["tiny"], C_GRAY)
		if hasattr(u, "_pending_evo") or hasattr(u, "_pending_evo3"):
			self._text(x + 5, y + available_h - 14, "⬆ 可进化！", self.fonts["tiny"], C_GOLD)

	# ──────────────────── 右侧面板 ───────────────────

	def _draw_right_panel(self, game, ui):
		cfg = game.cfg
		x   = cfg.board_offset_x + cfg.grid_size * cfg.cell_size + 8
		y   = cfg.board_offset_y
		w   = cfg.panel_width
		h   = cfg.grid_size * cfg.cell_size
		pygame.draw.rect(self.screen, C_PANEL_BG, (x, y, w, h))
		pygame.draw.rect(self.screen, C_PANEL_BDR, (x, y, w, h), 1)
		self._text(x + w // 2, y + 12, "单位列表", self.fonts["bold"], C_GOLD, center=True)

		ry = y + 28
		for faction, label, color in [(FACTION_RED, "★ 红方", C_RED), (FACTION_DIS, "☠ 灾方", C_DIS)]:
			self._text(x + 5, ry, label, self.fonts["small"], color)
			ry += 15
			for u in game.faction_units(faction):
				sel  = (ui.selected_uid == u.uid)
				line = f"{'▶' if sel else ' '}{u.name}  {u.hp}/{u.max_hp}HP"
				self._text(x + 5, ry, line, self.fonts["tiny"],
					C_GOLD if sel else C_WHITE)
				if hasattr(u, "_pending_evo") or hasattr(u, "_pending_evo3"):
					self._text(x + w - 16, ry, "⬆", self.fonts["tiny"], C_GOLD)
				ry += 13
			ry += 4

		log_top = y + h - 108
		pygame.draw.line(self.screen, C_PANEL_BDR, (x, log_top), (x + w, log_top))
		self._text(x + 4, log_top + 4, "战报", self.fonts["tiny"], C_GRAY)
		for i, line in enumerate(game.log[-6:]):
			col = C_WHITE if i == 5 else (100, 94, 86)
			self._text(x + 4, log_top + 18 + i * 14, line[:24], self.fonts["tiny"], col)

	# ──────────────────── 底部操作栏 ─────────────────

	def _draw_bottom_bar(self, game, ui):
		cfg = game.cfg
		by  = cfg.board_offset_y + cfg.grid_size * cfg.cell_size + 6
		bh  = 58
		sw  = cfg.screen_w
		pygame.draw.rect(self.screen, C_PANEL_BG, (0, by, sw, bh))
		pygame.draw.line(self.screen, C_PANEL_BDR, (0, by), (sw, by))

		phase_text = {
			"p1_plan": "【红方规划】 拖拽棋子到目标格移动 | 左侧面板选择行动",
			"p1_done": "【切换阵营】 请灾方接手，点击任意处继续",
			"p2_plan": "【灾方规划】 拖拽棋子到目标格移动 | 左侧面板选择行动",
			"animating": "【执行中…】",
			"result":  "【结算完毕】 点击确认继续下一回合",
			"game_over": "【游戏结束】 关闭窗口退出",
		}.get(ui.phase, "")
		self._text(12, by + 8, phase_text, self.fonts["small"], C_WHITE)
		self._text(12, by + 28, "蓝色菱形 = 移动范围  虚线 = 计划路线  红虚线 = 预测攻击目标",
			self.fonts["tiny"], C_GRAY)

		btn = ui.confirm_btn_rect
		labels = {
			"p1_plan": ("确认规划", C_RED),
			"p2_plan": ("确认规划", C_DIS),
			"result":  ("下一回合", C_GOLD),
		}
		if ui.phase in labels and btn:
			lbl, col = labels[ui.phase]
			pygame.draw.rect(self.screen, col, btn, border_radius=7)
			pygame.draw.rect(self.screen, C_WHITE, btn, 1, border_radius=7)
			self._text(btn.centerx, btn.centery, lbl, self.fonts["bold"], C_WHITE, center=True)

	# ──────────────────── 进化对话框 ─────────────────

	def _draw_evo_dialog(self, game, ui):
		cfg = game.cfg
		n   = len(ui.evo_options)
		dw  = 520
		dh  = 58 + n * 84 + 28
		dx  = (cfg.screen_w - dw) // 2
		dy  = (cfg.screen_h - dh) // 2
		pygame.draw.rect(self.screen, (24, 15, 9), (dx, dy, dw, dh), border_radius=8)
		pygame.draw.rect(self.screen, C_GOLD, (dx, dy, dw, dh), 2, border_radius=8)

		u = game.get_unit_by_uid(ui.evo_uid)
		self._text(dx + dw // 2, dy + 18, f"✨ 进化选择：{u.name if u else '?'}",
			self.fonts["bold"], C_GOLD, center=True)
		self._text(dx + dw // 2, dy + 38, "点击选择路线",
			self.fonts["tiny"], C_GRAY, center=True)

		for i, opt in enumerate(ui.evo_options):
			oy2  = dy + 56 + i * 84
			rect = pygame.Rect(dx + 22, oy2, dw - 44, 72)
			hov  = (i == ui.evo_hover)
			pygame.draw.rect(self.screen, (52, 34, 13) if hov else (34, 22, 10), rect, border_radius=6)
			pygame.draw.rect(self.screen, C_GOLD if hov else C_PANEL_BDR, rect, 2, border_radius=6)
			from unit import UNIT_TEMPLATES
			tmpl  = UNIT_TEMPLATES.get(opt["name"], {})
			route = "路线A（保守）" if i == 0 else "路线B（进化）"
			header = f"{route} → {opt['name']}   HP:{tmpl.get('max_hp','?')} ATK:{tmpl.get('atk','?')} SPD:{tmpl.get('spd','?')}"
			self._text(rect.x + 10, rect.y + 10, header, self.fonts["small"], C_WHITE)
			self._text(rect.x + 10, rect.y + 30, f"特性：{tmpl.get('trait','?')}", self.fonts["small"], C_GOLD)
			self._text(rect.x + 10, rect.y + 50, opt.get("desc",""), self.fonts["tiny"], C_GRAY)

	# ──────────────────── 阶段横幅 ───────────────────

	def _draw_phase_banner(self, game, ui):
		cfg  = game.cfg
		sw, sh = cfg.screen_w, cfg.screen_h
		s = pygame.Surface((sw, 78), pygame.SRCALPHA)
		s.fill((0, 0, 0, 185))
		self.screen.blit(s, (0, sh // 2 - 39))
		self._text(sw // 2, sh // 2, ui.banner_text, self.fonts["title"], C_GOLD, center=True)

	# ──────────────────── 工具 ───────────────────────

	def _text(self, x, y, text, font, color, center=False):
		surf = font.render(str(text), True, color)
		rect = surf.get_rect(center=(x, y)) if center else surf.get_rect(topleft=(x, y))
		self.screen.blit(surf, rect)

	def _wrap(self, text, mc):
		lines = []
		while len(text) > mc:
			lines.append(text[:mc]); text = text[mc:]
		if text:
			lines.append(text)
		return lines
