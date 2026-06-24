# 兵戮灾 · AI 策略模块
# 供游戏内 AI 接管 和 sim.py 模拟共用
# skill: 'novice' | 'veteran'   style: 'aggressive' | 'conservative'

import random
from constants import *


def _dist(ax, ay, bx, by):
	"""Manhattan 距离（移动估算用）"""
	return abs(ax - bx) + abs(ay - by)


def _cheby(ax, ay, bx, by):
	"""Chebyshev 距离（攻击范围判定用）"""
	return max(abs(ax - bx), abs(ay - by))


def _choose_target(u, enemies, skill):
	"""目标优先级：资深=残血优先 + 距离权重；新手=最近。"""
	if not enemies:
		return None
	if skill == "novice":
		return min(enemies, key=lambda e: _cheby(u.x, u.y, e.x, e.y))
	def pri(e):
		d    = _cheby(u.x, u.y, e.x, e.y)
		hp_r = e.hp / max(e.max_hp, 1)
		return d * 0.4 + hp_r * 3
	return min(enemies, key=pri)


def _jump_best(u, offsets, tgt, gs, game):
	"""
	异形跳移公共逻辑：
	优先落点在攻击范围内（Chebyshev=1），
	同时对落点相邻敌人数加惩罚，避免跳入重围。
	"""
	enemies_all = [e for e in game.alive_units() if e.faction != u.faction and not e.is_embryo]
	cands = [(u.x + ox, u.y + oy) for ox, oy in offsets
		if 0 <= u.x + ox < gs and 0 <= u.y + oy < gs]
	if not cands:
		return

	def score(p):
		px, py = p
		dist_to_tgt = _cheby(px, py, tgt.x, tgt.y)
		# 落点相邻（Chebyshev=1）的敌人数量 → 加惩罚
		danger = sum(1 for e in enemies_all if _cheby(px, py, e.x, e.y) <= 1)
		# 已在攻击范围给大奖励
		in_rng = 0 if dist_to_tgt <= 1 else 3
		return in_rng + dist_to_tgt + danger * 1.5   # 每个相邻敌人惩罚 1.5

	best = min(cands, key=score)
	u.planned_dir = (best[0] - u.x, best[1] - u.y)


def _move_toward(u, tgt, game, gs):
	"""移动朝向目标：战车/远程直线；旗卫斜线；集群/威压跳移；其余菱形。"""
	dx  = tgt.x - u.x
	dy  = tgt.y - u.y
	if dx == 0 and dy == 0:
		return
	spd = game.effective_spd(u)

	if u.has_trait("冲阵") or u.has_trait("劲弩") or u.has_trait("投射"):
		if abs(dx) >= abs(dy):
			step = min(abs(dx), spd) * (1 if dx > 0 else -1)
			nx, ny = u.x + step, u.y
		else:
			step = min(abs(dy), spd) * (1 if dy > 0 else -1)
			nx, ny = u.x, u.y + step
		if 0 <= nx < gs and 0 <= ny < gs:
			u.planned_dir = (nx - u.x, ny - u.y)
		return

	if u.has_trait("战旗"):
		# 旗卫：斜向4方向，选落点 Chebyshev 最近目标
		cands = [(u.x + d[0]*spd, u.y + d[1]*spd)
			for d in [(1,1),(1,-1),(-1,1),(-1,-1)]]
		cands = [(nx, ny) for nx, ny in cands if 0 <= nx < gs and 0 <= ny < gs]
		if cands:
			best = min(cands, key=lambda p: _cheby(p[0], p[1], tgt.x, tgt.y))
			u.planned_dir = (best[0] - u.x, best[1] - u.y)
		return

	if u.has_trait("集群"):
		_jump_best(u, [(1,1),(1,-1),(-1,1),(-1,-1),(2,2),(2,-2),(-2,2),(-2,-2)], tgt, gs, game)
		return

	if u.has_trait("威压"):
		_jump_best(u, [(1,2),(1,-2),(-1,2),(-1,-2),(2,1),(2,-1),(-2,1),(-2,-1)], tgt, gs, game)
		return

	# 默认：8方向（Chebyshev）移动，每步沿最短对角路径逼近目标
	mdx = max(-spd, min(spd, dx))
	mdy = max(-spd, min(spd, dy))
	nx, ny = u.x + mdx, u.y + mdy
	if 0 <= nx < gs and 0 <= ny < gs:
		u.planned_dir = (mdx, mdy)


def _try_high_ground(u, game, gs):
	"""资深地形感知：高地附近且无敌占领则抢占。"""
	for hx, hy in TERRAIN_HIGH:
		if (hx, hy) == (u.x, u.y):
			return None
		d = _cheby(u.x, u.y, hx, hy)
		if d > 2:
			continue
		if any(e.x == hx and e.y == hy and e.faction != u.faction
				for e in game.alive_units()):
			continue
		dx, dy = hx - u.x, hy - u.y
		sd = (1 if dx > 0 else -1, 0) if abs(dx) >= abs(dy) else (0, 1 if dy > 0 else -1)
		nx, ny = u.x + sd[0], u.y + sd[1]
		if 0 <= nx < gs and 0 <= ny < gs:
			return sd
	return None


def ai_plan(game, faction, skill="veteran", style="conservative"):
	"""
	为指定阵营填写所有单位的规划（planned_dir / planned_action）。
	skill : 'novice' | 'veteran'
	style : 'aggressive' | 'conservative'
	"""
	noise = 0.25 if skill == "novice" else 0.06
	units = game.faction_units(faction)
	for u in units:
		u.planned_dir    = DIR_NONE
		u.planned_action = ACT_NONE

	enemies = [e for e in game.alive_units()
		if e.faction != faction and not e.is_embryo]
	if not enemies:
		return

	gs = game.cfg.grid_size

	for u in units:
		if u.is_embryo:
			continue

		# 噪声
		if random.random() < noise:
			if random.random() < 0.35:
				u.planned_action = ACT_DEFEND
				continue
			dirs = [(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)
				if (dx, dy) != (0, 0)]
			random.shuffle(dirs)
			for dx, dy in dirs:
				nx, ny = u.x + dx, u.y + dy
				if 0 <= nx < gs and 0 <= ny < gs:
					u.planned_dir = (dx, dy)
					break
			continue

		tgt  = _choose_target(u, enemies, skill)
		# 近战用曼哈顿=1判断是否在攻击范围，远程用切比雪夫
		rng  = u.attack_range()
		dist = _cheby(u.x, u.y, tgt.x, tgt.y)
		hp_r = u.hp / max(u.max_hp, 1)
		in_rng = (_cheby(u.x, u.y, tgt.x, tgt.y) <= rng) if u.ranged else \
			(_dist(u.x, u.y, tgt.x, tgt.y) == 1)

		# 资深：远程单位管理——已在射程内原地不动
		if skill == "veteran" and u.ranged:
			if in_rng:
				u.planned_dir = DIR_NONE
				continue
			if abs(tgt.x - u.x) >= abs(tgt.y - u.y):
				step = (1 if tgt.x > u.x else -1, 0)
			else:
				step = (0, 1 if tgt.y > u.y else -1)
			nx, ny = u.x + step[0], u.y + step[1]
			if 0 <= nx < gs and 0 <= ny < gs:
				u.planned_dir = step
			continue

		# 近战：已在攻击范围（曼哈顿=1）→ 原地攻击，不移动
		if not u.ranged and in_rng:
			u.planned_dir = DIR_NONE
			continue

		# 资深激进：抢高地
		if skill == "veteran" and style == "aggressive":
			hg = _try_high_ground(u, game, gs)
			if hg:
				u.planned_dir = hg
				continue

		# 噬溃特殊逻辑：血量低但有杀机时优先进攻回血，而非防御
		if u.has_trait("噬溃") and hp_r < 0.5 and in_rng:
			# 有弱敌在射程内：进攻换血
			weak_in_range = [e for e in enemies if _dist(u.x, u.y, e.x, e.y) == 1
				and e.hp <= u.atk]
			if weak_in_range:
				u.planned_dir = DIR_NONE   # 原地攻击
				continue

		# 防御决策（激进阈值低，保守阈值高）
		has_onslaught = u.has_trait("噬溃")
		surrounded = sum(1 for e in enemies if _dist(u.x, u.y, e.x, e.y) == 1)
		if style == "conservative":
			hp_thresh   = 0.25 if has_onslaught else 0.50
			surr_thresh = 4    if has_onslaught else 2
		else:
			hp_thresh   = 0.15 if has_onslaught else 0.20
			surr_thresh = 4    if has_onslaught else 4
		if hp_r < hp_thresh or surrounded >= surr_thresh:
			u.planned_action = ACT_DEFEND
			continue

		# 越线与移动决策
		gs_half = gs // 2
		in_enemy_half = (
			(u.faction == FACTION_RED and u.y > gs_half) or
			(u.faction == FACTION_DIS and u.y < gs_half)
		)
		if style == "aggressive":
			# 激进：直扑敌人；仅无战斗压力时顺路越线
			no_combat = not any(_cheby(u.x, u.y, e.x, e.y) <= 2 for e in enemies)
			if u.level < 3 and not in_enemy_half and no_combat:
				cross_dir = 1 if u.faction == FACTION_RED else -1
				tgt = type("_P", (), {"x": tgt.x, "y": gs_half + cross_dir})()
			_move_toward(u, tgt, game, gs)
		else:
			# 保守：未越线时以越线为主要目标；已越线后正常追敌
			allies_nearby = sum(1 for a in units
				if a.uid != u.uid and _cheby(u.x, u.y, a.x, a.y) <= 2)
			if u.level < 3 and not in_enemy_half:
				cross_dir = 1 if u.faction == FACTION_RED else -1
				cross_tgt = type("_P", (), {"x": tgt.x, "y": gs_half + cross_dir})()
				if allies_nearby >= 1:
					_move_toward(u, cross_tgt, game, gs)
				else:
					ally = min((a for a in units if a.uid != u.uid),
						key=lambda a: _cheby(u.x, u.y, a.x, a.y), default=None)
					if ally:
						_move_toward(u, ally, game, gs)
			else:
				if allies_nearby >= 1 or dist <= 2:
					_move_toward(u, tgt, game, gs)
				else:
					ally = min((a for a in units if a.uid != u.uid),
						key=lambda a: _cheby(u.x, u.y, a.x, a.y), default=None)
					if ally:
						_move_toward(u, ally, game, gs)

	# 最终过滤：仅取消斜向踏入敌格的规划（正交踏入保留，触发挤占攻击）
	enemy_cells = {(e.x, e.y) for e in enemies}
	for u in units:
		if u.planned_dir == DIR_NONE:
			continue
		dx, dy = u.planned_dir
		nx, ny = u.x + dx, u.y + dy
		if dx != 0 and dy != 0 and (nx, ny) in enemy_cells:  # 斜向才取消
			u.planned_dir = DIR_NONE

