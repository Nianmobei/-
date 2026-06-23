# 血轨：渲染器 v2 — 分阶段配色、脉冲光晕、震屏、地形渲染

import pygame
import math
from constants import *
from animator import AnimPhase


def _lerp_color(c1, c2, t):
	return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))


def _alpha_surf(w, h):
	s = pygame.Surface((w, h), pygame.SRCALPHA)
	return s


# 阶段配色方案
PHASE_PALETTE = {
		"p1_plan": {
			"panel_bg":    (32, 14, 10),
			"panel_bdr":   (200, 60, 40),
			"accent":      C_RED,
			"accent_lite": C_RED_LITE,
			"label":       "红骑士团规划",
			"hint":        (255, 80, 60),
		},
		"p1_done": {
			"panel_bg":    (20, 10, 8),
			"panel_bdr":   (120, 40, 28),
			"accent":      C_RED,
			"accent_lite": C_RED_LITE,
			"label":       "切换阵营",
			"hint":        (180, 60, 50),
		},
		"p2_plan": {
			"panel_bg":    (10, 28, 16),
			"panel_bdr":   (40, 180, 80),
			"accent":      C_DIS,
			"accent_lite": C_DIS_LITE,
			"label":       "灾兽群规划",
			"hint":        (60, 200, 100),
		},
	"animating": {
		"panel_bg":    C_PANEL_BG,
		"panel_bdr":   C_PANEL_BDR,
		"accent":      C_GOLD,
		"accent_lite": C_GOLD,
		"label":       "执行中",
		"hint":        C_GOLD,
	},
	"result": {
		"panel_bg":    C_PANEL_BG,
		"panel_bdr":   C_GOLD,
		"accent":      C_GOLD,
		"accent_lite": C_GOLD,
		"label":       "结算完毕",
		"hint":        C_GOLD,
	},
	"game_over": {
		"panel_bg":    (28, 8, 6),
		"panel_bdr":   C_GOLD,
		"accent":      C_GOLD,
		"accent_lite": C_GOLD,
		"label":       "游戏结束",
		"hint":        C_GOLD,
	},
}

_DEFAULT_PALETTE = PHASE_PALETTE["result"]


class Renderer:
	def __init__(self, screen: pygame.Surface, fonts: dict):
		self.screen = screen
		self.fonts  = fonts
		self._pulse_t = 0.0   # 脉冲时钟

	def _palette(self, ui):
		return PHASE_PALETTE.get(ui.phase, _DEFAULT_PALETTE)

	# ──────────────────── 主入口 ─────────────────────

	def draw(self, game, ui, anim=None):
		self._pulse_t += 0.035
		pal = self._palette(ui)

		# 震屏偏移
		sx, sy = (0, 0)
		if anim and anim.is_playing:
			sx, sy = anim.get_shake()
		sx, sy = int(sx), int(sy)

		self.screen.fill(C_BG)

		# 绘制到偏移 surface（震屏）
		if sx or sy:
			board_surf = pygame.Surface(self.screen.get_size(), pygame.SRCALPHA)
			self._draw_board(game, ui, anim, surf=board_surf)
			self.screen.blit(board_surf, (sx, sy))
		else:
			self._draw_board(game, ui, anim)

		self._draw_plan_overlays(game, ui)
		self._draw_drag_piece(game, ui)
		self._draw_left_panel(game, ui, pal)
		self._draw_right_panel(game, ui, pal)
		self._draw_bottom_bar(game, ui, pal)
		if anim and anim.is_playing:
			self._draw_damage_tags(game, ui, anim)
			self._draw_projectiles(game, anim)
		if ui.evo_uid is not None:
			self._draw_evo_popup(game, ui)
		if ui.show_phase_banner:
			self._draw_phase_banner(game, ui)

	# ──────────────────── 棋盘格 ─────────────────────

	def _draw_board(self, game, ui, anim, surf=None):
		target = surf if surf else self.screen
		cfg = game.cfg
		cs  = cfg.cell_size
		ox  = cfg.board_offset_x
		oy  = cfg.board_offset_y
		gs  = cfg.grid_size

		for cy in range(gs):
			for cx in range(gs):
				rx = ox + cx * cs
				ry = oy + cy * cs
				rect = pygame.Rect(rx, ry, cs, cs)

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
				pygame.draw.rect(target, color, rect)

				# 移动范围高亮
				if (cx, cy) in ui.move_hints:
					pal = self._palette(ui)
					s = _alpha_surf(cs, cs)
					alpha = 70 if (cx, cy) != ui.hover_cell else 110
					hint_col = pal["accent"]
					s.fill((*hint_col, alpha // 3))
					pygame.draw.rect(s, (*hint_col, alpha), (0, 0, cs, cs), 3)
					target.blit(s, (rx, ry))

				# 选定目标格
				if ui.selected_move_cell and (cx, cy) == ui.selected_move_cell:
					pal = self._palette(ui)
					s = _alpha_surf(cs, cs)
					s.fill((*pal["accent_lite"], 50))
					pygame.draw.rect(s, (*pal["accent_lite"], 160), (0, 0, cs, cs), 3)
					target.blit(s, (rx, ry))

				# 攻击范围
				if (cx, cy) in ui.attack_hints and (cx, cy) not in ui.move_hints:
					s = _alpha_surf(cs, cs)
					s.fill((*C_ATK_HINT, 22))
					pygame.draw.rect(s, (*C_ATK_HINT, 55), (0, 0, cs, cs), 1)
					target.blit(s, (rx, ry))

				pygame.draw.rect(target, C_GRID, rect, 1)

				# 本阵标签
				if cfg.is_base(cx, cy):
					owner = cfg.base_owner(cx, cy)
					lbl   = "骑士阵" if owner == FACTION_RED else "灾兽巢"
					col   = C_RED if owner == FACTION_RED else C_DIS
					fkey  = "small" if cs >= 76 else "tiny"
					self._text_on(target, rx + cs // 2, ry + cs - 13, lbl,
						self.fonts[fkey], col, center=True)
					bs = game.base_states.get((cx, cy))
					if bs and bs.occupier:
						fc  = C_OCCUPY_RED if bs.occupier == FACTION_RED else C_OCCUPY_DIS
						tag = ("红" if bs.occupier == FACTION_RED else "灾") + f" {bs.occupy_count}/2"
						self._text_on(target, rx + cs // 2, ry + 9, tag,
							self.fonts["tiny"], fc, center=True)

				# 地形标签（左下小字 + 图标）
				if terrain == "trench":
					self._text_on(target, rx + 4, ry + cs - 13, "壕",
						self.fonts["tiny"], (160, 190, 255))
				elif terrain == "high":
					self._text_on(target, rx + 4, ry + cs - 13, "高",
						self.fonts["tiny"], (255, 210, 80))

				# 棋子
				self._draw_units_in_cell(
					game.units_at(cx, cy), rx, ry, game, ui, anim, cs, target)

	def _draw_units_in_cell(self, units, rx, ry, game, ui, anim, cs, target=None):
		if target is None:
			target = self.screen
		if not units:
			return
		n = len(units)
		for i, u in enumerate(units):
			if u.uid == ui.dragging_uid:
				# 原位置幽灵
				scx = rx + cs // 2
				scy = ry + cs // 2 - 5
				r   = max(8, int(18 * cs / 110))
				ghost = _alpha_surf(r * 2 + 4, r * 2 + 4)
				pygame.draw.circle(ghost, (*C_GHOST, 50), (r + 2, r + 2), r)
				pygame.draw.circle(ghost, (*C_WHITE, 70), (r + 2, r + 2), r, 2)
				target.blit(ghost, (scx - r - 2, scy - r - 2))
				continue

			if anim and anim.is_playing:
				vgx, vgy = anim.get_vpos(u.uid, u.x, u.y)
				scx = int(game.cfg.board_offset_x + vgx * cs + cs // 2)
				scy = int(game.cfg.board_offset_y + vgy * cs + cs // 2) - 5
			else:
				ox2 = (i - (n - 1) / 2) * (cs // max(n + 1, 2))
				scx = rx + cs // 2 + int(ox2)
				scy = ry + cs // 2 - 5

			self._draw_single_unit(u, scx, scy, game, ui, anim, cs, target)

			# HP 条（底部）
			bar_w = cs - 14
			bar_x = rx + 7
			bar_y = ry + cs - 9 - i * 7
			hp_r  = u.hp / max(u.max_hp, 1)
			pygame.draw.rect(target, C_DARK_GRAY, (bar_x, bar_y, bar_w, 4))
			bar_col = C_HP_GREEN if hp_r > 0.45 else ((200, 160, 40) if hp_r > 0.2 else C_HP_RED)
			pygame.draw.rect(target, bar_col,
				(bar_x, bar_y, max(1, int(bar_w * hp_r)), 4))

	def _draw_single_unit(self, u, scx, scy, game, ui, anim, cs, target=None):
		if target is None:
			target = self.screen
		scale  = cs / 110
		radius = max(8, int((24 if u.level >= 3 else (20 if u.level == 2 else 16)) * scale))

		selected = (u.uid == ui.selected_uid)
		is_cur_faction = (
			(ui.phase in ("p1_plan", "p1_done") and u.faction == FACTION_RED)
			or (ui.phase == "p2_plan" and u.faction == FACTION_DIS)
		)

		if u.is_embryo:
			color = C_EMBYO
		elif u.faction == FACTION_RED:
			color = C_RED_LITE if selected else C_RED
		else:
			color = C_DIS_LITE if selected else C_DIS

		dead_a = anim.dead_alpha(u.uid) if anim else (0 if u.dead else 255)
		if dead_a == 0:
			return

		# 受击闪白
		flash = anim.hit_brightness(u.uid) if anim else 0.0
		if flash > 0:
			color = _lerp_color(color, (255, 255, 255), flash)

		# 脉冲光晕（当前操控方且未死亡）
		if is_cur_faction and not u.dead and not (anim and anim.is_playing):
			pulse = 0.5 + 0.5 * math.sin(self._pulse_t + u.uid * 0.7)
			halo_r = radius + int(6 * pulse)
			halo_a = int(40 * pulse)
			halo = _alpha_surf(halo_r * 2 + 4, halo_r * 2 + 4)
			hc = C_RED if u.faction == FACTION_RED else C_DIS
			pygame.draw.circle(halo, (*hc, halo_a), (halo_r + 2, halo_r + 2), halo_r)
			target.blit(halo, (scx - halo_r - 2, scy - halo_r - 2))

		# 选中环（双层）
		if selected:
			pygame.draw.circle(target, C_SEL, (scx, scy), radius + 7, 1)
			pygame.draw.circle(target, C_WHITE, (scx, scy), radius + 4, 2)

		# 棋子主体
		surf = _alpha_surf(radius * 2 + 2, radius * 2 + 2)
		pygame.draw.circle(surf, (*color, dead_a), (radius + 1, radius + 1), radius)
		# 高光
		hl_col = _lerp_color(color, (255, 255, 255), 0.4)
		pygame.draw.circle(surf, (*hl_col, dead_a // 2),
			(radius + 1 - radius // 4, radius + 1 - radius // 4), radius // 3)
		pygame.draw.circle(surf, (*C_WHITE, dead_a), (radius + 1, radius + 1), radius, 2)
		target.blit(surf, (scx - radius - 1, scy - radius - 1))

		# 兵种名
		fkey = "unit" if cs >= 76 else "tiny"
		self._text_on(target, scx, scy - 3, u.name[:2], self.fonts[fkey], C_WHITE, center=True)

		# 等级点
		for lv in range(u.level):
			pygame.draw.circle(target, C_GOLD,
				(scx - (u.level - 1) * 4 + lv * 8, scy + radius - 3), 2)

		# 行动图标
		icon = {ACT_DEFEND: "🛡", ACT_OCCUPY: "🚩", ACT_MAKE: "🐣"}.get(u.planned_action)
		if icon:
			self._text_on(target, scx + radius - 2, scy - radius + 2, icon,
				self.fonts["tiny"], C_GOLD)

		# 进化可用提示（金色星形环）
		if hasattr(u, "_pending_evo") or hasattr(u, "_pending_evo3"):
			pulse2 = 0.5 + 0.5 * math.sin(self._pulse_t * 1.8 + u.uid)
			evo_r  = radius + 10
			evo_a  = int(120 * pulse2)
			evo_s  = _alpha_surf(evo_r * 2 + 4, evo_r * 2 + 4)
			pygame.draw.circle(evo_s, (*C_GOLD, evo_a), (evo_r + 2, evo_r + 2), evo_r, 2)
			target.blit(evo_s, (scx - evo_r - 2, scy - evo_r - 2))

	# ──────────────────── 规划覆盖层 ─────────────────

	def _draw_plan_overlays(self, game, ui):
		if ui.phase not in ("p1_plan", "p2_plan", "p1_done"):
			return
		cfg = game.cfg
		pal = self._palette(ui)
		cs  = cfg.cell_size

		for u in game.alive_units():
			if u.is_embryo or u.uid == ui.dragging_uid:
				continue
			ux, uy = cfg.cell_center(u.x, u.y)

			# 移动预览：目标格地面透明箭头（贴地，不画连线）
			if u.planned_dir != DIR_NONE:
				dx, dy = u.planned_dir
				tx, ty = cfg.cell_center(u.x + dx, u.y + dy)
				fc = C_RED if u.faction == FACTION_RED else C_DIS
				# 地面填色格
				rx = cfg.board_offset_x + (u.x + dx) * cs
				ry = cfg.board_offset_y + (u.y + dy) * cs
				s = _alpha_surf(cs, cs)
				s.fill((*fc, 28))
				self.screen.blit(s, (rx, ry))
				# 贴地大箭头（指向目标格中心）
				self._draw_ground_arrow(tx, ty, ux, uy, fc, 120, size=int(cs * 0.28))
				# 幽灵棋子
				radius = max(6, int(14 * cs / 110))
				gs2 = _alpha_surf(radius * 2 + 2, radius * 2 + 2)
				pygame.draw.circle(gs2, (*fc, 55), (radius + 1, radius + 1), radius)
				pygame.draw.circle(gs2, (*C_WHITE, 80), (radius + 1, radius + 1), radius, 1)
				self.screen.blit(gs2, (tx - radius - 1, ty - radius - 6))

			# 攻击预测：抛物线弧形虚线（当前操控方）
			cur_faction = FACTION_RED if ui.phase in ("p1_plan", "p1_done") else FACTION_DIS
			if u.faction == cur_faction:
				t = game.predict_attack_target(u)
				if t:
					tx2, ty2 = cfg.cell_center(t.x, t.y)
					self._draw_arc_dashed(ux, uy - 5, tx2, ty2 - 5, C_ATK_PREV, 85)
					self._draw_arrow_head(tx2, ty2 - 5, ux, uy - 5, C_ATK_PREV, 70)

	def _draw_ground_arrow(self, tip_x, tip_y, from_x, from_y, color, alpha, size=18):
		"""贴地大三角箭头，指向目标格中心"""
		dx, dy = tip_x - from_x, tip_y - from_y
		dist   = math.hypot(dx, dy)
		if dist < 0.1:
			return
		ux, uy = dx / dist, dy / dist
		px, py = -uy, ux
		p1 = (tip_x, tip_y)
		p2 = (tip_x - ux * size + px * size * 0.55, tip_y - uy * size + py * size * 0.55)
		p3 = (tip_x - ux * size - px * size * 0.55, tip_y - uy * size - py * size * 0.55)
		s = _alpha_surf(self.screen.get_width(), self.screen.get_height())
		pygame.draw.polygon(s, (*color, alpha), [p1, p2, p3])
		self.screen.blit(s, (0, 0))

	def _draw_arc_dashed(self, x1, y1, x2, y2, color, alpha, n=22):
		"""抛物线弧形虚线：控制点偏向左侧，呈抛射弧"""
		dx, dy = x2 - x1, y2 - y1
		dist   = math.hypot(dx, dy)
		if dist < 0.1:
			return
		# 垂直于方向的左侧偏移作为控制点
		perp_x = -dy / dist
		perp_y =  dx / dist
		mid_x  = (x1 + x2) / 2 + perp_x * dist * 0.38
		mid_y  = (y1 + y2) / 2 + perp_y * dist * 0.38
		# 采样二次贝塞尔曲线上的点
		pts = []
		for i in range(n + 1):
			t  = i / n
			bx = (1-t)**2 * x1 + 2*(1-t)*t * mid_x + t**2 * x2
			by = (1-t)**2 * y1 + 2*(1-t)*t * mid_y + t**2 * y2
			pts.append((int(bx), int(by)))
		# 虚线：隔一段画一段
		surf = _alpha_surf(self.screen.get_width(), self.screen.get_height())
		for i in range(0, len(pts) - 1, 2):
			pygame.draw.line(surf, (*color, alpha), pts[i], pts[i + 1], 2)
		self.screen.blit(surf, (0, 0))

	def _draw_arrow_head(self, tip_x, tip_y, from_x, from_y, color, alpha, size=7):
		dx, dy = tip_x - from_x, tip_y - from_y
		dist   = math.hypot(dx, dy)
		if dist < 0.1:
			return
		ux, uy = dx / dist, dy / dist
		px, py = -uy, ux
		p1 = (tip_x, tip_y)
		p2 = (tip_x - ux * size + px * (size * 0.5), tip_y - uy * size + py * (size * 0.5))
		p3 = (tip_x - ux * size - px * (size * 0.5), tip_y - uy * size - py * (size * 0.5))
		s = _alpha_surf(self.screen.get_width(), self.screen.get_height())
		pygame.draw.polygon(s, (*color, alpha), [p1, p2, p3])
		self.screen.blit(s, (0, 0))

	def _draw_dashed_line(self, x1, y1, x2, y2, color, alpha, dash=6):
		dx, dy = x2 - x1, y2 - y1
		length = math.hypot(dx, dy)
		if length == 0:
			return
		steps = max(1, int(length / (dash * 2)))
		surf  = _alpha_surf(self.screen.get_width(), self.screen.get_height())
		for i in range(steps):
			t0 = i * dash * 2 / length
			t1 = min(1.0, (i * dash * 2 + dash) / length)
			ax, ay = int(x1 + dx * t0), int(y1 + dy * t0)
			bx, by = int(x1 + dx * t1), int(y1 + dy * t1)
			pygame.draw.line(surf, (*color, alpha), (ax, ay), (bx, by), 2)
		self.screen.blit(surf, (0, 0))

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

		# 投影
		shadow = _alpha_surf(radius * 2 + 14, radius * 2 + 14)
		pygame.draw.circle(shadow, (0, 0, 0, 60), (radius + 7, radius + 10), radius)
		self.screen.blit(shadow, (mx - radius - 7, my - radius - 4))

		# 光环（拖拽时强调）
		halo = _alpha_surf(radius * 2 + 22, radius * 2 + 22)
		pygame.draw.circle(halo, (*color, 50), (radius + 11, radius + 11), radius + 6)
		self.screen.blit(halo, (mx - radius - 11, my - radius - 11))

		# 主体
		surf = _alpha_surf(radius * 2 + 2, radius * 2 + 2)
		pygame.draw.circle(surf, (*color, 235), (radius + 1, radius + 1), radius)
		pygame.draw.circle(surf, (*C_WHITE, 235), (radius + 1, radius + 1), radius, 2)
		self.screen.blit(surf, (mx - radius - 1, my - radius - 1))
		self._text(mx, my - 2, u.name[:2], self.fonts["unit"], C_WHITE, center=True)

		# 落点高亮
		cell = game.cfg.screen_to_cell(mx, my)
		if cell and cell in ui.move_hints:
			cx, cy = cell
			rx = cfg.board_offset_x + cx * cs
			ry = cfg.board_offset_y + cy * cs
			pal = self._palette(ui)
			hl = _alpha_surf(cs, cs)
			hl.fill((*pal["accent_lite"], 80))
			self.screen.blit(hl, (rx, ry))
			pygame.draw.rect(self.screen, pal["accent_lite"],
				pygame.Rect(rx, ry, cs, cs), 2)

	# ──────────────────── 伤害数字 ───────────────────

	def _draw_damage_tags(self, game, ui, anim):
		alpha, y_off = anim.damage_alpha_offset()
		if alpha <= 0:
			return
		cfg = game.cfg
		for tag in anim.damage_tags:
			scx, scy = cfg.cell_center(tag.gx, tag.gy)
			scy += y_off - 22
			if tag.is_heal:
				col  = (80, 220, 100)
				text = f"+{tag.amount}"
			else:
				col  = (255, 80, 50) if tag.amount >= 3 else (230, 140, 80)
				text = f"-{tag.amount}"
			fkey = "bold" if tag.amount >= 3 else "small"
			surf = self.fonts[fkey].render(text, True, col)
			surf.set_alpha(alpha)
			# 描边
			out = self.fonts[fkey].render(text, True, (0, 0, 0))
			out.set_alpha(alpha // 2)
			rect = surf.get_rect(center=(scx, scy))
			self.screen.blit(out, (rect.x + 1, rect.y + 1))
			self.screen.blit(surf, rect)

	# ──────────────────── 远程抛射体 ───────────────────

	def _draw_projectiles(self, game, anim):
		from animator import AnimPhase
		if anim.phase not in (AnimPhase.RANGED,):
			return
		cfg = game.cfg
		cs  = cfg.cell_size

		for p in anim.projectiles:
			if p.hit:
				continue
			t = p.progress
			if p.is_cannon:
				# 炮弹：抛物线弧度，较大圆形，橙黄色
				px_s = cfg.board_offset_x + p.sx * cs + cs // 2
				py_s = cfg.board_offset_y + p.sy * cs + cs // 2 - 5
				px_t = cfg.board_offset_x + p.tx * cs + cs // 2
				py_t = cfg.board_offset_y + p.ty * cs + cs // 2 - 5
				cx   = px_s + (px_t - px_s) * t
				# 抛物线上弧
				arc  = -math.sin(t * math.pi) * cs * 1.2
				cy   = py_s + (py_t - py_s) * t + arc
				r    = max(5, int(7 * (1.0 - abs(t - 0.5) * 0.5)))
				# 外光晕
				halo = _alpha_surf(r * 4, r * 4)
				pygame.draw.circle(halo, (255, 140, 40, 60), (r * 2, r * 2), r * 2)
				self.screen.blit(halo, (int(cx) - r * 2, int(cy) - r * 2))
				pygame.draw.circle(self.screen, (255, 200, 60), (int(cx), int(cy)), r)
				pygame.draw.circle(self.screen, (255, 255, 180), (int(cx), int(cy)), max(2, r // 2))
			else:
				# 弩箭：直线，细长，白蓝色，带尾迹
				px_s = cfg.board_offset_x + p.sx * cs + cs // 2
				py_s = cfg.board_offset_y + p.sy * cs + cs // 2 - 5
				px_t = cfg.board_offset_x + p.tx * cs + cs // 2
				py_t = cfg.board_offset_y + p.ty * cs + cs // 2 - 5
				cx   = px_s + (px_t - px_s) * t
				cy   = py_s + (py_t - py_s) * t
				# 箭头方向
				dx, dy = px_t - px_s, py_t - py_s
				dist   = math.hypot(dx, dy)
				if dist > 0.1:
					ux, uy = dx / dist, dy / dist
					# 尾迹（3段渐淡）
					tail_len = cs * 0.6
					for i, (frac, alpha) in enumerate([(0.7, 80), (0.4, 40), (0.2, 15)]):
						bx = cx - ux * tail_len * frac
						by = cy - uy * tail_len * frac
						surf = _alpha_surf(self.screen.get_width(), self.screen.get_height())
						pygame.draw.line(surf, (180, 220, 255, alpha),
							(int(bx), int(by)), (int(cx), int(cy)), 2)
						self.screen.blit(surf, (0, 0))
					# 箭体
					tip_x = int(cx + ux * 8)
					tip_y = int(cy + uy * 8)
					tail_x = int(cx - ux * 12)
					tail_y = int(cy - uy * 12)
					pygame.draw.line(self.screen, (220, 240, 255), (tail_x, tail_y), (tip_x, tip_y), 2)
					pygame.draw.circle(self.screen, (255, 255, 255), (tip_x, tip_y), 2)

	# ──────────────────── 左侧面板 ───────────────────

	def _draw_left_panel(self, game, ui, pal):
		cfg = game.cfg
		x, y = 6, cfg.board_offset_y
		w    = cfg.board_offset_x - 12
		h    = cfg.grid_size * cfg.cell_size

		pygame.draw.rect(self.screen, pal["panel_bg"], (x, y, w, h))
		# 阶段强调边框（2px + 顶部彩条）
		pygame.draw.rect(self.screen, pal["panel_bdr"], (x, y, w, h), 2)
		pygame.draw.rect(self.screen, pal["accent"], (x, y, w, 4))

		# 回合标题
		self._text(x + w // 2, y + 16, f"第 {game.turn} 回合", self.fonts["bold"], C_GOLD, center=True)

		# 地形提示（紧凑两行）
		self._text(x + 4, y + 34, "地形规则", self.fonts["tiny"], C_GRAY)
		self._text(x + 4, y + 47, "壕(4,4) 驻守-1伤", self.fonts["tiny"], (160, 190, 255))
		self._text(x + 4, y + 60, "高(0,4)(8,4) 攻+1", self.fonts["tiny"], (255, 210, 80))

		# 营地等级
		camp_names = {1: "废墟据点", 2: "简易兵营", 3: "前线营地"}
		pygame.draw.line(self.screen, pal["panel_bdr"], (x + 4, y + 76), (x + w - 4, y + 76), 1)
		self._text(x + 4, y + 80, "营地", self.fonts["tiny"], C_GRAY)
		self._text(x + 4, y + 93, camp_names[game.camp_level], self.fonts["small"], C_GOLD)

		# 本阵状态
		pygame.draw.line(self.screen, pal["panel_bdr"], (x + 4, y + 112), (x + w - 4, y + 112), 1)
		self._text(x + 4, y + 116, "本阵占领", self.fonts["tiny"], C_GRAY)
		py = y + 129
		for bpos, bstate in game.base_states.items():
			lbl = "骑士阵" if bstate.owner == FACTION_RED else "灾兽巢"
			if bstate.occupier:
				oc  = "红" if bstate.occupier == FACTION_RED else "灾"
				fc  = C_OCCUPY_RED if bstate.occupier == FACTION_RED else C_OCCUPY_DIS
				self._text(x + 4, py, f"{lbl}:{oc} {bstate.occupy_count}/2", self.fonts["tiny"], fc)
			else:
				self._text(x + 4, py, f"{lbl}: —", self.fonts["tiny"], C_GRAY)
			py += 14

		# 选中单位信息卡
		if ui.selected_uid:
			u = game.get_unit_by_uid(ui.selected_uid)
			if u and not u.dead:
				pygame.draw.line(self.screen, pal["panel_bdr"],
					(x + 4, py + 4), (x + w - 4, py + 4), 1)
				self._draw_unit_card(x + 4, py + 8, w - 8, u, game, pal)

		# 行动按钮
		for act, label, rect in ui.act_btn_rects:
			u = game.get_unit_by_uid(ui.selected_uid)
			active = (u and u.planned_action == act)
			# 根据动作类型着色
			if act == ACT_DEFEND:
				btn_accent = (60, 110, 200)
			elif act == ACT_OCCUPY:
				btn_accent = (160, 130, 40)
			elif act == ACT_MAKE:
				btn_accent = (80, 160, 80)
			else:
				btn_accent = pal["accent"]
			bg = (*btn_accent, 70) if active else (30, 20, 12)
			if active:
				pygame.draw.rect(self.screen, btn_accent, rect, border_radius=5)
			else:
				pygame.draw.rect(self.screen, bg[:3], rect, border_radius=5)
			bd = btn_accent if active else pal["panel_bdr"]
			pygame.draw.rect(self.screen, bd, rect, 2, border_radius=5)
			txt_col = C_WHITE if active else C_GRAY
			self._text(rect.x + 8, rect.centery, label, self.fonts["small"], txt_col)
			if active:
				# 激活状态小勾
				self._text(rect.right - 16, rect.centery, "✓", self.fonts["small"], C_WHITE)

	def _draw_unit_card(self, x, y, w, u, game, pal):
		fc = C_RED if u.faction == FACTION_RED else C_DIS
		available_h = min(135, game.cfg.grid_size * game.cfg.cell_size - (y - game.cfg.board_offset_y) - 2)
		if available_h < 40:
			return
		pygame.draw.rect(self.screen, (34, 22, 13), (x, y, w, available_h), border_radius=4)
		pygame.draw.rect(self.screen, fc, (x, y, w, available_h), 1, border_radius=4)
		# 名称与等级
		level_dots = "●" * u.level
		self._text(x + 5, y + 6, u.name, self.fonts["bold"], fc)
		self._text(x + w - 5 - len(level_dots) * 8, y + 6, level_dots, self.fonts["tiny"], C_GOLD)
		# 数值行
		self._text(x + 5, y + 22, f"HP  {u.hp} / {u.max_hp}", self.fonts["small"], C_WHITE)
		terrain = game.cfg.terrain_at(u.x, u.y)
		atk_eff = game.effective_atk(u)
		atk_str = f"ATK {atk_eff}" + (" ▲" if terrain == "high" else "")
		self._text(x + 5, y + 37, atk_str, self.fonts["small"],
			(255, 210, 80) if terrain == "high" else C_WHITE)
		self._text(x + 5, y + 52, f"SPD {u.spd}", self.fonts["small"], C_WHITE)
		if available_h > 75:
			self._text(x + 5, y + 67, f"特：{u.trait}", self.fonts["tiny"], C_GOLD)
			self._text(x + 5, y + 81, f"经验：{u.kills}",
				self.fonts["tiny"], C_GOLD if u.kills >= 1 else C_GRAY)
		if hasattr(u, "_pending_evo") or hasattr(u, "_pending_evo3"):
			self._text(x + 5, y + available_h - 14, "⬆ 可进化！", self.fonts["tiny"], C_GOLD)

	# ──────────────────── 右侧面板 ───────────────────

	def _draw_right_panel(self, game, ui, pal):
		cfg = game.cfg
		x   = cfg.board_offset_x + cfg.grid_size * cfg.cell_size + 8
		y   = cfg.board_offset_y
		w   = cfg.panel_width
		h   = cfg.grid_size * cfg.cell_size

		pygame.draw.rect(self.screen, pal["panel_bg"], (x, y, w, h))
		pygame.draw.rect(self.screen, pal["panel_bdr"], (x, y, w, h), 2)
		pygame.draw.rect(self.screen, pal["accent"], (x, y, w, 4))

		self._text(x + w // 2, y + 16, "单位列表", self.fonts["bold"], C_GOLD, center=True)

		ry = y + 32
		for faction, label, color in [
			(FACTION_RED, "★ 红骑士团", C_RED),
			(FACTION_DIS, "☠ 灾兽群",   C_DIS),
		]:
			# 阵营分隔标题
			pygame.draw.rect(self.screen, (*color, 40)[:3], (x + 2, ry, w - 4, 16),
				border_radius=2)
			self._text(x + 6, ry + 2, label, self.fonts["small"], color)
			ry += 18
			for u in game.faction_units(faction):
				sel  = (ui.selected_uid == u.uid)
				bg_col = (50, 32, 14) if sel else None
				if sel:
					pygame.draw.rect(self.screen, bg_col,
						(x + 2, ry - 1, w - 4, 14), border_radius=2)
				name_col = C_GOLD if sel else C_WHITE
				hp_col   = C_HP_GREEN if u.hp / u.max_hp > 0.45 else (
					(200, 160, 40) if u.hp / u.max_hp > 0.2 else C_HP_RED)
				# 等级 → 名字 → HP
				lvl_str = "Ⅲ" if u.level == 3 else ("Ⅱ" if u.level == 2 else "Ⅰ")
				self._text(x + 5, ry, f"{lvl_str} {u.name}", self.fonts["tiny"], name_col)
				self._text(x + w - 5, ry, f"{u.hp}/{u.max_hp}",
					self.fonts["tiny"], hp_col, center=False)
				if hasattr(u, "_pending_evo") or hasattr(u, "_pending_evo3"):
					self._text(x + w - 18, ry, "⬆", self.fonts["tiny"], C_GOLD)
				ry += 14
			ry += 5

		# 战报
		log_top = y + h - 116
		pygame.draw.line(self.screen, pal["panel_bdr"], (x, log_top), (x + w, log_top))
		self._text(x + 5, log_top + 4, "战  报", self.fonts["tiny"], C_GRAY)
		recent = game.log[-7:]
		for i, line in enumerate(recent):
			age  = len(recent) - 1 - i
			frac = 1.0 - age / max(len(recent) - 1, 1) * 0.65
			col  = tuple(int(c * frac) for c in C_WHITE)
			# 截断并显示
			short = line if len(line) <= 22 else line[:21] + "…"
			self._text(x + 5, log_top + 18 + i * 14, short, self.fonts["tiny"], col)

	# ──────────────────── 底部操作栏 ─────────────────

	def _draw_bottom_bar(self, game, ui, pal):
		cfg = game.cfg
		by  = cfg.board_offset_y + cfg.grid_size * cfg.cell_size + 6
		bh  = 58
		sw  = cfg.screen_w

		pygame.draw.rect(self.screen, pal["panel_bg"], (0, by, sw, bh))
		pygame.draw.line(self.screen, pal["panel_bdr"], (0, by), (sw, by), 2)

		# 阶段文字
		phase_lines = {
			"p1_plan":    ("【红骑士团规划】", "拖拽棋子移动  •  左侧面板选择行动  •  红虚线 = 预测攻击目标"),
			"p1_done":    ("【切换阵营 ▶】",   "请灾兽群接手  •  点击任意处继续"),
			"p2_plan":    ("【灾兽群规划】",   "拖拽棋子移动  •  左侧面板选择行动  •  红虚线 = 预测攻击目标"),
			"animating":  ("【执行中…】",      ""),
			"result":     ("【结算完毕】",     "点击确认 / Enter 继续下一回合"),
			"game_over":  ("【游戏结束】",     "关闭窗口退出"),
		}
		title, sub = phase_lines.get(ui.phase, ("", ""))
		self._text(12, by + 7, title, self.fonts["bold"], pal["accent"])
		if sub:
			self._text(12, by + 28, sub, self.fonts["tiny"], C_GRAY)

		# 确认按钮
		btn = ui.confirm_btn_rect
		labels = {
			"p1_plan": ("确认规划  ▶", C_RED),
			"p2_plan": ("确认规划  ▶", C_DIS),
			"result":  ("下一回合  ▶", C_GOLD),
		}
		if ui.phase in labels and btn:
			lbl, col = labels[ui.phase]
			# 脉冲边框
			pulse = 0.5 + 0.5 * math.sin(self._pulse_t * 1.4)
			border_col = _lerp_color(col, C_WHITE, pulse * 0.4)
			pygame.draw.rect(self.screen, col, btn, border_radius=8)
			pygame.draw.rect(self.screen, border_col, btn, 2, border_radius=8)
			self._text(btn.centerx, btn.centery, lbl, self.fonts["bold"], C_WHITE, center=True)

	# ──────────────────── 进化悬浮面板 ──────────────────

	def _draw_evo_popup(self, game, ui):
		from unit import UNIT_TEMPLATES
		if not hasattr(ui, "evo_popup_rect") or ui.evo_popup_rect is None:
			return
		pr  = ui.evo_popup_rect
		u   = game.get_unit_by_uid(ui.evo_uid)
		if not u:
			return

		# 背景遮罩（仅棋子周围淡化，不全屏）
		mask = _alpha_surf(pr.width + 20, pr.height + 20)
		mask.fill((0, 0, 0, 90))
		self.screen.blit(mask, (pr.x - 10, pr.y - 10))

		# 面板主体
		pygame.draw.rect(self.screen, (22, 14, 8), pr, border_radius=8)
		fc = C_RED if u.faction == FACTION_RED else C_DIS
		pygame.draw.rect(self.screen, fc, pr, 2, border_radius=8)
		pygame.draw.rect(self.screen, fc, pygame.Rect(pr.x, pr.y, pr.width, 5), border_radius=8)

		# 标题
		self._text(pr.x + pr.width // 2, pr.y + 14,
			f"⬆ {u.name} 可进化", self.fonts["small"], C_GOLD, center=True)
		self._text(pr.x + pr.width // 2, pr.y + 28,
			"选任意路线将补满HP", self.fonts["tiny"], C_GRAY, center=True)

		# 按钮
		labels = ["A路", "B路", "不进化"]
		colors = [(80, 180, 80), (180, 130, 40), (100, 100, 100)]
		for idx, rect in ui.evo_btn_rects:
			hov   = (idx == ui.evo_hover)
			opt_i = idx  # 0/1 = 路线, 2 = 不进化
			bc    = colors[opt_i] if opt_i < 3 else colors[2]
			bg    = bc if hov else (40, 26, 14)
			bd    = bc
			pygame.draw.rect(self.screen, bg, rect, border_radius=5)
			pygame.draw.rect(self.screen, bd, rect, 2, border_radius=5)

			if opt_i < len(ui.evo_options):
				opt  = ui.evo_options[opt_i]
				tmpl = UNIT_TEMPLATES.get(opt["name"], {})
				line1 = f"{labels[opt_i]} → {opt['name']}"
				line2 = f"HP{tmpl.get('max_hp','?')} ATK{tmpl.get('atk','?')} SPD{tmpl.get('spd','?')} {tmpl.get('trait','?')}"
			else:
				line1 = "不进化  HP补满"
				line2 = f"保持 {u.name}"
			tc = C_WHITE if hov else C_GRAY
			self._text(rect.x + 6, rect.centery - 7, line1, self.fonts["small"], tc)
			self._text(rect.x + 6, rect.centery + 7, line2, self.fonts["tiny"],
				C_GOLD if hov else (120, 100, 70))

	# ──────────────────── 阶段横幅 ───────────────────

	def _draw_phase_banner(self, game, ui):
		cfg    = game.cfg
		sw, sh = cfg.screen_w, cfg.screen_h
		pal    = self._palette(ui)

		# 半透明遮罩
		mask = _alpha_surf(sw, sh)
		mask.fill((0, 0, 0, 175))
		self.screen.blit(mask, (0, 0))

		# 彩色横条
		bar_h = 88
		bar_y = sh // 2 - bar_h // 2
		bar   = _alpha_surf(sw, bar_h)
		bar.fill((*pal["panel_bg"], 230))
		self.screen.blit(bar, (0, bar_y))
		# 顶底边线
		pygame.draw.line(self.screen, pal["accent"], (0, bar_y), (sw, bar_y), 2)
		pygame.draw.line(self.screen, pal["accent"], (0, bar_y + bar_h), (sw, bar_y + bar_h), 2)

		# 主文字
		self._text(sw // 2, sh // 2 - 10, ui.banner_text, self.fonts["title"],
			pal["accent_lite"], center=True)
		self._text(sw // 2, sh // 2 + 22, "点击任意处 / 按键继续…",
			self.fonts["small"], C_GRAY, center=True)

	# ──────────────────── 工具 ───────────────────────

	def _text(self, x, y, text, font, color, center=False):
		surf = font.render(str(text), True, color)
		rect = surf.get_rect(center=(x, y)) if center else surf.get_rect(topleft=(x, y))
		self.screen.blit(surf, rect)

	def _text_on(self, target, x, y, text, font, color, center=False):
		surf = font.render(str(text), True, color)
		rect = surf.get_rect(center=(x, y)) if center else surf.get_rect(topleft=(x, y))
		target.blit(surf, rect)

	def _wrap(self, text, mc):
		lines = []
		while len(text) > mc:
			lines.append(text[:mc]); text = text[mc:]
		if text:
			lines.append(text)
		return lines
 