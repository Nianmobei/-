# 血轨：动画管理器
# 驱动移动滑动、攻击冲刺、受击闪烁、伤害数字浮动

import math


def _ease_out_cubic(t: float) -> float:
	return 1.0 - (1.0 - t) ** 3


def _ease_in_out(t: float) -> float:
	return t * t * (3 - 2 * t)


class AnimPhase:
	IDLE   = "idle"
	MOVE   = "move"    # 0.38s：棋子滑向目标
	LUNGE  = "lunge"   # 0.18s：攻击方短促冲刺
	FLASH  = "flash"   # 0.28s：受击闪白
	DAMAGE = "damage"  # 0.65s：伤害数字浮起
	DONE   = "done"


class DamageTag:
	def __init__(self, uid: int, amount: int, gx: int, gy: int):
		self.uid    = uid
		self.amount = amount
		self.gx     = gx
		self.gy     = gy


class AnimationManager:
	MOVE_DUR   = 0.38
	LUNGE_DUR  = 0.18
	FLASH_DUR  = 0.28
	DAMAGE_DUR = 0.65

	def __init__(self):
		self.phase  = AnimPhase.IDLE
		self.timer  = 0.0
		# uid -> (float gx, float gy)
		self.visual_pos: dict  = {}
		# uid -> (from_x, from_y, to_x, to_y)
		self.move_data: dict   = {}
		# uid -> (target_gx, target_gy)
		self.lunge_data: dict  = {}
		# uid -> base (gx, gy) after move
		self.final_pos: dict   = {}
		self.hit_uids: set     = set()
		self.dead_uids: set    = set()
		self.damage_tags: list = []

	@property
	def is_playing(self) -> bool:
		return self.phase not in (AnimPhase.IDLE, AnimPhase.DONE)

	# ─────────────── 初始化 ───────────────────

	def setup(self, pre_snap: dict, game):
		"""
		pre_snap: {uid: (x, y, hp)}
		game: execute_turn() 已执行后的 GameState
		"""
		self.phase  = AnimPhase.MOVE
		self.timer  = 0.0
		self.visual_pos.clear()
		self.move_data.clear()
		self.lunge_data.clear()
		self.final_pos.clear()
		self.hit_uids.clear()
		self.dead_uids.clear()
		self.damage_tags.clear()

		# 从 PRE 状态初始化视觉位置
		for uid, (px, py, php) in pre_snap.items():
			self.visual_pos[uid] = (float(px), float(py))

		# 构建移动动画
		for uid, (old_x, old_y, old_hp) in pre_snap.items():
			u = game.get_unit_by_uid(uid)
			if u is None:
				continue
			self.final_pos[uid] = (u.x, u.y)
			if u.x != old_x or u.y != old_y:
				self.move_data[uid] = (old_x, old_y, u.x, u.y)

		# 构建受击 / 伤害 / 死亡
		for uid, (old_x, old_y, old_hp) in pre_snap.items():
			u = game.get_unit_by_uid(uid)
			if u is None:
				continue
			diff = old_hp - u.hp
			if diff > 0:
				self.hit_uids.add(uid)
				self.damage_tags.append(DamageTag(uid, diff, u.x, u.y))
			if u.dead:
				self.dead_uids.add(uid)

		# 构建攻击冲刺：HP 下降的对手附近非受伤单位视为攻击方
		hit_positions = {uid: (game.get_unit_by_uid(uid).x, game.get_unit_by_uid(uid).y)
			for uid in self.hit_uids if game.get_unit_by_uid(uid)}
		for u in game.alive_units():
			if u.uid in self.hit_uids:
				continue
			if u.is_embryo:
				continue
			best_dist, best_target = 999, None
			for huid, (hx, hy) in hit_positions.items():
				hu = game.get_unit_by_uid(huid)
				if hu and hu.faction != u.faction:
					d = abs(u.x - hx) + abs(u.y - hy)
					if d <= 2 and d < best_dist:
						best_dist, best_target = d, (hx, hy)
			if best_target:
				self.lunge_data[u.uid] = best_target

	# ─────────────── 帧更新 ───────────────────

	def update(self, dt: float) -> bool:
		"""推进动画；完成时返回 True"""
		self.timer += dt

		if self.phase == AnimPhase.MOVE:
			t = min(1.0, self.timer / self.MOVE_DUR)
			et = _ease_out_cubic(t)
			for uid, (fx, fy, tx, ty) in self.move_data.items():
				self.visual_pos[uid] = (fx + (tx - fx) * et, fy + (ty - fy) * et)
			if self.timer >= self.MOVE_DUR:
				for uid, (tx, ty) in self.final_pos.items():
					self.visual_pos[uid] = (float(tx), float(ty))
				self.phase = AnimPhase.LUNGE
				self.timer = 0.0

		elif self.phase == AnimPhase.LUNGE:
			t = min(1.0, self.timer / self.LUNGE_DUR)
			lunge_t = math.sin(t * math.pi)   # 0 → peak → 0
			for uid, (tgx, tgy) in self.lunge_data.items():
				base = self.final_pos.get(uid)
				if base:
					bx, by = float(base[0]), float(base[1])
					dx, dy = tgx - bx, tgy - by
					dist = max(0.01, math.hypot(dx, dy))
					ox = (dx / dist) * 0.32 * lunge_t
					oy = (dy / dist) * 0.32 * lunge_t
					self.visual_pos[uid] = (bx + ox, by + oy)
			if self.timer >= self.LUNGE_DUR:
				for uid in self.lunge_data:
					base = self.final_pos.get(uid)
					if base:
						self.visual_pos[uid] = (float(base[0]), float(base[1]))
				self.phase = AnimPhase.FLASH
				self.timer = 0.0

		elif self.phase == AnimPhase.FLASH:
			if self.timer >= self.FLASH_DUR:
				self.phase = AnimPhase.DAMAGE
				self.timer = 0.0

		elif self.phase == AnimPhase.DAMAGE:
			if self.timer >= self.DAMAGE_DUR:
				self.phase = AnimPhase.DONE
				self.timer = 0.0
				return True

		return False

	# ─────────────── 查询接口（供渲染器） ────────────────────

	def get_vpos(self, uid: int, default_x: int, default_y: int) -> tuple:
		return self.visual_pos.get(uid, (float(default_x), float(default_y)))

	def hit_brightness(self, uid: int) -> float:
		"""0~1：受击闪白亮度"""
		if self.phase == AnimPhase.FLASH and uid in self.hit_uids:
			t = self.timer / self.FLASH_DUR
			return max(0.0, math.sin(t * math.pi * 2.5) * (1.0 - t))
		return 0.0

	def damage_alpha_offset(self) -> tuple:
		"""(alpha 0~255, y_offset px) 伤害数字浮动状态"""
		if self.phase == AnimPhase.DAMAGE:
			t = self.timer / self.DAMAGE_DUR
			alpha   = max(0, int(255 * (1.0 - t ** 1.5)))
			y_off   = -int(t * 36)
			return alpha, y_off
		return 0, 0

	def dead_alpha(self, uid: int) -> int:
		if uid not in self.dead_uids:
			return 255
		if self.phase in (AnimPhase.MOVE, AnimPhase.LUNGE, AnimPhase.FLASH):
			return 200
		if self.phase == AnimPhase.DAMAGE:
			t = min(1.0, self.timer / self.DAMAGE_DUR)
			return max(0, int(200 * (1.0 - t)))
		return 0
