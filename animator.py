# 血轨：动画管理器 v5
# 四阶段严格串行：
#   ① RANGED  — 远程弹道（移动前，原位射击）
#   ② MOVE    — 棋子位移
#   ③ CLASH   — 碰撞冲突（锁定标记 + 互攻）
#   ④ COMBAT  — 主攻 LUNGE/RECOIL；反击 COUNTER_LUNGE/COUNTER_RECOIL
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
	IDLE           = "idle"
	RANGED         = "ranged"          # ① 远程弹道
	MOVE           = "move"            # ② 棋子位移  0.30s
	SETTLE         = "settle"          # 移动后停顿  0.10s
	CLASH_MARK     = "clash_mark"      # ③ 冲突锁定标记  0.28s
	LUNGE          = "lunge"           # 近战冲刺    0.20s
	RECOIL         = "recoil"          # 弹退         0.18s
	GAP            = "gap"             # 对间停顿    0.06s
	COUNTER_LUNGE  = "counter_lunge"   # ④ 反击冲刺  0.18s
	COUNTER_RECOIL = "counter_recoil"  # 反击弹退    0.15s
	DAMAGE         = "damage"          # 伤害数字浮起 0.70s
	DONE           = "done"


# 阶段显示名（用于底栏标注）
PHASE_STAGE_LABEL = {
	AnimPhase.RANGED:         "① 远程攻击",
	AnimPhase.MOVE:           "② 部队移动",
	AnimPhase.SETTLE:         "② 部队移动",
	AnimPhase.CLASH_MARK:     "③ 冲突对决",
	AnimPhase.LUNGE:          "④ 攻击与反击",
	AnimPhase.RECOIL:         "④ 攻击与反击",
	AnimPhase.GAP:            "④ 攻击与反击",
	AnimPhase.COUNTER_LUNGE:  "④ 攻击与反击",
	AnimPhase.COUNTER_RECOIL: "④ 攻击与反击",
	AnimPhase.DAMAGE:         "结算",
}


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


class CombatPair:
	"""pair_type: 'collision' | 'melee' | 'counter'"""
	def __init__(self, atk_uid, tgt_uid, pair_type="melee"):
		self.atk_uid   = atk_uid
		self.tgt_uid   = tgt_uid
		self.pair_type = pair_type
		self.atk_base  = None   # (float x, float y)
		self.tgt_base  = None
		self.recoil_dir = None  # 归一化 (dx, dy)，tgt 弹退方向


class AnimationManager:
	MOVE_DUR           = 0.30
	SETTLE_DUR         = 0.10
	CLASH_MARK_DUR     = 0.28
	LUNGE_DUR          = 0.20
	RECOIL_DUR         = 0.18
	GAP_DUR            = 0.06
	COUNTER_LUNGE_DUR  = 0.18
	COUNTER_RECOIL_DUR = 0.15
	RANGED_DUR         = 0.40
	DAMAGE_DUR         = 0.70

	def __init__(self):
		self.phase   = AnimPhase.IDLE
		self.timer   = 0.0
		self.visual_pos: dict  = {}
		self.move_data: dict   = {}
		self.final_pos: dict   = {}
		self.hit_uids: set     = set()
		self.dead_uids: set    = set()
		self.damage_tags: list = []
		self.projectiles: list = []
		self.screen_shake      = 0.0
		self.shake_intensity   = 0.0
		self._shake_offset     = (0, 0)
		self._pairs: list      = []
		self._pair_idx: int    = 0
		self._active_hit_uid: int     = -1   # 主攻受击（白闪）
		self._active_counter_uid: int = -1   # 反击受击（蓝闪）

	@property
	def is_playing(self) -> bool:
		return self.phase not in (AnimPhase.IDLE, AnimPhase.DONE)

	def _cur_pair(self):
		if self._pair_idx < len(self._pairs):
			return self._pairs[self._pair_idx]
		return None

	# ─────────────── 初始化 ────────────────────────

	def setup(self, pre_snap: dict, game):
		self.phase  = AnimPhase.IDLE
		self.timer  = 0.0
		self.visual_pos.clear()
		self.move_data.clear()
		self.final_pos.clear()
		self.hit_uids.clear()
		self.dead_uids.clear()
		self.damage_tags.clear()
		self.projectiles.clear()
		self._pairs.clear()
		self._pair_idx = 0
		self._active_hit_uid     = -1
		self._active_counter_uid = -1
		self.screen_shake  = 0.0
		self._shake_offset = (0, 0)

		# 初始视觉坐标 = 移动前位置
		for uid, (px, py, _) in pre_snap.items():
			self.visual_pos[uid] = (float(px), float(py))

		# 最终位置（移动后）
		for uid in pre_snap:
			u = game.get_unit_by_uid(uid)
			if u:
				self.final_pos[uid] = (u.x, u.y)

		# 主攻击事件边界
		main_end = getattr(game, "last_attack_main_end", len(game.last_attack_events))

		# ── 远程抛射体（用 pre_snap 位置，移动前射击）────
		seen_rng = set()
		for atk_uid, tgt_uid, is_rng, _ in game.last_attack_events:
			if not is_rng:
				continue
			key = frozenset([atk_uid, tgt_uid])
			if key in seen_rng:
				continue
			seen_rng.add(key)
			atk = game.get_unit_by_uid(atk_uid)
			tgt = game.get_unit_by_uid(tgt_uid)
			if not atk or not tgt:
				continue
			# 用 pre_snap 坐标（移动前）
			ax, ay = pre_snap.get(atk_uid, (atk.x, atk.y, 0))[:2]
			tx, ty = pre_snap.get(tgt_uid, (tgt.x, tgt.y, 0))[:2]
			is_cannon = "炮" in atk.name or atk.has_trait("投射")
			self.projectiles.append(Projectile(
				atk_uid, tgt_uid,
				float(ax), float(ay), float(tx), float(ty),
				is_cannon=is_cannon,
			))

		# ── 近战对队列：collision → melee → counter ─────
		seen = set()
		collision_pairs, melee_pairs, counter_pairs = [], [], []
		for i, (atk_uid, tgt_uid, is_rng, is_coll) in enumerate(game.last_attack_events):
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
			if is_coll:
				ptype = "collision"
			elif i >= main_end:
				ptype = "counter"
			else:
				ptype = "melee"
			cp = CombatPair(atk_uid, tgt_uid, ptype)
			cp.atk_base = (float(atk.x), float(atk.y))
			cp.tgt_base = (float(tgt.x), float(tgt.y))
			dx = float(tgt.x) - float(atk.x)
			dy = float(tgt.y) - float(atk.y)
			dist = math.hypot(dx, dy)
			cp.recoil_dir = (dx / dist, dy / dist) if dist > 0.01 else (0.0, -1.0)
			if ptype == "collision":
				collision_pairs.append(cp)
			elif ptype == "counter":
				counter_pairs.append(cp)
			else:
				melee_pairs.append(cp)
		self._pairs = collision_pairs + melee_pairs + counter_pairs

		# ── 非战斗单位移动数据 ────────────────────────────
		combat_uids = {cp.atk_uid for cp in self._pairs} | {cp.tgt_uid for cp in self._pairs}
		for uid, (ox, oy, _) in pre_snap.items():
			u = game.get_unit_by_uid(uid)
			if u and uid not in combat_uids and (u.x != ox or u.y != oy):
				self.move_data[uid] = (ox, oy, u.x, u.y)

		# ── 伤害 / 死亡 ──────────────────────────────────
		for uid, (_, _, old_hp) in pre_snap.items():
			u = game.get_unit_by_uid(uid)
			if not u:
				continue
			diff = old_hp - u.hp
			if diff > 0:
				self.hit_uids.add(uid)
				self.damage_tags.append(DamageTag(uid, diff, u.x, u.y))
			elif diff < 0:
				self.damage_tags.append(DamageTag(uid, abs(diff), u.x, u.y, is_heal=True))
			if u.dead:
				self.dead_uids.add(uid)

		if self.dead_uids:
			self.screen_shake    = 0.26
			self.shake_intensity = min(6.0, 2.0 + len(self.dead_uids) * 1.8)

		# ── 决定起始阶段 ─────────────────────────────────
		if self.projectiles:
			self.phase = AnimPhase.RANGED
		else:
			self.phase = AnimPhase.MOVE

	# ─────────────── 帧更新 ────────────────────────

	def update(self, dt: float, game=None) -> bool:
		self.timer += dt

		# 震屏衰减
		if self.screen_shake > 0:
			self.screen_shake = max(0.0, self.screen_shake - dt)
			t   = self.screen_shake / 0.26
			mag = self.shake_intensity * t
			self._shake_offset = (random.uniform(-mag, mag), random.uniform(-mag, mag))
		else:
			self._shake_offset = (0, 0)

		# ① 远程弹道
		if self.phase == AnimPhase.RANGED:
			t = min(1.0, self.timer / self.RANGED_DUR)
			for p in self.projectiles:
				p.progress = t
				if t >= 1.0:
					p.hit = True
			if self.timer >= self.RANGED_DUR:
				self.phase = AnimPhase.MOVE
				self.timer = 0.0

		# ② 棋子位移
		elif self.phase == AnimPhase.MOVE:
			t  = min(1.0, self.timer / self.MOVE_DUR)
			et = _ease_out_back(t) if t < 0.92 else _ease_out_cubic(t)
			for uid, (fx, fy, tx, ty) in self.move_data.items():
				self.visual_pos[uid] = (fx + (tx - fx) * et, fy + (ty - fy) * et)
			if self.timer >= self.MOVE_DUR:
				combat_uids = {cp.atk_uid for cp in self._pairs} | {cp.tgt_uid for cp in self._pairs}
				for uid, pos in self.final_pos.items():
					if uid not in combat_uids:
						self.visual_pos[uid] = (float(pos[0]), float(pos[1]))
				self.phase = AnimPhase.SETTLE
				self.timer = 0.0

		elif self.phase == AnimPhase.SETTLE:
			if self.timer >= self.SETTLE_DUR:
				for uid, pos in self.final_pos.items():
					self.visual_pos[uid] = (float(pos[0]), float(pos[1]))
				self.timer = 0.0
				self._start_next_pair()

		# ③ 冲突锁定标记
		elif self.phase == AnimPhase.CLASH_MARK:
			if self.timer >= self.CLASH_MARK_DUR:
				self.phase = AnimPhase.LUNGE
				self.timer = 0.0

		# ④ 近战冲刺（包含 collision 和 melee）
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
				self.visual_pos[cp.tgt_uid] = (bx + rdx * 0.18 * knock_t, by + rdy * 0.18 * knock_t)
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
				self._start_next_pair()

		# ④ 反击冲刺
		elif self.phase == AnimPhase.COUNTER_LUNGE:
			cp = self._cur_pair()
			if cp:
				t       = min(1.0, self.timer / self.COUNTER_LUNGE_DUR)
				lunge_t = math.sin(t * math.pi)
				bx, by  = cp.atk_base
				tx, ty  = cp.tgt_base
				dx, dy  = tx - bx, ty - by
				dist    = max(0.01, math.hypot(dx, dy))
				self.visual_pos[cp.atk_uid] = (bx + (dx/dist)*0.22*lunge_t, by + (dy/dist)*0.22*lunge_t)
			if self.timer >= self.COUNTER_LUNGE_DUR:
				if cp:
					self.visual_pos[cp.atk_uid] = cp.atk_base
					self._active_counter_uid = cp.tgt_uid
				self.phase = AnimPhase.COUNTER_RECOIL
				self.timer = 0.0

		elif self.phase == AnimPhase.COUNTER_RECOIL:
			cp = self._cur_pair()
			if cp and cp.recoil_dir:
				t        = min(1.0, self.timer / self.COUNTER_RECOIL_DUR)
				knock_t  = math.sin(t * math.pi)
				bx, by   = cp.tgt_base
				rdx, rdy = cp.recoil_dir
				self.visual_pos[cp.tgt_uid] = (bx + rdx * 0.15 * knock_t, by + rdy * 0.15 * knock_t)
			if self.timer >= self.COUNTER_RECOIL_DUR:
				if cp:
					self.visual_pos[cp.tgt_uid] = cp.tgt_base
				self._active_counter_uid = -1
				self.phase = AnimPhase.GAP
				self.timer = 0.0

		elif self.phase == AnimPhase.DAMAGE:
			if self.timer >= self.DAMAGE_DUR:
				self.phase = AnimPhase.DONE
				self.timer = 0.0
				return True

		return False

	def _start_next_pair(self):
		"""SETTLE/GAP 后推进到下一对或 DAMAGE"""
		cp = self._cur_pair()
		if cp is None:
			self.phase = AnimPhase.DAMAGE
			return
		if cp.pair_type == "collision":
			# 先显示锁定标记
			self.phase = AnimPhase.CLASH_MARK
		elif cp.pair_type == "counter":
			self.phase = AnimPhase.COUNTER_LUNGE
		else:
			self.phase = AnimPhase.LUNGE

	# ─────────────── 查询接口 ──────────────────────

	def get_vpos(self, uid: int, default_x: int, default_y: int) -> tuple:
		return self.visual_pos.get(uid, (float(default_x), float(default_y)))

	def get_shake(self) -> tuple:
		return self._shake_offset

	def stage_label(self) -> str:
		return PHASE_STAGE_LABEL.get(self.phase, "")

	def get_clash_pair(self):
		"""返回当前 CLASH_MARK 阶段的对 (atk_uid, tgt_uid, progress) 或 None"""
		if self.phase != AnimPhase.CLASH_MARK:
			return None
		cp = self._cur_pair()
		if not cp:
			return None
		prog = min(1.0, self.timer / self.CLASH_MARK_DUR)
		return (cp.atk_uid, cp.tgt_uid, prog)

	def hit_brightness(self, uid: int) -> float:
		"""白闪（主攻受击）"""
		if uid != self._active_hit_uid:
			return 0.0
		if self.phase == AnimPhase.RECOIL:
			t = min(1.0, self.timer / self.RECOIL_DUR)
			return max(0.0, math.sin(t * math.pi * 1.8) * (1.0 - t * 0.5))
		return 0.0

	def counter_brightness(self, uid: int) -> float:
		"""蓝闪（反击受击）"""
		if uid != self._active_counter_uid:
			return 0.0
		if self.phase == AnimPhase.COUNTER_RECOIL:
			t = min(1.0, self.timer / self.COUNTER_RECOIL_DUR)
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
			AnimPhase.RANGED,
			AnimPhase.MOVE, AnimPhase.SETTLE,
			AnimPhase.CLASH_MARK,
			AnimPhase.LUNGE, AnimPhase.RECOIL, AnimPhase.GAP,
			AnimPhase.COUNTER_LUNGE, AnimPhase.COUNTER_RECOIL,
		)
		if self.phase in alive_phases:
			return 200
		if self.phase == AnimPhase.DAMAGE:
			t = min(1.0, self.timer / self.DAMAGE_DUR)
			return max(0, int(200 * (1.0 - t ** 0.7)))
		return 0

	def current_lunge_uids(self) -> set:
		cp = self._cur_pair()
		if cp and self.phase in (AnimPhase.LUNGE, AnimPhase.COUNTER_LUNGE):
			return {cp.atk_uid}
		return set()
