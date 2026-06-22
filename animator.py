# 血轨：动画管理器 v4
# 严格串行：MOVE → SETTLE → (LUNGE→RECOIL)×N对 → RANGED → DAMAGE → DONE
# 每对战斗独立播放，绝不同时

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
	MOVE    = "move"      # 0.30s：无冲突单位滑到位
	SETTLE  = "settle"    # 0.10s：所有单位落位停顿
	LUNGE   = "lunge"     # 0.20s：当前对的攻击方冲向防守方
	RECOIL  = "recoil"    # 0.18s：防守方弹退回位
	GAP     = "gap"       # 0.06s：对间间隔
	RANGED  = "ranged"    # 0.38s：远程抛射体飞行
	DAMAGE  = "damage"    # 0.70s：所有伤害数字浮起
	DONE    = "done"


class DamageTag:
	def __init__(self, uid: int, amount: int, gx: int, gy: int, is_heal: bool = False):
		self.uid     = uid
		self.amount  = amount
		self.gx      = gx
		self.gy      = gy
		self.is_heal = is_heal


class Projectile:
	def __init__(self, atk_uid, tgt_uid, sx, sy, tx, ty, is_cannon: bool = False):
		self.atk_uid = atk_uid
		self.tgt_uid = tgt_uid
		self.sx, self.sy = sx, sy
		self.tx, self.ty = tx, ty
		self.progress    = 0.0
		self.is_cannon   = is_cannon
		self.hit         = False


# 单对战斗记录
class CombatPair:
	def __init__(self, atk_uid, tgt_uid):
		self.atk_uid = atk_uid
		self.tgt_uid = tgt_uid
		# 计算时填入
		self.atk_base  = None   # (float x, float y)
		self.tgt_base  = None
		self.recoil_dir = None  # (dx, dy) 归一化，tgt 弹退方向


class AnimationManager:
	MOVE_DUR    = 0.30
	SETTLE_DUR  = 0.10
	LUNGE_DUR   = 0.20
	RECOIL_DUR  = 0.18
	GAP_DUR     = 0.06
	RANGED_DUR  = 0.38
	DAMAGE_DUR  = 0.70

	def __init__(self):
		self.phase   = AnimPhase.IDLE
		self.timer   = 0.0
		self.visual_pos: dict  = {}
		self.move_data: dict   = {}   # uid→(fx,fy,tx,ty) 非战斗单位
		self.final_pos: dict   = {}   # uid→(x,y)
		self.hit_uids: set     = set()
		self.dead_uids: set    = set()
		self.damage_tags: list = []
		self.projectiles: list = []
		self.screen_shake      = 0.0
		self.shake_intensity   = 0.0
		self._shake_offset     = (0, 0)
		# 串行战斗队列
		self._pairs: list      = []   # list[CombatPair]，按顺序
		self._pair_idx: int    = 0
		# 当前对的活跃闪白 uid（RECOIL阶段用）
		self._active_hit_uid: int = -1

	@property
	def is_playing(self) -> bool:
		return self.phase not in (AnimPhase.IDLE, AnimPhase.DONE)

	def _cur_pair(self):
		if self._pair_idx < len(self._pairs):
			return self._pairs[self._pair_idx]
		return None

	# ─────────────── 初始化 ───────────────────

	def setup(self, pre_snap: dict, game):
		self.phase   = AnimPhase.MOVE
		self.timer   = 0.0
		self.visual_pos.clear()
		self.move_data.clear()
		self.final_pos.clear()
		self.hit_uids.clear()
		self.dead_uids.clear()
		self.damage_tags.clear()
		self.projectiles.clear()
		self._pairs.clear()
		self._pair_idx = 0
		self._active_hit_uid = -1
		self.screen_shake   = 0.0
		self._shake_offset  = (0, 0)

		for uid, (px, py, _) in pre_snap.items():
			self.visual_pos[uid] = (float(px), float(py))

		for uid, (_, _, _) in pre_snap.items():
			u = game.get_unit_by_uid(uid)
			if u:
				self.final_pos[uid] = (u.x, u.y)

		# 战斗 uid 集合（不参与移动动画）
		combat_uids = set()
		for atk_uid, tgt_uid, is_rng, _ in game.last_attack_events:
			if not is_rng:
				combat_uids.add(atk_uid)
				combat_uids.add(tgt_uid)

		# 非战斗移动
		for uid, (ox, oy, _) in pre_snap.items():
			u = game.get_unit_by_uid(uid)
			if u and uid not in combat_uids and (u.x != ox or u.y != oy):
				self.move_data[uid] = (ox, oy, u.x, u.y)

		# 受击 / 死亡 / 伤害数字
		for uid, (_, _, old_hp) in pre_snap.items():
			u = game.get_unit_by_uid(uid)
			if not u:
				continue
			diff = old_hp - u.hp
			if diff > 0:
				self.hit_uids.add(uid)
				self.damage_tags.append(DamageTag(uid, diff, u.x, u.y))
			if u.dead:
				self.dead_uids.add(uid)

		if self.dead_uids:
			self.screen_shake    = 0.26
			self.shake_intensity = min(6.0, 2.0 + len(self.dead_uids) * 1.8)

		# 构建近战对队列（每对独立，严格去重）
		seen = set()
		for atk_uid, tgt_uid, is_rng, _ in game.last_attack_events:
			if is_rng:
				continue
			key = (atk_uid, tgt_uid)
			if key in seen:
				continue
			seen.add(key)
			atk = game.get_unit_by_uid(atk_uid)
			tgt = game.get_unit_by_uid(tgt_uid)
			if not atk or not tgt:
				continue
			cp = CombatPair(atk_uid, tgt_uid)
			cp.atk_base  = (float(atk.x), float(atk.y))
			cp.tgt_base  = (float(tgt.x), float(tgt.y))
			# 弹退方向：目标背离攻击者
			dx = float(tgt.x) - float(atk.x)
			dy = float(tgt.y) - float(atk.y)
			dist = math.hypot(dx, dy)
			if dist < 0.01:
				dx, dy = 0.0, -1.0
			else:
				dx, dy = dx / dist, dy / dist
			cp.recoil_dir = (dx, dy)
			self._pairs.append(cp)

		# 远程抛射体
		seen_rng = set()
		for atk_uid, tgt_uid, is_rng, _ in game.last_attack_events:
			if not is_rng:
				continue
			pair_key = frozenset([atk_uid, tgt_uid])
			if pair_key in seen_rng:
				continue
			seen_rng.add(pair_key)
			atk = game.get_unit_by_uid(atk_uid)
			tgt = game.get_unit_by_uid(tgt_uid)
			if atk and tgt:
				is_cannon = "炮" in atk.name or atk.has_trait("投射")
				self.projectiles.append(Projectile(
					atk_uid, tgt_uid,
					float(atk.x), float(atk.y),
					float(tgt.x), float(tgt.y),
					is_cannon=is_cannon,
				))

	# ─────────────── 帧更新 ───────────────────

	def update(self, dt: float, game=None) -> bool:
		self.timer += dt

		# 震屏衰减
		if self.screen_shake > 0:
			self.screen_shake = max(0.0, self.screen_shake - dt)
			t = self.screen_shake / 0.26
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
				combat_uids = {cp.atk_uid for cp in self._pairs} | {cp.tgt_uid for cp in self._pairs}
				for uid, pos in self.final_pos.items():
					if uid not in combat_uids:
						self.visual_pos[uid] = (float(pos[0]), float(pos[1]))
				self.phase = AnimPhase.SETTLE
				self.timer = 0.0

		elif self.phase == AnimPhase.SETTLE:
			if self.timer >= self.SETTLE_DUR:
				# 战斗单位也落位（它们之前一直在原位）
				for uid, pos in self.final_pos.items():
					self.visual_pos[uid] = (float(pos[0]), float(pos[1]))
				self.timer = 0.0
				self._advance_combat_or_ranged()

		elif self.phase == AnimPhase.LUNGE:
			cp = self._cur_pair()
			if cp:
				t       = min(1.0, self.timer / self.LUNGE_DUR)
				lunge_t = math.sin(t * math.pi)
				bx, by  = cp.atk_base
				tx, ty  = cp.tgt_base
				dx, dy  = tx - bx, ty - by
				dist    = max(0.01, math.hypot(dx, dy))
				ox      = (dx / dist) * 0.28 * lunge_t
				oy      = (dy / dist) * 0.28 * lunge_t
				self.visual_pos[cp.atk_uid] = (bx + ox, by + oy)
			if self.timer >= self.LUNGE_DUR:
				if cp:
					self.visual_pos[cp.atk_uid] = cp.atk_base
					self._active_hit_uid = cp.tgt_uid
				self.phase = AnimPhase.RECOIL
				self.timer = 0.0

		elif self.phase == AnimPhase.RECOIL:
			cp = self._cur_pair()
			if cp and cp.recoil_dir:
				t       = min(1.0, self.timer / self.RECOIL_DUR)
				knock_t = math.sin(t * math.pi)
				bx, by  = cp.tgt_base
				rdx, rdy = cp.recoil_dir
				self.visual_pos[cp.tgt_uid] = (
					bx + rdx * 0.18 * knock_t,
					by + rdy * 0.18 * knock_t,
				)
			if self.timer >= self.RECOIL_DUR:
				if cp:
					self.visual_pos[cp.tgt_uid] = cp.tgt_base
				self._active_hit_uid = -1
				self.phase = AnimPhase.GAP
				self.timer = 0.0

		elif self.phase == AnimPhase.GAP:
			if self.timer >= self.GAP_DUR:
				self._pair_idx += 1
				self.timer = 0.0
				self._advance_combat_or_ranged()

		elif self.phase == AnimPhase.RANGED:
			t = min(1.0, self.timer / self.RANGED_DUR)
			for p in self.projectiles:
				p.progress = t
				if t >= 1.0:
					p.hit = True
			if self.timer >= self.RANGED_DUR:
				self.phase = AnimPhase.DAMAGE
				self.timer = 0.0

		elif self.phase == AnimPhase.DAMAGE:
			if self.timer >= self.DAMAGE_DUR:
				self.phase = AnimPhase.DONE
				self.timer = 0.0
				return True

		return False

	def _advance_combat_or_ranged(self):
		"""从 SETTLE 或 GAP 后决定下一阶段"""
		if self._pair_idx < len(self._pairs):
			self.phase = AnimPhase.LUNGE
		elif self.projectiles:
			self.phase = AnimPhase.RANGED
		else:
			self.phase = AnimPhase.DAMAGE

	# ─────────────── 查询接口 ────────────────────

	def get_vpos(self, uid: int, default_x: int, default_y: int) -> tuple:
		return self.visual_pos.get(uid, (float(default_x), float(default_y)))

	def get_shake(self) -> tuple:
		return self._shake_offset

	def hit_brightness(self, uid: int) -> float:
		"""受击闪白：当前对的防守方在 RECOIL 阶段闪白"""
		if uid != self._active_hit_uid:
			return 0.0
		if self.phase == AnimPhase.RECOIL:
			t = min(1.0, self.timer / self.RECOIL_DUR)
			return max(0.0, math.sin(t * math.pi * 1.8) * (1.0 - t * 0.5))
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
		alive_phases = (
			AnimPhase.MOVE, AnimPhase.SETTLE,
			AnimPhase.LUNGE, AnimPhase.RECOIL, AnimPhase.GAP,
			AnimPhase.RANGED,
		)
		if self.phase in alive_phases:
			return 200
		if self.phase == AnimPhase.DAMAGE:
			t = min(1.0, self.timer / self.DAMAGE_DUR)
			return max(0, int(200 * (1.0 - t ** 0.7)))
		return 0

	def current_lunge_uids(self) -> set:
		cp = self._cur_pair()
		if cp and self.phase == AnimPhase.LUNGE:
			return {cp.atk_uid}
		return set()
