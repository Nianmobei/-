# 血轨：双盲修正平衡模拟 v4
# 修正：位置对称（5x5 back 单位移至同行）+ 碰撞随机平局打破（不再偏红）
# 方法论：trait 对齐 AI（红守阵/灾噬溃）+ 15% 噪声 + 4 对阵 × 2 地图 × 25 局

import os
import sys
import random

os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"

sys.path.insert(0, os.path.dirname(__file__))

import pygame
pygame.init()
pygame.display.set_mode((1, 1))

from constants import *
from game_engine import GameState

MAX_TURNS  = 40
N_PER_CFG  = 25
NOISE_RATE = 0.15


# ─────────────────── AI 规划 ─────────────────────

def ai_plan_faction(game, faction, style):
	units = game.faction_units(faction)
	for u in units:
		u.planned_action = ACT_NONE
		u.planned_dir    = DIR_NONE

	for u in units:
		if random.random() < NOISE_RATE:
			_plan_random(u, game)
		elif style == "red_liezheng":
			_plan_liezheng(u, game)
		elif style == "dis_shiwei":
			_plan_shiwei(u, game)
		else:
			_plan_aggressive(u, game)


def _nearest_enemy(u, game):
	enemies = game.faction_units(
		FACTION_DIS if u.faction == FACTION_RED else FACTION_RED
	)
	if not enemies:
		return None
	return min(enemies, key=lambda e: abs(e.x - u.x) + abs(e.y - u.y))


def _step_toward(ux, uy, tx, ty, spd):
	dx = tx - ux; dy = ty - uy
	adx = abs(dx); ady = abs(dy)
	if adx == 0 and ady == 0:
		return 0, 0
	step = min(spd, adx + ady)
	ox, oy = 0, 0
	if adx >= ady:
		sx = min(adx, step) * (1 if dx > 0 else -1)
		rem = step - min(adx, step)
		sy = min(ady, rem) * (1 if dy > 0 else -1)
		ox, oy = sx, sy
	else:
		sy = min(ady, step) * (1 if dy > 0 else -1)
		rem = step - min(ady, step)
		sx = min(adx, rem) * (1 if dx > 0 else -1)
		ox, oy = sx, sy
	return ox, oy


def _plan_aggressive(u, game):
	e = _nearest_enemy(u, game)
	if not e:
		return
	spd = game.effective_spd(u)
	dist = abs(e.x - u.x) + abs(e.y - u.y)
	rng  = u.attack_range()
	if dist <= rng:
		u.planned_dir = DIR_NONE
	else:
		u.planned_dir = _step_toward(u.x, u.y, e.x, e.y, spd)


def _plan_liezheng(u, game):
	"""守阵风格：射程内不动触发列阵减伤；血少时防御"""
	e = _nearest_enemy(u, game)
	if not e:
		return
	spd  = game.effective_spd(u)
	dist = abs(e.x - u.x) + abs(e.y - u.y)
	rng  = u.attack_range()
	hp_ratio = u.hp / u.max_hp

	if hp_ratio < 0.35:
		u.planned_action = ACT_DEFEND
		u.planned_dir    = DIR_NONE
	elif dist <= rng + 1:
		u.planned_dir = DIR_NONE   # 原地不动，触发列阵
	else:
		u.planned_dir = _step_toward(u.x, u.y, e.x, e.y, spd)


def _plan_shiwei(u, game):
	"""噬溃风格：全速冲锋，争取击杀触发回血"""
	_plan_aggressive(u, game)


def _plan_random(u, game):
	spd = game.effective_spd(u)
	candidates = [DIR_NONE]
	for dx in range(-spd, spd + 1):
		for dy in range(-spd, spd + 1):
			if abs(dx) + abs(dy) <= spd and (dx, dy) != (0, 0):
				nx, ny = u.x + dx, u.y + dy
				if 0 <= nx < game.cfg.grid_size and 0 <= ny < game.cfg.grid_size:
					candidates.append((dx, dy))
	u.planned_dir = random.choice(candidates)


# ─────────────── 单局运行 ───────────────────────

def run_batch(mode, red_style, dis_style, n, noise=NOISE_RATE):
	random.seed(2025)
	wins   = {FACTION_RED: 0, FACTION_DIS: 0, None: 0}
	turns_list = []
	win_types  = {"全歼": 0, "占阵": 0, "平局": 0}

	for _ in range(n):
		cfg  = GameConfig(mode)
		game = GameState(cfg)
		game.setup()

		for _ in range(MAX_TURNS):
			if game.winner:
				break
			ai_plan_faction(game, FACTION_RED, red_style)
			ai_plan_faction(game, FACTION_DIS, dis_style)
			game.execute_turn()
			for u in game.alive_units():
				u.clear_turn_state()
			if game.winner:
				break

		wins[game.winner] = wins.get(game.winner, 0) + 1
		turns_list.append(game.turn - 1)
		r = game.win_reason or ""
		if "全歼" in r:
			win_types["全歼"] += 1
		elif "占" in r:
			win_types["占阵"] += 1
		else:
			win_types["平局"] += 1

	rw = wins[FACTION_RED]; dw = wins[FACTION_DIS]; draw = wins[None]
	avg_t = sum(turns_list) / len(turns_list)
	return rw, dw, draw, avg_t, win_types


# ─────────────── 镜像对局 ───────────────────────

def run_mirror(mode, unit_name, n):
	from unit import Unit
	random.seed(2025)
	wins = {FACTION_RED: 0, FACTION_DIS: 0, None: 0}
	turns_list = []

	for _ in range(n):
		cfg  = GameConfig(mode)
		game = GameState(cfg)
		game.units = []
		pos = cfg.initial_positions()
		for x, y in pos[FACTION_RED]:
			game.units.append(Unit(unit_name, FACTION_RED, x, y))
		for x, y in pos[FACTION_DIS]:
			game.units.append(Unit(unit_name, FACTION_DIS, x, y))

		for _ in range(MAX_TURNS):
			if game.winner:
				break
			ai_plan_faction(game, FACTION_RED, "aggressive")
			ai_plan_faction(game, FACTION_DIS, "aggressive")
			game.execute_turn()
			for u in game.alive_units():
				u.clear_turn_state()
			if game.winner:
				break

		wins[game.winner] = wins.get(game.winner, 0) + 1
		turns_list.append(game.turn - 1)

	rw = wins[FACTION_RED]; dw = wins[FACTION_DIS]; draw = wins[None]
	avg_t = sum(turns_list) / len(turns_list)
	return rw, dw, draw, avg_t


# ─────────────── 主报告 ─────────────────────────

if __name__ == "__main__":
	configs = [
		("red_liezheng", "dis_shiwei",  "红(守阵) vs 灾(噬溃)  ← 双方按trait打"),
		("aggressive",   "dis_shiwei",  "红(激进) vs 灾(噬溃)"),
		("red_liezheng", "aggressive",  "红(守阵) vs 灾(激进)"),
		("aggressive",   "aggressive",  "红(激进) vs 灾(激进)"),
	]

	total_rw = total_dw = total_draw = 0
	trait_rw = trait_dw = 0

	for mode in ["5x5", "10x10"]:
		print(f"\n{'='*68}")
		print(f"  地图：{mode}   双盲修正模拟 v4（位置+平局修正，噪声={int(NOISE_RATE*100)}%）")
		print(f"{'='*68}")
		print(f"{'对阵':40s} {'红':>4} {'灾':>4} {'平':>3}  {'均回合':>6}  胜负方式")
		print("-" * 68)

		map_rw = map_dw = 0
		for rs, ds, label in configs:
			rw, dw, draw, avg_t, wt = run_batch(mode, rs, ds, N_PER_CFG)
			total_rw += rw; total_dw += dw; total_draw += draw
			map_rw   += rw; map_dw   += dw

			suffix = " ★" if rs == "red_liezheng" and ds == "dis_shiwei" else ""
			print(f"  {label:40s} {rw:4d} {dw:4d} {draw:3d}  {avg_t:6.1f}回  "
				  f"全歼{wt['全歼']} 占阵{wt['占阵']} 平{wt['平局']}{suffix}")

			if rs == "red_liezheng" and ds == "dis_shiwei":
				trait_rw += rw; trait_dw += dw

		total = map_rw + map_dw
		pct   = map_rw / total * 100 if total else 50
		flag  = "✅ 均衡" if 40 <= pct <= 60 else ("⚠️ 灾偏强" if pct < 40 else "⚠️ 红偏强")
		print("-" * 68)
		print(f"  {mode} 红方总胜率：{map_rw}/{map_rw+map_dw} = {pct:.0f}%  {flag}")

	# ── 综合 ──
	print(f"\n{'='*68}")
	print("  综合分析")
	print(f"{'='*68}")
	all_t = total_rw + total_dw + total_draw
	all_pct = total_rw / (total_rw + total_dw) * 100 if (total_rw + total_dw) else 50
	flag_all = "✅ 均衡" if 40 <= all_pct <= 60 else ("⚠️ 灾偏强" if all_pct < 40 else "⚠️ 红偏强")
	print(f"\n  总局数 {all_t}  红方整体胜率 {all_pct:.1f}%  {flag_all}")
	tr_pct = trait_rw / (trait_rw + trait_dw) * 100 if (trait_rw + trait_dw) else 50
	tr_flag = "✅ 均衡" if 40 <= tr_pct <= 60 else ("⚠️ 灾偏强" if tr_pct < 40 else "⚠️ 红偏强")
	print(f"\n  ★ 各按trait打（最接近实际对局）：")
	print(f"     红胜 {trait_rw}  灾胜 {trait_dw}  红方率 {tr_pct:.0f}%  {tr_flag}")

	# ── 镜像 ──
	print(f"\n{'='*68}")
	print("  镜像对局  同兵种互战（验证代码公平性）")
	print(f"{'='*68}")
	print(f"{'对局':42s} {'红':>4} {'灾':>4} {'平':>3}  {'均回合':>6}  公平性")
	print("-" * 68)
	for mode in ["5x5", "10x10"]:
		for uname, label in [("铁卫", "铁卫列阵 vs 铁卫列阵"),
							  ("散兽", "散兽噬溃 vs 散兽噬溃")]:
			rw, dw, draw, avg_t = run_mirror(mode, uname, N_PER_CFG)
			total_ = rw + dw
			red_rt = rw / total_ * 100 if total_ > 0 else 50
			fair   = "✅ 对称" if 38 <= red_rt <= 62 else "⚠️ 不对称"
			print(f"  {mode}  {label:34s} {rw:4d} {dw:4d} {draw:3d}  {avg_t:6.1f}回  "
				  f"{fair}({red_rt:.0f}%)")
	print("-" * 68)
	print("  注：镜像局验证规则层公平性，50% ± 12% 视为合格")
	print(f"\n{'='*68}\n")
