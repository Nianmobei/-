# 血轨：核心游戏引擎（菱形范围移动 + 修复防御/驻扎）

from constants import *
from unit import Unit, UNIT_TEMPLATES
from effects import EffectManager


def manhattan(ax, ay, bx, by):
	return abs(ax - bx) + abs(ay - by)


def in_bounds(x, y, gs):
	return 0 <= x < gs and 0 <= y < gs


def chebyshev(ax, ay, bx, by):
	return max(abs(ax - bx), abs(ay - by))


def adjacent_units(unit, all_units):
	"""8方向相邻（切比雪夫距离=1，含斜向）"""
	return [u for u in all_units
		if not u.dead and u.uid != unit.uid
		and chebyshev(unit.x, unit.y, u.x, u.y) == 1]


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
			name = "红骑士团" if faction == FACTION_RED else "灾兽群"
			log.append(f"🏳️ {name} 夺回本阵{bpos}")

		if [u for u in real if u.faction == faction] and not effect_rift:
				self.occupy_count += 1
				name = "红骑士团" if self.occupier == FACTION_RED else "灾兽群"
				log.append(f"🚩 {name} 占领本阵{bpos} 第{self.occupy_count}回合")
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
		# 每回合攻击事件：list of (atk_uid, tgt_uid, is_ranged, is_collision)
		self.last_attack_events: list = []
		# 主攻击阶段结束边界（供动画器区分主攻 vs 反击）
		self.last_attack_main_end: int = 0
		# 心跳事件标记（每3回合，供 main.py 弹横幅）
		self.heartbeat_event: bool = False

	def setup(self):
		conds = self.cfg.conditions
		pos_map = self.cfg.tide_positions() if "tide" in conds else self.cfg.initial_positions()
		for x, y in pos_map[FACTION_RED]:
			self.units.append(Unit("铁卫", FACTION_RED, x, y))
		for x, y in pos_map[FACTION_DIS]:
			self.units.append(Unit("散兽", FACTION_DIS, x, y))
		if "extreme_terrain" in conds:
			self._generate_extreme_terrain(pos_map)

	def _generate_extreme_terrain(self, pos_map):
		import random
		cfg = self.cfg
		occupied = {cfg.red_base, cfg.dis_base}
		for pos in pos_map.get(FACTION_RED, []) + pos_map.get(FACTION_DIS, []):
			occupied.add(pos)
		gs = cfg.grid_size
		# 中间带随机生成，避开本阵和初始位置
		mid_lo, mid_hi = gs // 4, gs * 3 // 4
		candidates = [(x, y) for x in range(gs) for y in range(mid_lo, mid_hi + 1)
			if (x, y) not in occupied]
		random.shuffle(candidates)
		cfg._extra_terrain = {}
		for i, pos in enumerate(candidates[:5]):
			cfg._extra_terrain[pos] = "high" if i < 3 else "trench"

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
		if self.cfg.terrain_at(unit.x, unit.y) == "high":
			atk += 1
		return atk

	def effective_spd(self, unit):
		return unit.spd

	def predict_attack_target(self, unit):
		"""规划阶段预测自动攻击目标（供 UI 预览）"""
		self._pre_pos = {u.uid: (u.x, u.y) for u in self.alive_units()}
		return self._auto_find_target(unit, self.alive_units())

	# ─── 执行回合 ───────────────────────────────

	def apply_planned_evolutions(self, log):
		"""执行回合首步：同步应用双方在规划阶段已选定的进化计划（双盲同步）。"""
		for u in list(self.alive_units()):
			plan = getattr(u, "_evo_plan", None)
			if plan is None:
				continue
			if plan == "":
				self.skip_evolution(u.uid)
			else:
				log.append(f"⬆️ {u.name} 进化为 {plan}")
				self.evolve_unit(u.uid, plan)
			if hasattr(u, "_evo_plan"):
				delattr(u, "_evo_plan")
			# 清理剩余 pending 标记
			for attr in ("_pending_evo", "_pending_evo3"):
				if hasattr(u, attr):
					delattr(u, attr)

	def execute_turn(self):
		log    = []
		self.last_attack_events = []

		# ① 首步：双方规划阶段已选的进化同步生效
		self.apply_planned_evolutions(log)

		self._pre_pos = {u.uid: (u.x, u.y) for u in self.alive_units()}

		# 自动行动：有敌在攻击射程内→攻击（即使不移动）；否则不移动→防御
		all_u = self.alive_units()
		for u in all_u:
			if u.is_embryo:
				continue
			if u.planned_dir == DIR_NONE:
				has_target = any(self._in_attack_range(u, e)
					for e in all_u
					if e.faction != u.faction and not e.dead and not e.is_embryo)
				u.planned_action = ACT_NONE if has_target else ACT_DEFEND
			else:
				u.planned_action = ACT_NONE

		erode = set()  # 蚀地已移除
		self._phase_move(erode, log)
		self._phase_action(log)
		self._flush_dead(log)

		conds = self.cfg.conditions

		# 丰饶：每回合末存活未满血单位 +1HP
		if "abundance" in conds:
			for u in self.alive_units():
				if u.hp < u.max_hp:
					u.heal(1)

		# 战争恩赐：每回合末存活 lv1/lv2 单位 +1经验
		if "war_gift" in conds:
			for u in self.alive_units():
				if u.level < 3 and not u.is_embryo:
					u.kills += 1
					log.append(f"🎁 战争恩赐：{u.name} +1经验({u.kills})")

		# 驻扎回血（简易兵营 lv2 +1HP，前线营地 lv3 +2HP）
		if self.camp_level >= 2:
			bonus = 2 if self.camp_level >= 3 else 1
			for bpos in self.base_states:
				for u in self.alive_units():
					if (u.x, u.y) == bpos and not u.did_move:
						u.heal(bonus)
						log.append(f"🏕️ 驻扎：{u.name} +{bonus}HP → {u.hp}HP")

		for bpos, bstate in self.base_states.items():
			bstate.update(self.units_at(*bpos), False, log, bpos)

		# 越线经验：奇数回合结算，驻扎在敌方领域（越过中线）的未满级单位+1经验
		# 红方往下推(y > gs//2)，灾方往上推(y < gs//2)
		if self.turn % 2 == 1:
			gs_half = self.cfg.grid_size // 2
			for u in self.alive_units():
				if u.level >= 3 or u.is_embryo:
					continue
				in_enemy_half = (
					(u.faction == FACTION_RED and u.y > gs_half) or
					(u.faction == FACTION_DIS and u.y < gs_half)
				)
				if in_enemy_half:
					u.kills += 1
					log.append(f"⚔️ {u.name} 深入敌境 +1经验({u.kills})")

		# 高地首次踏入奖励 +1经验
		for u in self.alive_units():
			if u.level >= 3 or u.is_embryo:
				continue
			if self.cfg.terrain_at(u.x, u.y) == "high":
				visited = getattr(u, "_visited_high", set())
				if (u.x, u.y) not in visited:
					visited.add((u.x, u.y))
					u._visited_high = visited
					u.kills += 1
					log.append(f"🏔️ {u.name} 首次占领高地 +1经验({u.kills})")

		# 长线战：每3回合，本阵未被敌占则补充1个基础兵种
		if "long_war" in conds and self.turn % 3 == 0:
			for bpos, bstate in self.base_states.items():
				owner = bstate.owner
				if owner is None:
					continue
				if bstate.occupier is not None and bstate.occupier != owner:
					continue  # 被敌占领，不补充
				if self.units_at(*bpos):
					continue  # 格内有棋子，不补充
				name = "铁卫" if owner == FACTION_RED else "散兽"
				self.add_unit(name, owner, *bpos)
				log.append(f"🔄 长线战：{name}({owner[:3]}) 在 {bpos} 生成")

		self._check_evolution(log)
		self._check_victory(log)
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

		# 敌方当前位置集合（规划阶段不可主动踏入，意外挤占仍由碰撞系统处理）
		enemy_pos = {(e.x, e.y) for e in self.alive_units() if not e.is_embryo}

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
			# 斜向踏入敌格 → 取消移动；正交踏入允许，触发挤占攻击
			elif (nx, ny) in enemy_pos and any(
					e.x == nx and e.y == ny and e.faction != u.faction
					for e in self.alive_units() if not e.is_embryo):
				ddx, ddy = nx - u.x, ny - u.y
				if ddx != 0 and ddy != 0:   # 仅斜向禁止
					nx, ny = u.x, u.y
			intent[u.uid] = (nx, ny)

		# 冲突处理：区分"静止单位被进入"和"多单位同时移向空格"
		# 静止单位（intent == 当前位置）视为不可穿越障碍，移动者强制退回
		dest_map = defaultdict(list)
		for uid, pos in intent.items():
			dest_map[pos].append(uid)

		final = dict(intent)
		collision_pairs = []
		pushed_by_friendly = set()   # 被友方挡住的移动单位uid，用于后续绕路

		for pos, uids in dest_map.items():
			if len(uids) < 2:
				continue
			units_here = [self.get_unit_by_uid(uid) for uid in uids]
			# 区分：已在该格静止的单位 vs 正在移动进来的单位
			static  = [u for u in units_here if (u.x, u.y) == pos]
			movers  = [u for u in units_here if (u.x, u.y) != pos]
			if not movers:
				continue   # 都是原地单位，无需处理

			if static:
				# 有单位静止占据此格 → 所有移动者退回原位
				for mv in movers:
					final[mv.uid] = (mv.x, mv.y)
					for st in static:
						if st.faction != mv.faction:
							collision_pairs.append((st.uid, mv.uid))
						else:
							pushed_by_friendly.add(mv.uid)
				if movers:
					log.append(f"↩️ 挡路：{', '.join(m.name for m in movers)} 被占格单位阻挡")
			else:
				# 多个单位同时移向同一空格 → 速度高者留，低者退
				random.shuffle(units_here)
				units_here.sort(key=lambda u: self.effective_spd(u), reverse=True)
				winner = units_here[0]
				for loser in units_here[1:]:
					final[loser.uid] = (loser.x, loser.y)
					log.append(f"↩️ 挤开：{loser.name} 被挤回原位")
					if winner.faction != loser.faction:
						collision_pairs.append((winner.uid, loser.uid))
					else:
						pushed_by_friendly.add(loser.uid)

		# 问题4：被友方挡住的单位自动绕路到相邻可用格
		occupied_final = set(final[u.uid] for u in self.alive_units())
		for uid in pushed_by_friendly:
			u = self.get_unit_by_uid(uid)
			if not u:
				continue
			# 只在原地时才绕路（已经有其他冲突处理把它定位原地）
			if final[uid] != (u.x, u.y):
				continue
			# 按曼哈顿距离优先：先试计划移动方向的相邻格
			pdx, pdy = u.planned_dir
			candidates = []
			for ddx, ddy in [(pdx, pdy), (1,0),(-1,0),(0,1),(0,-1)]:
				if ddx == 0 and ddy == 0:
					continue
				nx, ny = u.x + ddx, u.y + ddy
				if not in_bounds(nx, ny, gs):
					continue
				if (nx, ny) in occupied_final:
					continue
				# 不能进入敌方占领格（友方绕路用）
				enemy_there = any(
					eu.x == nx and eu.y == ny
					for eu in self.alive_units()
					if eu.faction != u.faction and eu.uid != u.uid
				)
				if enemy_there:
					continue
				candidates.append((nx, ny))
			if candidates:
				nx, ny = candidates[0]
				final[uid] = (nx, ny)
				occupied_final.add((nx, ny))
				log.append(f"↪️ 绕路：{u.name} 自动移至({nx},{ny})")

		for u in self.alive_units():
			tx, ty = final[u.uid]
			if tx != u.x or ty != u.y:
				u.did_move = True
				log.append(f"➡️ {u.name}({u.faction[:3]}) ({u.x},{u.y})→({tx},{ty})")
			u.x, u.y = tx, ty

		# 安全清理：如有同阵营单位共格（边界情况），强制挤出到相邻空格
		from collections import defaultdict as _dd
		pos_grp = _dd(list)
		for u in self.alive_units():
			pos_grp[(u.x, u.y)].append(u)
		occupied_now = set(pos_grp.keys())
		for pos, uu in pos_grp.items():
			by_fac = {}
			for u in uu:
				by_fac.setdefault(u.faction, []).append(u)
			for fac, grp in by_fac.items():
				if len(grp) <= 1:
					continue
				for extra in grp[1:]:
					for ddx, ddy in [(1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)]:
						nx, ny = extra.x + ddx, extra.y + ddy
						if in_bounds(nx, ny, gs) and (nx, ny) not in occupied_now:
							extra.x, extra.y = nx, ny
							occupied_now.add((nx, ny))
							log.append(f"⚠️ 修正重叠：{extra.name} 移至({nx},{ny})")
							break

		if not silent:
			self._resolve_collisions(collision_pairs, log)

	def _resolve_collisions(self, collision_pairs, log):
		all_alive = self.alive_units()
		for w_uid, l_uid in collision_pairs:
			w = self.get_unit_by_uid(w_uid)
			l = self.get_unit_by_uid(l_uid)
			if not w or not l or w.dead or l.dead or w.faction == l.faction:
				continue
			# 近战碰撞伤害要求正交相邻（曼哈顿=1），斜向冲撞仅阻挡不造成伤害
			orthogonal = manhattan(w.x, w.y, l.x, l.y) == 1
			w_atk = (w.planned_action != ACT_DEFEND and not w.is_embryo and orthogonal)
			l_atk = (l.planned_action != ACT_DEFEND and not l.is_embryo and orthogonal)
			if w_atk and l_atk:
				dw = self._calc_damage(w, l, all_alive)
				dl = self._calc_damage(l, w, all_alive)
				l.take_damage(dw); w.take_damage(dl)
				log.append(f"💥 碰撞互攻：{w.name}↔{l.name}  互伤{dw}/{dl}")
				w._collision_partner = l.uid; l._collision_partner = w.uid
				self.last_attack_events.append((w.uid, l.uid, False, True))
				self.last_attack_events.append((l.uid, w.uid, False, True))
			elif w_atk:
				d = self._calc_damage(w, l, all_alive)
				l.take_damage(d)
				log.append(f"💥 碰撞：{w.name}→{l.name}  伤{d}")
				w._collision_partner = l.uid; l._collision_partner = w.uid
				self.last_attack_events.append((w.uid, l.uid, False, True))
				# 被挤占方处于防御状态 → 碰撞反击
				if l.planned_action == ACT_DEFEND and not l.dead and not l.is_embryo:
					cd = self._calc_damage(l, w, all_alive)
					w.take_damage(cd)
					log.append(f"🔄 挤占反击：{l.name}→{w.name}  伤{cd}")
					self.last_attack_events.append((l.uid, w.uid, False, True))
			elif l_atk:
				d = self._calc_damage(l, w, all_alive)
				w.take_damage(d)
				log.append(f"💥 碰撞：{l.name}→{w.name}  伤{d}")
				w._collision_partner = l.uid; l._collision_partner = w.uid
				self.last_attack_events.append((l.uid, w.uid, False, True))
				# 被挤占方处于防御状态 → 碰撞反击
				if w.planned_action == ACT_DEFEND and not w.dead and not w.is_embryo:
					cd = self._calc_damage(w, l, all_alive)
					l.take_damage(cd)
					log.append(f"🔄 挤占反击：{w.name}→{l.name}  伤{cd}")
					self.last_attack_events.append((w.uid, l.uid, False, True))
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

		# 参与了挤占碰撞的棋子本回合不再发起或响应普通攻击
		collision_uids = {u.uid for u in all_alive if getattr(u, "_collision_partner", None)}

		attackers = [u for u in all_alive
			if u.planned_action != ACT_DEFEND and not u.is_embryo
			and u.uid not in collision_uids]
		import random as _rnd
		_rnd.shuffle(attackers)
		attackers.sort(key=lambda u: self.effective_spd(u), reverse=True)

		processed = set()
		for uid in all_alive:
			p = getattr(uid, "_collision_partner", None)
			if p:
				processed.add(frozenset([uid.uid, p]))

		# 主攻击阶段：每个攻击者打一次主目标，记录每个目标被谁攻击（按顺序）
		attacks_received = {}   # tgt_uid → [atk_uid, ...]（按攻击先后顺序）
		for atk in attackers:
			if atk.dead:
				continue
			if atk.ranged and atk.did_move:
				continue
			target = self._find_unprocessed_target(atk, all_alive, processed)
			if not target:
				continue
			pair = frozenset([atk.uid, target.uid])
			dmg = self._calc_damage(atk, target, all_alive)
			target.pending_dmg += dmg
			log.append(f"⚔️ {atk.name}({atk.faction[:3]}) → {target.name}  伤{dmg}")
			self.last_attack_events.append((atk.uid, target.uid, atk.ranged, False))
			attacks_received.setdefault(target.uid, []).append(atk.uid)

		# 结算主攻击伤害
		for u in self.alive_units():
			if u.pending_dmg > 0:
				old = u.hp
				dmg_taken = u.pending_dmg
				u.take_damage(u.pending_dmg)
				u.pending_dmg = 0
				log.append(f"💔 {u.name} −{dmg_taken}HP  {old}→{u.hp}")
				if u.dead:
					log.append(f"💀 {u.name}({u.faction[:3]}) 阵亡")

		# 反击阶段：被攻击的存活单位进行反击（碰撞参与者跳过）
		# 防御中 → 反击所有攻击者；未防御 → 只反击第一个攻击者
		self.last_attack_main_end = len(self.last_attack_events)   # 主攻击事件边界
		cur_alive = self.alive_units()
		for tgt_uid, atk_uids in attacks_received.items():
			tgt = self.get_unit_by_uid(tgt_uid)
			if not tgt or tgt.dead or tgt.is_embryo:
				continue
			if tgt.uid in collision_uids:   # 碰撞参与者不反击
				continue
			# 防御单位反击所有人，非防御只反击第一个
			counter_list = atk_uids if tgt.defending else [atk_uids[0]]
			for atk_uid in counter_list:
				atk = self.get_unit_by_uid(atk_uid)
				if not atk or atk.dead:
					continue
				cdmg = self._calc_damage(tgt, atk, cur_alive)
				atk.take_damage(cdmg)
				tag = "🔄 反击(全)" if tgt.defending else "🔄 反击"
				log.append(f"{tag}：{tgt.name} → {atk.name}  伤{cdmg}")
				self.last_attack_events.append((tgt.uid, atk.uid, tgt.ranged, False))
				if atk.dead:
					log.append(f"💀 {atk.name}({atk.faction[:3]}) 反击阵亡")

		# 招灾：被主攻击命中时，对第一个攻击者反弹1点伤害（每格每回合触发一次）
		招灾_triggered = set()
		for tgt_uid, atk_uids in attacks_received.items():
			tgt = self.get_unit_by_uid(tgt_uid)
			if not tgt or not tgt.has_trait("招灾") or tgt_uid in 招灾_triggered:
				continue
			招灾_triggered.add(tgt_uid)
			atk = self.get_unit_by_uid(atk_uids[0])
			if atk and not atk.dead:
				atk.take_damage(1)
				log.append(f"⚡ 招灾：{tgt.name} → {atk.name} 反弹1伤")
				if atk.dead:
					log.append(f"💀 {atk.name}({atk.faction[:3]}) 招灾阵亡")

		# 击杀经验：任何单位击杀敌方 +1经验（含铁卫）
		for atk in attackers:
			if atk.dead or atk.level >= 3:
				continue
			atk_evts = [e for e in self.last_attack_events[:self.last_attack_main_end]
				if e[0] == atk.uid and not e[2]]
			for _, tgt_uid, _, _ in atk_evts:
				tgt = self.get_unit_by_uid(tgt_uid)
				if tgt and tgt.dead:
					atk.kills += 1
					log.append(f"☠ {atk.name} 击杀+1经验({atk.kills})")
					break

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

	def _in_attack_range(self, attacker, target):
		"""近战基础单位仅十字4格（曼哈顿=1），远程单位切比雪夫≤射程。"""
		rng = attacker.attack_range()
		if attacker.ranged:
			return chebyshev(attacker.x, attacker.y, target.x, target.y) <= rng
		return manhattan(attacker.x, attacker.y, target.x, target.y) == 1

	def _auto_find_target(self, attacker, all_alive):
		enemies = [u for u in all_alive
			if u.faction != attacker.faction and not u.dead and not u.is_embryo]
		in_range = [e for e in enemies if self._in_attack_range(attacker, e)]
		if not in_range:
			return None
		atk_pre = self._pre_pos.get(attacker.uid, (attacker.x, attacker.y))
		def key(e):
			post = chebyshev(attacker.x, attacker.y, e.x, e.y)
			ep   = self._pre_pos.get(e.uid, (e.x, e.y))
			pre  = chebyshev(atk_pre[0], atk_pre[1], ep[0], ep[1])
			return (post, pre)
		in_range.sort(key=key)
		return in_range[0]

	def _find_unprocessed_target(self, attacker, all_alive, processed):
		"""按优先级遍历射程内目标，跳过已与攻击者处理过的对；允许远程在碰撞后攻击其他目标"""
		enemies = [u for u in all_alive
			if u.faction != attacker.faction and not u.dead and not u.is_embryo]
		in_range = [e for e in enemies if self._in_attack_range(attacker, e)]
		if not in_range:
			return None
		atk_pre = self._pre_pos.get(attacker.uid, (attacker.x, attacker.y))
		def key(e):
			post = chebyshev(attacker.x, attacker.y, e.x, e.y)
			ep   = self._pre_pos.get(e.uid, (e.x, e.y))
			pre  = chebyshev(atk_pre[0], atk_pre[1], ep[0], ep[1])
			return (post, pre)
		in_range.sort(key=key)
		for e in in_range:
			if frozenset([attacker.uid, e.uid]) not in processed:
				return e
		return None

	def _auto_find_target_raw(self, attacker, all_units):
		enemies = [u for u in all_units
			if u.faction != attacker.faction and not u.is_embryo]
		in_range = [e for e in enemies if self._in_attack_range(attacker, e)]
		if not in_range:
			return None
		in_range.sort(key=lambda e: chebyshev(attacker.x, attacker.y, e.x, e.y))
		return in_range[0]

	def _calc_damage(self, attacker, defender, all_alive):
		atk = self.effective_atk(attacker)
		if attacker.has_trait("齐射"):
			if any(u.faction == attacker.faction for u in adjacent_units(attacker, all_alive)):
				atk += 1
		for a in all_alive:
			if (a.faction == attacker.faction and a.has_trait("战旗")
					and a.uid != attacker.uid
					and chebyshev(attacker.x, attacker.y, a.x, a.y) <= 2):
				atk += 1; break
		# 防御减免
		def_bonus = 0
		# 3级单位固有防御+1（精英单位不可被1级兵轻易击杀）
		if defender.level >= 3:
			def_bonus += 1
		if defender.has_trait("硬壳"):
			def_bonus += 1
		if defender.has_trait("列阵") and not defender.did_move:
			def_bonus += 1
		# 铁壁光环
		if any(a.faction == defender.faction and a.has_trait("铁壁") and not a.did_move
				for a in adjacent_units(defender, all_alive)):
			def_bonus += 1
		# 战壕地形
		if self.cfg.terrain_at(defender.x, defender.y) == "trench":
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
		# 心跳：每3回合，所有存活1级单位各+1经验（战争节奏加速）
		self.heartbeat_event = False
		if self.turn % 3 == 0:
			self.heartbeat_event = True
			for u in self.alive_units():
				if u.level == 1 and not u.is_embryo:
					u.kills += 1
					log.append(f"💗 心跳：{u.name} +1经验({u.kills})")
		# 进化触发判定（1→2需3经验，2→3需5经验，每级独立计算）
		for u in self.alive_units():
			if u.level == 1 and u.kills >= 3 and not hasattr(u, "_pending_evo"):
				u._pending_evo = True
				log.append(f"⬆️ {u.name}({u.faction[:3]}) 可进化！")
			if u.level == 2 and u.kills >= 5 and not hasattr(u, "_pending_evo3"):
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
		u.max_hp   = tmpl["max_hp"]
		u.hp       = tmpl["max_hp"]        # 先设新 max_hp
		u.base_atk = tmpl["atk"]
		u.base_spd = tmpl["spd"]
		u.trait    = tmpl["trait"]
		u.ranged   = tmpl["ranged"]
		u.can_make = tmpl.get("can_make", True)
		u.kills    = 0                     # 每级独立经验，进化后归零
		for a in ("_pending_evo", "_pending_evo3"):
			if hasattr(u, a):
				delattr(u, a)
		# 进化：HP增加2点（不补满）
		u.hp = min(u.max_hp, u.hp + 2)
		self.log.append(f"✨ {old}({u.faction[:3]}) → {target_name}！+2HP({u.hp}/{u.max_hp})")

	def skip_evolution(self, uid):
		"""不进化，保留路线 → +4HP（不补满）"""
		u = self.get_unit_by_uid(uid)
		if not u:
			return
		u.hp = min(u.max_hp, u.hp + 4)
		for a in ("_pending_evo", "_pending_evo3"):
			if hasattr(u, a):
				delattr(u, a)
		self.log.append(f"💊 {u.name}({u.faction[:3]}) 保留路线，+4HP({u.hp}/{u.max_hp})")

	def _check_victory(self, log):
		red = self.faction_units(FACTION_RED)
		dis = self.faction_units(FACTION_DIS)
		# 同时阵亡：用剩余HP总量决定胜负，真平局时存活单位多的一方胜
		if not red and not dis:
			red_hp = sum(u.hp for u in self.units if u.faction == FACTION_RED)
			dis_hp = sum(u.hp for u in self.units if u.faction == FACTION_DIS)
			if red_hp > dis_hp:
				self.winner = FACTION_RED; self.win_reason = "同归于尽（红骑士团HP占优）"
			elif dis_hp > red_hp:
				self.winner = FACTION_DIS; self.win_reason = "同归于尽（灾兽群HP占优）"
			else:
				self.winner = FACTION_RED; self.win_reason = "同归于尽（完全平局，红骑士团优先）"
			log.append(f"⚖️ 双方同归于尽！{self.win_reason}"); return
		if not red:
			self.winner = FACTION_DIS; self.win_reason = "全歼红骑士团"
			log.append("🏆 灾兽群胜利！"); return
		if not dis:
			self.winner = FACTION_RED; self.win_reason = "全歼灾兽群"
			log.append("🏆 红骑士团胜利！"); return
		for bpos, bstate in self.base_states.items():
			w = bstate.winner()
			if w:
				self.winner = w
				self.win_reason = f"连续占领{bpos} 2回合"
				log.append(f"🏆 {'红骑士团' if w == FACTION_RED else '灾兽群'} 胜利！"); return

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
