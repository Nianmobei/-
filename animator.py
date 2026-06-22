# 血轨：动画管理器 v3
# 流程：MOVE → COMBAT（近战分批冲刺+受击）→ RANGED（抛射体）→ DAMAGE → DONE
# 无冲突单位在 MOVE 阶段独立移动，战斗单位等到 COMBAT 阶段才表现攻击

import math
import random


def _ease_out_cubic(t: float) -> float:
	return 1.0 - (1.0 - t) ** 3


def _ease_out_back(t: float) -> float:
	c1 = 1.70158
	c3 = c1 + 1.0
	return 1.0 + c3 * ((t - 1.0) ** 3) + c1 * ((t - 1.0) ** 2)


class AnimPhase:
	IDLE    = "idle"
	MOVE    = "move"      # 0.30s：无冲突单位滑动到位
	SETTLE  = "settle"    # 0.10s：所有单位落位停顿
	COMBAT  = "combat"    # 0.22s×N批：近战单位依次冲刺+受击
	RANGED  = "ranged"    # 0.40s：远程抛射体飞行
	FLASH   = "flash"     # 0.28s：受击闪白
	DAMAGE  = "damage"    # 0.70s：伤害数字浮起
	DONE    = "done"


class DamageTag:
	def __init__(self, uid: int, amount: int, gx: int, gy: int, is_heal: bool = False):
		self.uid     = uid
		self.amount  = amount
		self.gx      = gx
		self.gy      = gy
		self.is_heal = is_heal


class Projectile:
	"""远程抛射体（弩箭/炮弹）"""
	def __init__(self, atk_uid, tgt_uid, sx, sy, tx, ty, is_cannon: bool = False):
		self.atk_uid   = atk_uid
		self.tgt_uid   = tgt_uid
		self.sx, self.sy = sx, sy          # 起点（格坐标）
		self.tx, self.ty = tx, ty          # 终点（格坐标）
		self.progress    = 0.0             # 0→1
		self.is_cannon   = is_cannon       # True=炮弹（抛物线+大），False=弩箭（直线+小）
		self.hit         = False


class AnimationManager:
	MOVE_DUR    = 0.30
	SETTLE_DUR  = 0.10
	COMBAT_STEP = 0.22   # 每批近战动画时长
	RANGED_DUR  = 0.40
	FLASH_DUR   = 0.28
	DAMAGE_DUR  = 0.70

	def __init__(self):
		self.phase  = AnimPhase.IDLE
		self.timer  = 0.0
		self.visual_pos: dict  = {}
		self.move_data: dict   = {}       # uid→(fx,fy,tx,ty) 非冲突移动
		self.final_pos: dict   = {}       # uid→(x,y) 最终网格位置
		self.hit_uids: set     = set()
		self.dead_uids: set    = set()
		self.damage_tags: list = []
		self.screen_shake      = 0.0
		self.shake_intensity   = 0.0
		self._shake_offset     = (0, 0)

		# 近战批次：list of list of (atk_uid, tgt_uid)
		self._combat_batches: list  = []
		self._combat_idx: int       = 0    # 当前批次下标
		# 当前批次冲刺进度（uid→目标格）
		self._lunge_data: dict      = {}
		# 远程抛射体列表
		self.projectiles: list      = []
		# 受击后退：uid → (dir_x, dir_y) 归一化，背离攻击方向
		self._knockback: dict       = {}

	@property
	def is_playing(self) -> bool:
		return self.phase not in (AnimPhase.IDLE, AnimPhase.DONE)

	# ─────────────── 初始化 ───────────────────

	def setup(self, pre_snap: dict, game):
		"""
		pre_snap: {uid: (x, y, hp)}   执行前快照
		game:     execute_turn() 已调用后的状态
		"""
		self.phase  = AnimPhase.MOVE
		self.timer  = 0.0
		self.visual_pos.clear()
		self.move_data.clear()
		self.final_pos.clear()
		self.hit_uids.clear()
		self.dead_uids.clear()
		self.damage_tags.clear()
		self._combat_batches.clear()
		self._combat_idx = 0
		self._lunge_data.clear()
		self.projectiles.clear()
		self._knockback.clear()
		self.screen_shake   = 0.0
		self._shake_offset  = (0, 0)

		# 视觉初始位置 = 执行前位置
		for uid, (px, py, _) in pre_snap.items():
			self.visual_pos[uid] = (float(px), float(py))

		# 最终网格位置
		for uid, (old_x, old_y, _) in pre_snap.items():
			u = game.get_unit_by_uid(uid)
			if u is None:
				continue
			self.final_pos[uid] = (u.x, u.y)

		# 分类：参与战斗的 uid 集合（来自 last_attack_events）
		combat_uids = set()
		for atk_uid, tgt_uid, is_rng, is_col in game.last_attack_events:
			if not is_rng:
				combat_uids.add(atk_uid)
				combat_uids.add(tgt_uid)

		# 非战斗单位：移动动画
		for uid, (old_x, old_y, _) in pre_snap.items():
			u = game.get_unit_by_uid(uid)
			if u is None or uid in combat_uids:
				continue
			if u.x != old_x or u.y != old_y:
				self.move_data[uid] = (old_x, old_y, u.x, u.y)

		# 受击 / 死亡
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

		if self.dead_uids:
			self.screen_shake    = 0.24
			self.shake_intensity = min(6.0, 2.0 + len(self.dead_uids) * 1.8)

		# 构建近战攻击批次
		# 碰撞事件一批，行动阶段按攻击者速度分批（同速一批）
		collision_pairs = []
		action_events   = []
		for evt in game.last_attack_events:
			atk_uid, tgt_uid, is_rng, is_col = evt
			if is_rng:
				continue
			if is_col:
				pair = frozenset([atk_uid, tgt_uid])
				if pair not in {frozenset(p) for p in collision_pairs}:
					collision_pairs.append((atk_uid, tgt_uid))
			else:
				action_events.append((atk_uid, tgt_uid))

		if collision_pairs:
			self._combat_batches.append(collision_pairs)

		# 行动阶段去重后按先后顺序分批（同一目标的多次攻击合并到一批）
		seen_pairs = set()
		batch_cur  = []
		for atk_uid, tgt_uid in action_events:
			pair = frozenset([atk_uid, tgt_uid])
			if pair in seen_pairs:
				if batch_cur:
					self._combat_batches.append(batch_cur)
				batch_cur = [(atk_uid, tgt_uid)]
				seen_pairs = {pair}
			else:
				batch_cur.append((atk_uid, tgt_uid))
				seen_pairs.add(pair)
		if batch_cur:
			self._combat_batches.append(batch_cur)

		# 远程抛射体
		seen_rng = set()
		for atk_uid, tgt_uid, is_rng, _ in game.last_attack_events:
			if not is_rng:
				continue
			pair = frozenset([atk_uid, tgt_uid])
			if pair in seen_rng:
				continue
			seen_rng.add(pair)
			atk = game.get_unit_by_uid(atk_uid)
			tgt = game.get_unit_by_uid(tgt_uid)
			if atk and tgt:
				is_cannon = atk.has_trait("投射") or atk.has_trait("炮兽") or "炮" in atk.name
				self.projectiles.append(Projectile(
					atk_uid, tgt_uid,
					float(atk.x), float(atk.y),
					float(tgt.x), float(tgt.y),
					is_cannon=is_cannon,
				))

		# 初始化第一批近战冲刺
		if self._combat_batches:
			self._start_combat_batch(0, game)

		# 受击后退方向：每个被击单位取所有攻击者位置均值，计算背离方向
		tgt_attackers: dict = {}   # tgt_uid → [(atk_x, atk_y), ...]
		for atk_uid, tgt_uid, is_rng, _ in game.last_attack_events:
			atk = game.get_unit_by_uid(atk_uid)
			if atk is None:
				continue
			tgt_attackers.setdefault(tgt_uid, []).append((float(atk.x), float(atk.y)))
		for tgt_uid, atk_positions in tgt_attackers.items():
			tgt = game.get_unit_by_uid(tgt_uid)
			if tgt is None:
				continue
			# 均值方向
			ax = sum(p[0] for p in atk_positions) / len(atk_positions)
			ay = sum(p[1] for p in atk_positions) / len(atk_positions)
			dx, dy = float(tgt.x) - ax, float(tgt.y) - ay
			dist   = math.hypot(dx, dy)
			if dist < 0.01:
				dx, dy = 0.0, -1.0   # 正上方退
			else:
				dx, dy = dx / dist, dy / dist
			self._knockback[tgt_uid] = (dx, dy)

	def _start_combat_batch(self, idx, game):
		self._lunge_data.clear()
		if idx >= len(self._combat_batches):
			return
		batch = self._combat_batches[idx]
		done_attackers = set()
		for atk_uid, tgt_uid in batch:
			if atk_uid in done_attackers:
				continue
			done_attackers.add(atk_uid)
			atk = game.get_unit_by_uid(atk_uid)
			tgt = game.get_unit_by_uid(tgt_uid)
			if atk and tgt:
				self._lunge_data[atk_uid] = (float(tgt.x), float(tgt.y))

	# ─────────────── 帧更新 ───────────────────

	def update(self, dt: float, game=None) -> bool:
		"""推进动画；完成时返回 True。game 用于批次切换时重新查询位置。"""
		self.timer += dt

		# 震屏衰减
		if self.screen_shake > 0:
			self.screen_shake = max(0.0, self.screen_shake - dt)
			t = self.screen_shake / 0.24
			mag = self.shake_intensity * t
			self._shake_offset = (random.uniform(-mag, mag), random.uniform(-mag, mag))
		else:
			self._shake_offset = (0, 0)

		if self.phase == AnimPhase.MOVE:
			t  = min(1.0, self.timer / self.MOVE_DUR)
			et = _ease_out_back(t) if t < 0.92 else _ease_out_cubic(t)
			for uid, (fx, fy, tx, ty) in self.move_data.items():
				self.visual_pos[uid] = (fx + (tx - fx) * et, fy + (ty - fy) * et)
			if self.timer >= self.MOVE_DUR:
				# 非战斗单位落位
				for uid, (tx, ty) in self.final_pos.items():
					if uid not in {u for batch in self._combat_batches for pair in batch for u in pair}:
						self.visual_pos[uid] = (float(tx), float(ty))
				self.phase = AnimPhase.SETTLE
				self.timer = 0.0

		elif self.phase == AnimPhase.SETTLE:
			if self.timer >= self.SETTLE_DUR:
				# 把战斗单位也移到最终位置（它们在 MOVE 阶段未参与滑动）
				for uid, pos in self.final_pos.items():
					self.visual_pos[uid] = (float(pos[0]), float(pos[1]))
				if self._combat_batches:
					self.phase = AnimPhase.COMBAT
				elif self.projectiles:
					self.phase = AnimPhase.RANGED
				else:
					self.phase = AnimPhase.FLASH
				self.timer = 0.0

		elif self.phase == AnimPhase.COMBAT:
			t       = min(1.0, self.timer / self.COMBAT_STEP)
			lunge_t = math.sin(t * math.pi)
			for uid, (tgx, tgy) in self._lunge_data.items():
				base = self.final_pos.get(uid)
				if base:
					bx, by = float(base[0]), float(base[1])
					dx, dy = tgx - bx, tgy - by
					dist   = max(0.01, math.hypot(dx, dy))
					ox     = (dx / dist) * 0.28 * lunge_t
					oy     = (dy / dist) * 0.28 * lunge_t
					self.visual_pos[uid] = (bx + ox, by + oy)

			if self.timer >= self.COMBAT_STEP:
				# 本批结束，复位
				for uid in self._lunge_data:
					base = self.final_pos.get(uid)
					if base:
						self.visual_pos[uid] = (float(base[0]), float(base[1]))
				self._combat_idx += 1
				if self._combat_idx < len(self._combat_batches):
					if game:
						self._start_combat_batch(self._combat_idx, game)
					self.timer = 0.0
					# 继续 COMBAT
				else:
					self._lunge_data.clear()
					if self.projectiles:
						self.phase = AnimPhase.RANGED
					else:
						self.phase = AnimPhase.FLASH
					self.timer = 0.0

		elif self.phase == AnimPhase.RANGED:
			t = min(1.0, self.timer / self.RANGED_DUR)
			for p in self.projectiles:
				p.progress = t
				if t >= 1.0:
					p.hit = True
			if self.timer >= self.RANGED_DUR:
				self.phase = AnimPhase.FLASH
				self.timer = 0.0

		elif self.phase == AnimPhase.FLASH:
			# 受击后退：sin 曲线，峰值 0.18 格，然后弹回
			t = min(1.0, self.timer / self.FLASH_DUR)
			knock_t = math.sin(t * math.pi)   # 0→peak→0
			for uid, (dx, dy) in self._knockback.items():
				base = self.final_pos.get(uid)
				if base:
					bx, by = float(base[0]), float(base[1])
					self.visual_pos[uid] = (
						bx + dx * 0.18 * knock_t,
						by + dy * 0.18 * knock_t,
					)
			if self.timer >= self.FLASH_DUR:
				# 复位到最终格
				for uid in self._knockback:
					base = self.final_pos.get(uid)
					if base:
						self.visual_pos[uid] = (float(base[0]), float(base[1]))
				self.phase = AnimPhase.DAMAGE
				self.timer = 0.0

		elif self.phase == AnimPhase.DAMAGE:
			if self.timer >= self.DAMAGE_DUR:
				self.phase = AnimPhase.DONE
				self.timer = 0.0
				return True

		return False

	# ─────────────── 查询接口 ────────────────────

	def get_vpos(self, uid: int, default_x: int, default_y: int) -> tuple:
		return self.visual_pos.get(uid, (float(default_x), float(default_y)))

	def get_shake(self) -> tuple:
		return self._shake_offset

	def hit_brightness(self, uid: int) -> float:
		"""受击闪白：FLASH阶段 + RANGED命中后"""
		active = (
			self.phase == AnimPhase.FLASH
			or (self.phase == AnimPhase.RANGED
				and any(p.hit and p.tgt_uid == uid for p in self.projectiles))
		)
		if active and uid in self.hit_uids:
			t = min(1.0, self.timer / self.FLASH_DUR)
			return max(0.0, math.sin(t * math.pi * 2.0) * (1.0 - t * 0.6))
		return 0.0

	def damage_alpha_offset(self) -> tuple:
		if self.phase == AnimPhase.DAMAGE:
			t     = self.timer / self.DAMAGE_DUR
			alpha = max(0, int(255 * (1.0 - t ** 1.2)))
			y_off = -int(t * 42)
			return alpha, y_off
		return 0, 0

	def dead_alpha(self, uid: int) -> int:
		if uid not in self.dead_uids:
			return 255
		if self.phase in (AnimPhase.MOVE, AnimPhase.SETTLE, AnimPhase.COMBAT, AnimPhase.RANGED, AnimPhase.FLASH):
			return 200
		if self.phase == AnimPhase.DAMAGE:
			t = min(1.0, self.timer / self.DAMAGE_DUR)
			return max(0, int(200 * (1.0 - t ** 0.7)))
		return 0

	def current_lunge_uids(self) -> set:
		"""当前正在冲刺的攻击方 uid 集合（供渲染器高亮）"""
		return set(self._lunge_data.keys())
