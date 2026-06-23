# 兵戮灾 · AI 策略模块
# 供游戏内 AI 接管 和 sim.py 模拟共用
# skill: 'novice' | 'veteran'   style: 'aggressive' | 'conservative'

import random
from constants import *


def _dist(ax, ay, bx, by):
	return abs(ax - bx) + abs(ay - by)


def _choose_target(u, enemies, skill):
	"""目标优先级：资深=残血优先；新手=最近。"""
	if not enemies:
		return None
	if skill == "novice":
		return min(enemies, key=lambda e: _dist(u.x, u.y, e.x, e.y))
	def pri(e):
		d    = _dist(u.x, u.y, e.x, e.y)
		hp_r = e.hp / max(e.max_hp, 1)
		return d * 0.4 + hp_r * 3
	return min(enemies, key=pri)


def _move_toward(u, tgt, game, gs):
	"""移动朝向目标，冲阵/劲弩走直线。"""
	dx  = tgt.x - u.x
	dy  = tgt.y - u.y
	if dx == 0 and dy == 0:
		return
	spd = game.effective_spd(u)

	if u.has_trait("冲阵") or u.has_trait("劲弩"):
		if abs(dx) >= abs(dy):
			step = min(abs(dx), spd) * (1 if dx > 0 else -1)
			nx, ny = u.x + step, u.y
		else:
			step = min(abs(dy), spd) * (1 if dy > 0 else -1)
			nx, ny = u.x, u.y + step
		if 0 <= nx < gs and 0 <= ny < gs:
			u.planned_dir = (nx - u.x, ny - u.y)
		return

	remaining = spd
	mdx = mdy = 0
	if abs(dx) >= abs(dy):
		mdx = min(abs(dx), remaining) * (1 if dx > 0 else -1)
		remaining -= abs(mdx)
		mdy = min(abs(dy), remaining) * (1 if dy > 0 else -1)
	else:
		mdy = min(abs(dy), remaining) * (1 if dy > 0 else -1)
		remaining -= abs(mdy)
		mdx = min(abs(dx), remaining) * (1 if dx > 0 else -1)

	nx, ny = u.x + mdx, u.y + mdy
	if 0 <= nx < gs and 0 <= ny < gs:
		u.planned_dir = (mdx, mdy)


def _try_high_ground(u, game, gs):
	"""资深地形感知：高地附近且无敌占领则抢占。"""
	for hx, hy in TERRAIN_HIGH:
		if (hx, hy) == (u.x, u.y):
			return None
		d = _dist(u.x, u.y, hx, hy)
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
				if abs(dx) + abs(dy) == 1]
			random.shuffle(dirs)
			for dx, dy in dirs:
				nx, ny = u.x + dx, u.y + dy
				if 0 <= nx < gs and 0 <= ny < gs:
					u.planned_dir = (dx, dy)
					break
			continue

		tgt  = _choose_target(u, enemies, skill)
		dist = _dist(u.x, u.y, tgt.x, tgt.y)
		hp_r = u.hp / max(u.max_hp, 1)
		rng  = u.attack_range()

		# 资深：远程单位管理
		if skill == "veteran" and u.ranged:
			if dist <= rng:
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

		# 资深激进：抢高地
		if skill == "veteran" and style == "aggressive":
			hg = _try_high_ground(u, game, gs)
			if hg:
				u.planned_dir = hg
				continue

		# 防御决策
		if style == "conservative":
			surrounded = sum(1 for e in enemies
				if _dist(u.x, u.y, e.x, e.y) <= 1)
			has_onslaught = u.has_trait("噬溃")
			hp_thresh  = 0.30 if has_onslaught else (0.40 if skill == "veteran" else 0.20)
			surr_thresh = 3 if has_onslaught else 2
			if hp_r < hp_thresh or surrounded >= surr_thresh:
				u.planned_action = ACT_DEFEND
				continue

		# 移动决策
		if style == "aggressive":
			_move_toward(u, tgt, game, gs)
		else:
			allies_nearby = sum(1 for a in units
				if a.uid != u.uid and _dist(u.x, u.y, a.x, a.y) <= 2)
			if allies_nearby >= 1 or dist <= rng + 1:
				_move_toward(u, tgt, game, gs)
			else:
				ally = min((a for a in units if a.uid != u.uid),
					key=lambda a: _dist(u.x, u.y, a.x, a.y), default=None)
				if ally:
					_move_toward(u, ally, game, gs)
