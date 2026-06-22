# 血轨：核心游戏引擎（菱形范围移动 + 修复防御/驻扎）

from constants import *
from unit import Unit, UNIT_TEMPLATES
from effects import EffectManager


def manhattan(ax, ay, bx, by):
	return abs(ax - bx) + abs(ay - by)


def in_bounds(x, y, gs):
	return 0 <= x < gs and 0 <= y < gs


def adjacent_units(unit, all_units):
	return [u for u in all_units
		if not u.dead and u.uid != unit.uid
		and manhattan(unit.x, unit.y, u.x, u.y) == 1]


# ─────────── 占领状态 ────────────────────────

class BaseState:
	def __init__(self, owner_faction):
		self.owner        = owner_faction
		self.occupier     = None
		self.occupy_count = 0

	def update(self, units_on, effect_rift, log, bpos):
		real     = [u for u in units_on if not u.is_embryo]
		factions = set(u.faction for u in units_on)

		if len(factions) > 1:
			self.occupier     = None
			self.occupy_count = 0
			log.append(f"⚡ 本阵{bpos} 双方同时在场，占领清零")
			return

		if not units_on:
			return

		faction = list(factions)[0]
		if faction != self.occupier:
			self.occupier     = faction
			self.occupy_count = 0
			name = "红方" if faction == FACTION_RED else "灾方"
			log.append(f"🏳️ {name} 夺回本阵{bpos}")

		if [u for u in real if u.faction == faction] and not effect_rift:
			self.occupy_count += 1
			name = "红方" if self.occupier == FACTION_RED else "灾方"
			log.append(f"🚩 {name} 占领本阵{bpos} 第{self.occupy_count}回合")
			for u in real:
				if u.level == 1:
					u.kills += 1
		elif effect_rift:
			log.append(f"🔒 裂痕：本阵{bpos} 不可占领")

	def winner(self):
		if self.occupy_count < 2 or self.occupier is None:
			return None
		if self.owner is None:
			return self.occupier
		if self.occupier != self.owner:
			return self.occupier
		return None


# ─────────── 游戏状态 ────────────────────────

class GameState:

	def __init__(self, cfg: GameConfig = None):
		if cfg is None:
			cfg = GameConfig("5x5")
		self.cfg         = cfg
		self.turn        = 1
		self.units: list = []
		self.effect_mgr  = EffectManager()
		self.base_states: dict = {}
		for pos, owner in cfg.all_bases():
			self.base_states[pos] = BaseState(owner)
		self.camp_level  = 1
		self.winner      = None
		self.win_reason  = ""
		self.collapse_targets: dict = {}
		self.log: list   = []
		self._pre_pos: dict = {}

	def setup(self):
		pos_map = self.cfg.initial_positions()
		for x, y in pos_map[FACTION_RED]:
			self.units.append(Unit("铁卫", FACTION_RED, x, y))
		for x, y in pos_map[FACTION_DIS]:
			self.units.append(Unit("散兽", FACTION_DIS, x, y))

	def add_unit(self, name, faction, x, y):
		u = Unit(name, faction, x, y)
		self.units.append(u)
		return u

	def alive_units(self):
		return [u for u in self.units if not u.dead]

	def units_at(self, x, y):
		return [u for u in self.alive_units() if u.x == x and u.y == y]

	def faction_units(self, faction):
		return [u for u in self.alive_units() if u.faction == faction]

	def get_unit_by_uid(self, uid):
		for u in self.units:
			if u.uid == uid:
				return u
		return None

	def effect_tag(self):
		return self.effect_mgr.tag()

	# ─── 属性修正 ───────────────────────────────

	def effective_atk(self, unit):
		atk = unit.atk
		if self.effect_tag() == "blood_surge":
			atk += 1
		if self.effect_tag() == "beast_instinct":
			if any(u.faction == unit.faction for u in adjacent_units(unit, self.alive_units())):
				atk += 1
		return atk

	def effective_spd(self, unit):
		spd = unit.spd
		if self.effect_tag() == "red_whisper":
			spd += 1
		return spd

	def predict_attack_target(self, unit):
		"""规划阶段预测自动攻击目标（供 UI 预览）"""
		self._pre_pos = {u.uid: (u.x, u.y) for u in self.alive_units()}
		return self._auto_find_target(unit, self.alive_units())

	# ─── 执行回合 ───────────────────────────────

	def execute_turn(self):
		log    = []
		effect = self.effect_tag()
		silent = (effect == "silence")
		if silent:
			log.append("⚡ 寂静：本回合无法攻击")

		self._pre_pos = {u.uid: (u.x, u.y) for u in self.alive_units()}

		erode = self.effect_mgr.erode_cells(self.cfg.grid_size)
		self._phase_move(erode, log, silent)

		if effect == "collapse":
			for faction in (FACTION_RED, FACTION_DIS):
				tuid = self.collapse_targets.get(faction)
				if tuid:
					t = self.get_unit_by_uid(tuid)
					if t and not t.dead:
						t.take_damage(1)
						log.append(f"💥 崩解：{t.name} −1HP → {t.hp}HP")

		self._phase_action(log, silent)
		self._flush_dead(log)

		# 铁砧回响
		if effect == "anvil_echo":
			for u in self.alive_units():
				if not u.did_move:
					u.heal(1)
					log.append(f"🔨 铁砧：{u.name} +1HP → {u.hp}HP")

		# 回音
		if effect == "echo":
			for u in self.alive_units():
				u.heal(1)
			log.append("🔔 回音：所有棋子 +1HP")

		# 驻扎回血（简易兵营 lv2 +1HP，前线营地 lv3 +2HP）
		if self.camp_level >= 2:
			bonus = 2 if self.camp_level >= 3 else 1
			for bpos in self.base_states:
				for u in self.alive_units():
					if (u.x, u.y) == bpos and not u.did_move:
						u.heal(bonus)
						log.append(f"🏕️ 驻扎：{u.name} +{bonus}HP → {u.hp}HP")

		rift = (effect == "rift")
		for bpos, bstate in self.base_states.items():
			bstate.update(self.units_at(*bpos), rift, log, bpos)

		self._check_evolution(log)
		self._check_victory(log)

		if self.turn % 3 == 0:
			self.effect_mgr.advance()
			log.append(f"🌀 战场效果 → 【{self.effect_mgr.name()}】{self.effect_mgr.desc()}")

		self._update_camp_level()
		self.turn += 1
		self.log.extend(log)
		return log

	# ─── 移动阶段（支持菱形范围位移） ──────────────

	def _phase_move(self, erode, log, silent=False):
		import random
		from collections import defaultdict
		gs = self.cfg.grid_size

		# ── 战车冲阵预处理：直线逐格移动，遇敌停止并造成伤害 ──────
		chariot_moved = set()
		for u in self.alive_units():
			if not u.has_trait("冲阵") or u.stun_move or u.planned_action == ACT_DEFEND:
				continue
			dx, dy = u.planned_dir
			if dx == 0 and dy == 0:
				continue
			# 非直线规划视为无效
			if dx != 0 and dy != 0:
				u.planned_dir = DIR_NONE
				continue
			step_x = 1 if dx > 0 else -1
			step_y = 1 if dy > 0 else -1
			if dx == 0:
				step_x = 0
			if dy == 0:
				step_y = 0
			max_steps = min(abs(dx) + abs(dy), self.effective_spd(u))
			cx, cy = u.x, u.y
			for _ in range(max_steps):
				nx, ny = cx + step_x, cy + step_y
				if not in_bounds(nx, ny, gs):
					break
				cx, cy = nx, ny
				enemies_here = [e for e in self.alive_units()
					if e.x == cx and e.y == cy
					and e.faction != u.faction and not e.is_embryo]
				if enemies_here:
					all_a = self.alive_units()
					for enemy in enemies_here:
						dmg = self._calc_damage(u, enemy, all_a)
						enemy.take_damage(dmg)
						log.append(f"💨 冲阵：{u.name}→{enemy.name}  伤{dmg}")
						if dmg == 0 and self.effective_atk(u) > 0:
							enemy.kills += 1
							log.append(f"⭐ {enemy.name} 防住冲阵！+1经验({enemy.kills})")
						if enemy.dead:
							log.append(f"💀 {enemy.name}({enemy.faction[:3]}) 冲阵阵亡")
						u._collision_partner  = enemy.uid
						enemy._collision_partner = u.uid
					break  # 遇敌停止
			if cx != u.x or cy != u.y:
				log.append(f"🚗 {u.name}({u.faction[:3]}) 冲阵 ({u.x},{u.y})→({cx},{cy})")
				u.did_move = True
			u.x, u.y = cx, cy
			chariot_moved.add(u.uid)

		intent = {}
		for u in self.alive_units():
			if u.uid in chariot_moved:
				# 战车已自行处理移动，锁定当前位置
				intent[u.uid] = (u.x, u.y)
				continue
			if u.stun_move or u.planned_action == ACT_DEFEND:
				intent[u.uid] = (u.x, u.y)
				continue
			dx, dy = u.planned_dir
			nx, ny = u.x + dx, u.y + dy
			# 越界 → 原地
			if not in_bounds(nx, ny, gs):
				nx, ny = u.x, u.y
			intent[u.uid] = (nx, ny)

		# 冲突处理：先处理同格情况
		# ① 敌方同格：速度高者留，低者退，记录碰撞对
		# ② 友方同格：速度高者留，低者退（不结算战斗）
		dest_map = defaultdict(list)
		for uid, pos in intent.items():
			dest_map[pos].append(uid)

		final = dict(intent)
		collision_pairs = []

		for pos, uids in dest_map.items():
			if len(uids) < 2:
				continue
			units_here = [self.get_unit_by_uid(uid) for uid in uids]
			# 必须有至少一个是真正在移动的（否则原本就同格，跳过）
			if not any(intent[u.uid] != (u.x, u.y) for u in units_here):
				continue
			# 同速随机打乱，避免 uid 顺序造成系统性偏差
			random.shuffle(units_here)
			units_here.sort(key=lambda u: self.effective_spd(u), reverse=True)
			winner = units_here[0]
			for loser in units_here[1:]:
				final[loser.uid] = (loser.x, loser.y)
				log.append(f"↩️ 挤开：{loser.name} 被挤回原位")
				# 只有敌方对撞才记录碰撞
				if winner.faction != loser.faction:
					collision_pairs.append((winner.uid, loser.uid))

		for u in self.alive_units():
			tx, ty = final[u.uid]
			if tx != u.x or ty != u.y:
				u.did_move = True
				log.append(f"➡️ {u.name}({u.faction[:3]}) ({u.x},{u.y})→({tx},{ty})")
			u.x, u.y = tx, ty

		if not silent:
			self._resolve_collisions(collision_pairs, log)

		if erode:
			for u in self.alive_units():
				if (u.x, u.y) in erode and u.did_move:
					log.append(f"🌑 蚀地：{u.name} 进入蚀地格")

	def _resolve_collisions(self, collision_pairs, log):
		all_alive = self.alive_units()
		for w_uid, l_uid in collision_pairs:
			w = self.get_unit_by_uid(w_uid)
			l = self.get_unit_by_uid(l_uid)
			if not w or not l or w.dead or l.dead or w.faction == l.faction:
				continue
			w_atk = (w.planned_action != ACT_DEFEND and not w.is_embryo)
			l_atk = (l.planned_action != ACT_DEFEND and not l.is_embryo)
			if w_atk and l_atk:
				dw = self._calc_damage(w, l, all_alive)
				dl = self._calc_damage(l, w, all_alive)
				l.take_damage(dw); w.take_damage(dl)
				log.append(f"💥 碰撞互攻：{w.name}↔{l.name}  互伤{dw}/{dl}")
				if dw == 0 and self.effective_atk(w) > 0:
					l.kills += 1
					log.append(f"⭐ {l.name} 防住攻击！+1经验({l.kills})")
				if dl == 0 and self.effective_atk(l) > 0:
					w.kills += 1
					log.append(f"⭐ {w.name} 防住攻击！+1经验({w.kills})")
				w._collision_partner = l.uid; l._collision_partner = w.uid
			elif w_atk:
				d = self._calc_damage(w, l, all_alive)
				l.take_damage(d)
				log.append(f"💥 碰撞：{w.name}→{l.name}  伤{d}")
				if d == 0 and self.effective_atk(w) > 0:
					l.kills += 1
					log.append(f"⭐ {l.name} 防住攻击！+1经验({l.kills})")
				w._collision_partner = l.uid; l._collision_partner = w.uid
			elif l_atk:
				d = self._calc_damage(l, w, all_alive)
				w.take_damage(d)
				log.append(f"💥 碰撞：{l.name}→{w.name}  伤{d}")
				if d == 0 and self.effective_atk(l) > 0:
					w.kills += 1
					log.append(f"⭐ {w.name} 防住攻击！+1经验({w.kills})")
				w._collision_partner = l.uid; l._collision_partner = w.uid
			else:
				log.append(f"🤝 碰撞双防：无伤害")
			for u in (w, l):
				if u.hp <= 0 and not u.dead:
					u.dead = True
					log.append(f"💀 {u.name}({u.faction[:3]}) 碰撞阵亡")

	# ─── 行动阶段（自动攻击） ──────────────────────

	def _phase_action(self, log, silent=False):
		all_alive = self.alive_units()
		for u in all_alive:
			if u.planned_action == ACT_DEFEND:
				u.defending = True

		if not silent:
			attackers = [u for u in all_alive
				if u.planned_action != ACT_DEFEND and not u.is_embryo]
			attackers.sort(key=lambda u: self.effective_spd(u), reverse=True)

			processed = set()
			for uid in all_alive:
				p = getattr(uid, "_collision_partner", None)
				if p:
					processed.add(frozenset([uid.uid, p]))

			for atk in attackers:
				if atk.dead:
					continue
				if atk.ranged and atk.did_move:
					continue
				# 跳过已处理对（碰撞对），尝试下一目标而不是直接放弃
				target = self._find_unprocessed_target(atk, all_alive, processed)
				if not target:
					continue
				pair = frozenset([atk.uid, target.uid])
				dmg = self._calc_damage(atk, target, all_alive)
				same_spd = self.effective_spd(atk) == self.effective_spd(target)
				t_atks_back = (
					target.planned_action != ACT_DEFEND
					and not target.is_embryo
					and same_spd
					and self._auto_find_target(target, all_alive) is atk
				)
				if t_atks_back:
					# 同速同时互攻：锁定该对，防止重复
					dmg2 = self._calc_damage(target, atk, all_alive)
					atk.pending_dmg    += dmg2
					target.pending_dmg += dmg
					log.append(f"⚔️ 同时：{atk.name}↔{target.name}  互伤{dmg2}/{dmg}")
					processed.add(pair)
				else:
					target.pending_dmg += dmg
					log.append(f"⚔️ {atk.name}({atk.faction[:3]}) → {target.name}  伤{dmg}")
					# 非同速单向攻击：不锁定，慢速方稍后仍可攻击快速方
				# 防住判定（dmg=0 但攻击有效）：防守方 +1 经验
				if dmg == 0 and self.effective_atk(atk) > 0:
					target.kills += 1
					log.append(f"⭐ {target.name} 防住攻击！+1经验({target.kills})")
				if t_atks_back:
					dmg2_val = self._calc_damage(target, atk, all_alive) if t_atks_back else 0
					if dmg2_val == 0 and self.effective_atk(target) > 0:
						atk.kills += 1
						log.append(f"⭐ {atk.name} 防住反攻！+1经验({atk.kills})")

			for u in self.alive_units():
				if u.pending_dmg > 0:
					old = u.hp
					u.take_damage(u.pending_dmg)
					log.append(f"💔 {u.name} −{u.pending_dmg}HP  {old}→{u.hp}")
					if u.dead:
						log.append(f"💀 {u.name}({u.faction[:3]}) 阵亡")

			# 噬溃
			for atk in attackers:
				if atk.dead or not atk.has_trait("噬溃"):
					continue
				t = self._auto_find_target_raw(atk, self.units)
				if t and t.dead:
					atk.heal(2)
					log.append(f"🩸 噬溃：{atk.name} +2HP → {atk.hp}HP")

			# 威压
			for atk in attackers:
				if atk.has_trait("威压") and not atk.dead:
					t = self._auto_find_target(atk, all_alive)
					if t and t.pending_dmg > 0:
						t.stun_move = True
						log.append(f"😱 威压：{t.name} 下回合无法移动")

			# 集群溅射
			for atk in attackers:
				if atk.has_trait("集群") and not atk.dead:
					t = self._auto_find_target(atk, self.alive_units())
					if t:
						for nb in adjacent_units(t, self.alive_units()):
							if nb.faction != atk.faction:
								nb.take_damage(1)
								log.append(f"💥 集群：{nb.name} −1HP")

		for u in self.alive_units():
			if u.planned_action == ACT_MAKE and u.level >= 2 and not u.made_unit and u.can_make:
				self._do_make(u, log)

	def _auto_find_target(self, attacker, all_alive):
		enemies = [u for u in all_alive
			if u.faction != attacker.faction and not u.dead and not u.is_embryo]
		rng = attacker.attack_range()
		in_range = [e for e in enemies
			if manhattan(attacker.x, attacker.y, e.x, e.y) <= rng]
		if not in_range:
			return None
		atk_pre = self._pre_pos.get(attacker.uid, (attacker.x, attacker.y))
		def key(e):
			post = manhattan(attacker.x, attacker.y, e.x, e.y)
			ep   = self._pre_pos.get(e.uid, (e.x, e.y))
			pre  = manhattan(atk_pre[0], atk_pre[1], ep[0], ep[1])
			return (post, pre)
		in_range.sort(key=key)
		return in_range[0]

	def _find_unprocessed_target(self, attacker, all_alive, processed):
		"""按优先级遍历射程内目标，跳过已与攻击者处理过的对；允许远程在碰撞后攻击其他目标"""
		enemies = [u for u in all_alive
			if u.faction != attacker.faction and not u.dead and not u.is_embryo]
		rng = attacker.attack_range()
		in_range = [e for e in enemies
			if manhattan(attacker.x, attacker.y, e.x, e.y) <= rng]
		if not in_range:
			return None
		atk_pre = self._pre_pos.get(attacker.uid, (attacker.x, attacker.y))
		def key(e):
			post = manhattan(attacker.x, attacker.y, e.x, e.y)
			ep   = self._pre_pos.get(e.uid, (e.x, e.y))
			pre  = manhattan(atk_pre[0], atk_pre[1], ep[0], ep[1])
			return (post, pre)
		in_range.sort(key=key)
		for e in in_range:
			if frozenset([attacker.uid, e.uid]) not in processed:
				return e
		return None

	def _auto_find_target_raw(self, attacker, all_units):
		enemies = [u for u in all_units
			if u.faction != attacker.faction and not u.is_embryo]
		rng = attacker.attack_range()
		in_range = [e for e in enemies
			if manhattan(attacker.x, attacker.y, e.x, e.y) <= rng]
		if not in_range:
			return None
		in_range.sort(key=lambda e: manhattan(attacker.x, attacker.y, e.x, e.y))
		return in_range[0]

	def _calc_damage(self, attacker, defender, all_alive):
		atk = self.effective_atk(attacker)
		if attacker.has_trait("齐射"):
			if any(u.faction == attacker.faction for u in adjacent_units(attacker, all_alive)):
				atk += 1
		for a in all_alive:
			if (a.faction == attacker.faction and a.has_trait("战旗")
					and a.uid != attacker.uid
					and manhattan(attacker.x, attacker.y, a.x, a.y) <= 2):
				atk += 1; break
		# 防御减免
		def_bonus = 1 if defender.defending else 0
		if defender.has_trait("硬壳"):
			def_bonus += 1
		if defender.has_trait("列阵") and not defender.did_move:
			def_bonus += 1
		# 铁壁光环：相邻己方盾卫（未移动）给防守方+1减伤
		if any(a.faction == defender.faction and a.has_trait("铁壁") and not a.did_move
				for a in adjacent_units(defender, all_alive)):
			def_bonus += 1
		return max(0, atk - def_bonus)

	def _do_make(self, maker, log):
		gs = self.cfg.grid_size
		for dx, dy in [DIR_UP, DIR_DOWN, DIR_LEFT, DIR_RIGHT]:
			nx, ny = maker.x + dx, maker.y + dy
			if in_bounds(nx, ny, gs) and not self.units_at(nx, ny):
				self.add_unit("胚体", maker.faction, nx, ny)
				maker.made_unit = True
				log.append(f"🐣 {maker.name} 制造胚体@({nx},{ny})")
				return
		log.append(f"🚫 {maker.name} 无空格可制造")

	def _flush_dead(self, log):
		for u in self.alive_units():
			if u.hp <= 0:
				u.dead = True

	def _check_evolution(self, log):
		# 每2回合：存活单位获得+1经验（不含胚体、3级）
		if self.turn % 2 == 0:
			for u in self.alive_units():
				if not u.is_embryo and u.level < 3:
					u.kills += 1
					log.append(f"⏱️ {u.name} 存活奖励 +1经验({u.kills})")
		for u in self.alive_units():
			if u.level == 1 and u.kills >= 1 and not hasattr(u, "_pending_evo"):
				u._pending_evo = True
				log.append(f"⬆️ {u.name}({u.faction[:3]}) 可进化！")
			if u.level == 2 and u.kills >= 1 and not hasattr(u, "_pending_evo3"):
				u._pending_evo3 = True
				log.append(f"⬆️ {u.name}({u.faction[:3]}) 可进化3级！")

	def evolve_unit(self, uid, target_name):
		u = self.get_unit_by_uid(uid)
		if not u:
			return
		tmpl = UNIT_TEMPLATES[target_name]
		old = u.name
		u.name     = target_name
		u.level    = tmpl["level"]
		hp_bonus   = tmpl["max_hp"] - u.max_hp
		u.max_hp   = tmpl["max_hp"]
		u.hp       = min(u.max_hp, u.hp + max(0, hp_bonus))
		u.base_atk = tmpl["atk"]
		u.base_spd = tmpl["spd"]
		u.trait    = tmpl["trait"]
		u.ranged   = tmpl["ranged"]
		u.can_make = tmpl.get("can_make", True)
		for a in ("_pending_evo", "_pending_evo3"):
			if hasattr(u, a):
				delattr(u, a)
		self.log.append(f"✨ {old}({u.faction[:3]}) → {target_name}！")

	def _check_victory(self, log):
		red = self.faction_units(FACTION_RED)
		dis = self.faction_units(FACTION_DIS)
		# 同时阵亡：用剩余HP总量决定胜负，真平局时存活单位多的一方胜
		if not red and not dis:
			red_hp = sum(u.hp for u in self.units if u.faction == FACTION_RED)
			dis_hp = sum(u.hp for u in self.units if u.faction == FACTION_DIS)
			if red_hp > dis_hp:
				self.winner = FACTION_RED; self.win_reason = "同归于尽（红方HP占优）"
			elif dis_hp > red_hp:
				self.winner = FACTION_DIS; self.win_reason = "同归于尽（灾方HP占优）"
			else:
				self.winner = FACTION_RED; self.win_reason = "同归于尽（完全平局，红方优先）"
			log.append(f"⚖️ 双方同归于尽！{self.win_reason}"); return
		if not red:
			self.winner = FACTION_DIS; self.win_reason = "全歼红方"
			log.append("🏆 灾方胜利！"); return
		if not dis:
			self.winner = FACTION_RED; self.win_reason = "全歼灾方"
			log.append("🏆 红方胜利！"); return
		for bpos, bstate in self.base_states.items():
			w = bstate.winner()
			if w:
				self.winner = w
				self.win_reason = f"连续占领{bpos} 2回合"
				log.append(f"🏆 {'红方' if w == FACTION_RED else '灾方'} 胜利！"); return

	def _update_camp_level(self):
		if self.turn >= 3 and self.camp_level < 2:
			self.camp_level = 2
		if any(bs.occupy_count >= 1 for bs in self.base_states.values()):
			if self.camp_level < 3:
				self.camp_level = 3

	@property
	def occupy_faction(self):
		if self.cfg.shared_base and self.cfg.shared_base in self.base_states:
			return self.base_states[self.cfg.shared_base].occupier
		return None

	@property
	def occupy_count(self):
		if self.cfg.shared_base and self.cfg.shared_base in self.base_states:
			return self.base_states[self.cfg.shared_base].occupy_count
		return 0
73 