# 血轨：9×9 平衡模拟 + 自动调整
# 方法论：trait 对齐 AI + 15% 噪声 + 200 局 → 自动调参直到胜率均衡

import os
import sys
import random
import copy

os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"

sys.path.insert(0, os.path.dirname(__file__))

import pygame
pygame.init()
pygame.display.set_mode((1, 1))

from constants import *
from game_engine import GameState
import unit as unit_module
from unit import Unit

MAX_TURNS  = 60
NOISE_RATE = 0.15
BALANCE_TOL = 5      # ±5% 视为均衡
MAX_BALANCE_ITER = 8  # 最多调 8 轮


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
	return min(enemies, key=lambda e: abs(e.x - u.x) + abs(e.y - u.y)) if enemies else None


def _step_toward(ux, uy, tx, ty, spd):
	dx = tx - ux; dy = ty - uy
	adx = abs(dx); ady = abs(dy)
	if adx == 0 and ady == 0:
		return 0, 0
	step = min(spd, adx + ady)
	if adx >= ady:
		sx = min(adx, step) * (1 if dx > 0 else -1)
		rem = step - min(adx, step)
		sy = min(ady, rem) * (1 if dy > 0 else -1)
	else:
		sy = min(ady, step) * (1 if dy > 0 else -1)
		rem = step - min(ady, step)
		sx = min(adx, rem) * (1 if dx > 0 else -1)
	return sx, sy


def _plan_aggressive(u, game):
	e = _nearest_enemy(u, game)
	if not e: return
	spd  = game.effective_spd(u)
	dist = abs(e.x - u.x) + abs(e.y - u.y)
	rng  = u.attack_range()
	if dist <= rng:
		u.planned_dir = DIR_NONE
	else:
		u.planned_dir = _step_toward(u.x, u.y, e.x, e.y, spd)


def _plan_liezheng(u, game):
	e = _nearest_enemy(u, game)
	if not e: return
	spd   = game.effective_spd(u)
	dist  = abs(e.x - u.x) + abs(e.y - u.y)
	rng   = u.attack_range()
	if u.hp / u.max_hp < 0.35:
		u.planned_action = ACT_DEFEND
		u.planned_dir    = DIR_NONE
	elif dist <= rng + 1:
		u.planned_dir = DIR_NONE
	else:
		u.planned_dir = _step_toward(u.x, u.y, e.x, e.y, spd)


def _plan_shiwei(u, game):
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


# ─────────────────── 单批次运行 ─────────────────────

def run_batch(red_style, dis_style, n, seed=None):
	if seed is not None:
		random.seed(seed)
	wins       = {FACTION_RED: 0, FACTION_DIS: 0, None: 0}
	turns_list = []
	win_types  = {"全歼": 0, "占阵": 0, "平局": 0}

	for _ in range(n):
		cfg  = GameConfig("9x9")
		game = GameState(cfg)
		game.setup()

		for _ in range(MAX_TURNS):
			if game.winner: break
			ai_plan_faction(game, FACTION_RED, red_style)
			ai_plan_faction(game, FACTION_DIS, dis_style)
			game.execute_turn()
			for u in game.alive_units():
				u.clear_turn_state()
			if game.winner: break

		wins[game.winner] = wins.get(game.winner, 0) + 1
		turns_list.append(game.turn - 1)
		r = game.win_reason or ""
		if "全歼" in r:  win_types["全歼"] += 1
		elif "占" in r:  win_types["占阵"] += 1
		else:            win_types["平局"] += 1

	rw = wins[FACTION_RED]; dw = wins[FACTION_DIS]
	avg_t = sum(turns_list) / len(turns_list) if turns_list else 0
	return rw, dw, wins[None], avg_t, win_types


CONFIGS = [
	("red_liezheng", "dis_shiwei",  "红(守阵) vs 灾(噬溃)  ★"),
	("aggressive",   "dis_shiwei",  "红(激进) vs 灾(噬溃)"),
	("red_liezheng", "aggressive",  "红(守阵) vs 灾(激进)"),
	("aggressive",   "aggressive",  "红(激进) vs 灾(激进)"),
]


def run_full_sim(n_per_cfg=50, seed=2025, label=""):
	"""跑完 4 对阵 × n_per_cfg 局，返回 (总胜率%, trait对齐胜率%)"""
	if label:
		print(f"\n{'='*68}\n  {label}\n{'='*68}")
		print(f"{'对阵':40s} {'红':>4} {'灾':>4} {'平':>3}  {'均回合':>6}  胜负方式")
		print("-" * 68)

	total_rw = total_dw = 0
	trait_rw = trait_dw = 0

	for rs, ds, lbl in CONFIGS:
		rw, dw, draw, avg_t, wt = run_batch(rs, ds, n_per_cfg, seed)
		total_rw += rw; total_dw += dw
		if rs == "red_liezheng" and ds == "dis_shiwei":
			trait_rw = rw; trait_dw = dw
		if label:
			print(f"  {lbl:40s} {rw:4d} {dw:4d} {draw:3d}  {avg_t:6.1f}回  "
				  f"全歼{wt['全歼']} 占阵{wt['占阵']} 平{wt['平局']}")

	all_games = total_rw + total_dw
	total_pct  = total_rw / all_games * 100 if all_games else 50
	trait_pct  = trait_rw / (trait_rw + trait_dw) * 100 if (trait_rw + trait_dw) else 50

	if label:
		flag = "✅ 均衡" if 40 <= total_pct <= 60 else ("⚠️ 灾偏强" if total_pct < 40 else "⚠️ 红偏强")
		print("-" * 68)
		print(f"  总胜率 {total_pct:.1f}%  {flag}  |  ★trait对齐 {trait_pct:.1f}%")

	return total_pct, trait_pct


# ─────────────────── 自动平衡 ─────────────────────

TUNING_TARGETS = [
	# (描述, 单位名, 字段, 方向)
	("散兽 hp -1（削灾）", "散兽", "max_hp", -1),
	("铁卫 hp +1（强红）", "铁卫", "max_hp", +1),
	("散兽 atk -1（削灾）", "散兽", "atk",    -1),
	("铁卫 atk +1（强红）", "铁卫", "atk",    +1),
	("铁卫 hp -1（削红）", "铁卫", "max_hp", -1),
	("散兽 hp +1（强灾）", "散兽", "max_hp", +1),
	("铁卫 atk -1（削红）", "铁卫", "atk",    -1),
	("散兽 atk +1（强灾）", "散兽", "atk",    +1),
]

# 合法值范围，防止数值退化
LIMITS = {"max_hp": (2, 6), "atk": (1, 4)}


def apply_tune(name, field, delta):
	tmpl = unit_module.UNIT_TEMPLATES[name]
	tmpl[field] = tmpl[field] + delta


def revert_tune(name, field, delta):
	tmpl = unit_module.UNIT_TEMPLATES[name]
	tmpl[field] = tmpl[field] - delta


def val_in_range(name, field, delta):
	v = unit_module.UNIT_TEMPLATES[name][field] + delta
	lo, hi = LIMITS.get(field, (0, 99))
	return lo <= v <= hi


def auto_balance():
	applied = []

	print("\n" + "="*68)
	print("  ▶ 自动平衡模式启动")
	print("="*68)

	total_pct, trait_pct = run_full_sim(50, seed=2025, label="初始基准（每对阵50局）")

	for iteration in range(MAX_BALANCE_ITER):
		if abs(total_pct - 50) <= BALANCE_TOL and abs(trait_pct - 50) <= BALANCE_TOL + 2:
			print(f"\n✅ 已达平衡（总体{total_pct:.1f}% / ★{trait_pct:.1f}%），停止调整")
			break

		# 确定调整方向
		# 以 trait 对齐局为主要信号
		target = trait_pct
		need_buff_red = target < 50

		print(f"\n── 迭代 {iteration + 1} ──  当前★胜率 {target:.1f}%，{'红偏弱→尝试强红/削灾' if need_buff_red else '红偏强→尝试削红/强灾'}")

		best_desc    = None
		best_delta   = abs(target - 50)
		best_pct     = target
		best_name_field_delta = None

		# 测试每个候选，快速用 30 局
		for desc, uname, field, delta in TUNING_TARGETS:
			# 方向过滤：弱红时只试强红/削灾，强红时只试削红/强灾
			is_buff_red = (uname == "铁卫" and delta > 0) or (uname == "散兽" and delta < 0)
			if need_buff_red and not is_buff_red:
				continue
			if not need_buff_red and is_buff_red:
				continue
			if not val_in_range(uname, field, delta):
				continue

			apply_tune(uname, field, delta)
			_, test_trait = run_full_sim(30, seed=3000 + iteration)
			revert_tune(uname, field, delta)

			d = abs(test_trait - 50)
			print(f"    试：{desc:20s}  ★{test_trait:.1f}%  偏差{d:.1f}%")
			if d < best_delta:
				best_delta = d
				best_pct   = test_trait
				best_desc  = desc
				best_name_field_delta = (uname, field, delta)

		if best_name_field_delta:
			uname, field, delta = best_name_field_delta
			apply_tune(uname, field, delta)
			applied.append((best_desc, uname, field, delta))
			print(f"\n  ✔ 应用：{best_desc}  →  预测★{best_pct:.1f}%")
		else:
			print("  ✗ 无可用改动，停止")
			break

		# 重新全量测试
		total_pct, trait_pct = run_full_sim(50, seed=2025 + iteration + 1,
			label=f"迭代{iteration+1}后（每对阵50局）")

	return applied


# ─────────────────── 镜像验证 ─────────────────────

def run_mirror(unit_name, n=50):
	random.seed(9999)
	wins = {FACTION_RED: 0, FACTION_DIS: 0, None: 0}
	for _ in range(n):
		cfg  = GameConfig("9x9")
		game = GameState(cfg)
		game.units = []
		pos = cfg.initial_positions()
		for x, y in pos[FACTION_RED]:
			game.units.append(Unit(unit_name, FACTION_RED, x, y))
		for x, y in pos[FACTION_DIS]:
			game.units.append(Unit(unit_name, FACTION_DIS, x, y))
		for _ in range(MAX_TURNS):
			if game.winner: break
			ai_plan_faction(game, FACTION_RED, "aggressive")
			ai_plan_faction(game, FACTION_DIS, "aggressive")
			game.execute_turn()
			for u in game.alive_units(): u.clear_turn_state()
			if game.winner: break
		wins[game.winner] = wins.get(game.winner, 0) + 1
	rw = wins[FACTION_RED]; dw = wins[FACTION_DIS]
	pct = rw / (rw + dw) * 100 if (rw + dw) else 50
	fair = "✅ 对称" if 38 <= pct <= 62 else "⚠️ 不对称"
	print(f"  镜像 {unit_name} vs {unit_name}：红{rw} 灾{dw}  {pct:.0f}%  {fair}")


# ─────────────────── 写回 unit.py ─────────────────────

def save_unit_templates():
	"""将调整后的 UNIT_TEMPLATES 写回 unit.py（仅数值字段）"""
	tmpl = unit_module.UNIT_TEMPLATES
	lines = [
		"# 血轨：兵种定义与单位类\n",
		"# （由 sim.py 自动平衡后生成）\n\n",
		"from constants import *\n\n",
		"UNIT_TEMPLATES = {\n",
	]
	for name, d in tmpl.items():
		faction = repr(d['faction'])
		lines.append(
			f"\t{repr(name):12s}: dict(faction={faction}, level={d['level']}, "
			f"max_hp={d['max_hp']}, atk={d['atk']}, spd={d['spd']}, "
			f"trait={repr(d['trait'])}, ranged={d['ranged']}, can_make={d.get('can_make', True)}),\n"
		)
	lines.append("}\n")

	# 读原文件，只替换 UNIT_TEMPLATES 块
	with open("unit.py", "r", encoding="utf-8") as f:
		original = f.read()

	start = original.index("UNIT_TEMPLATES = {")
	end   = original.index("\n}\n", start) + 3
	block = "".join(lines[3:])  # skip comment + import lines
	new_content = original[:start] + block + original[end:]

	with open("unit.py", "w", encoding="utf-8") as f:
		f.write(new_content)
	print("\n📝 unit.py 已写入平衡后数值")


# ─────────────────── 主入口 ─────────────────────

if __name__ == "__main__":
	print("血轨平衡模拟器 v4  |  9×9 地图  |  双盲修正方法论")

	# 1. 自动平衡
	applied_changes = auto_balance()

	# 2. 最终 200 局报告
	print("\n" + "="*68)
	print("  ▶ 最终 200 局报告（每对阵 50 局）")
	run_full_sim(50, seed=42, label="最终平衡结果")

	# 3. 镜像验证
	print(f"\n{'='*68}")
	print("  镜像公平性验证")
	print(f"{'='*68}")
	run_mirror("铁卫", 50)
	run_mirror("散兽", 50)

	# 4. 汇报调整内容
	if applied_changes:
		print(f"\n{'='*68}")
		print("  累计调整项目：")
		tpl = unit_module.UNIT_TEMPLATES
		for desc, uname, field, delta in applied_changes:
			print(f"    {desc}")
		print(f"\n  最终 1 级数值：")
		for uname in ("铁卫", "散兽"):
			t = tpl[uname]
			print(f"    {uname}：hp={t['max_hp']}  atk={t['atk']}  spd={t['spd']}")
		save_unit_templates()
	else:
		print("\n✅ 初始数值已均衡，无需调整")

	print(f"\n{'='*68}\n")
