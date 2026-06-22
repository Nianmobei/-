# 血轨 200局模拟 v2 — 含新经验规则 + 无胚体生产 + 无防守经验
import sys, random
sys.path.insert(0, r"D:\学习资料\创作项目\血棋")
from constants import *
from game_engine import GameState
from unit import UNIT_TEMPLATES

# ── AI 策略 ──────────────────────────────────────────────────────────────────

def _dist(ax, ay, bx, by):
	return abs(ax - bx) + abs(ay - by)

def ai_plan(game, faction, style="auto", noise=0.15):
	"""给 faction 所有单位规划行动。style: 守阵/噬溃/aggressive/auto"""
	units = game.faction_units(faction)
	for u in units:
		u.planned_dir    = DIR_NONE
		u.planned_action = ACT_NONE

	enemies = [e for e in game.alive_units() if e.faction != faction and not e.is_embryo]
	if not enemies:
		return

	cfg = game.cfg
	gs  = cfg.grid_size
	spd = game.effective_spd

	for u in units:
		if u.is_embryo:
			continue
		if random.random() < noise:
			# 随机噪声：随机移动或防御
			if random.random() < 0.4:
				u.planned_action = ACT_DEFEND
				continue
			dirs = [(dx, dy) for dx in range(-1, 2) for dy in range(-1, 2)
				if (dx, dy) != (0, 0) and abs(dx) + abs(dy) == 1]
			random.shuffle(dirs)
			for dx, dy in dirs:
				nx, ny = u.x + dx, u.y + dy
				if 0 <= nx < gs and 0 <= ny < gs:
					u.planned_dir = (dx, dy)
					break
			continue

		# 找最近敌人
		tgt = min(enemies, key=lambda e: _dist(u.x, u.y, e.x, e.y))
		dx  = tgt.x - u.x
		dy  = tgt.y - u.y
		dist = _dist(u.x, u.y, tgt.x, tgt.y)

		eff_spd = spd(u)
		actual_style = style
		if actual_style == "auto":
			actual_style = "守阵" if faction == FACTION_RED else "噬溃"

		if actual_style == "守阵":
			# 守阵：保持队形推进，血量低时防御
			allies_close = sum(1 for a in units if a.uid != u.uid and _dist(u.x, u.y, a.x, a.y) <= 2)
			hp_ratio = u.hp / u.max_hp
			if dist <= u.attack_range() and hp_ratio < 0.4:
				u.planned_action = ACT_DEFEND
			else:
				# 向敌人方向移动
				mx = max(-eff_spd, min(eff_spd, dx))
				my = max(-eff_spd, min(eff_spd, dy))
				if abs(mx) + abs(my) > eff_spd:
					if abs(mx) >= abs(my): my = 0
					else: mx = 0
				u.planned_dir = (mx, my)
		elif actual_style == "噬溃":
			# 噬溃：激进追击，优先孤立敌人
			if dist <= eff_spd + u.attack_range():
				mx = max(-eff_spd, min(eff_spd, dx))
				my = max(-eff_spd, min(eff_spd, dy))
				if abs(mx) + abs(my) > eff_spd:
					if abs(mx) >= abs(my):
						my = 0
					else:
						mx = 0
				u.planned_dir = (mx, my)
		elif actual_style == "aggressive":
			mx = max(-eff_spd, min(eff_spd, dx))
			my = max(-eff_spd, min(eff_spd, dy))
			if abs(mx) + abs(my) > eff_spd:
				if abs(mx) >= abs(my):
					my = 0
				else:
					mx = 0
			u.planned_dir = (mx, my)

def run_game(red_style="守阵", dis_style="噬溃", noise=0.15, max_turns=40):
	cfg  = GameConfig()
	game = GameState(cfg)
	game.setup()

	# 模拟中自动处理进化：随机选路线A（50%）或B（50%）
	def auto_evolve():
		for u in list(game.alive_units()):
			if hasattr(u, "_pending_evo") or hasattr(u, "_pending_evo3"):
				from ui import EVO_TABLE
				opts = EVO_TABLE.get((u.faction, u.name), [])
				if opts:
					choice = random.choice(opts)
					game.evolve_unit(u.uid, choice["name"])
				else:
					game.skip_evolution(u.uid)

	for t in range(max_turns):
		if game.winner:
			break
		ai_plan(game, FACTION_RED, red_style, noise)
		ai_plan(game, FACTION_DIS, dis_style, noise)
		game.execute_turn()
		auto_evolve()

	if not game.winner:
		# 超时判断：存活HP总量
		red_hp = sum(u.hp for u in game.alive_units() if u.faction == FACTION_RED)
		dis_hp = sum(u.hp for u in game.alive_units() if u.faction == FACTION_DIS)
		if red_hp > dis_hp:
			game.winner = FACTION_RED
		elif dis_hp > red_hp:
			game.winner = FACTION_DIS
		else:
			game.winner = FACTION_RED

	return game.winner, game.turn

# ── 跑 200 局 ─────────────────────────────────────────────────────────────────

CONFIGS = [
	("★ 红守阵 vs 灾噬溃",  "守阵",      "噬溃",      0.15,  50),
	("  红激进 vs 灾守",    "aggressive","守阵",      0.15,  50),
	("  红红镜像",          "守阵",      "守阵",      0.15,  50),
	("  灾灾镜像",          "噬溃",      "噬溃",      0.15,  50),
]

print("=" * 54)
print("血轨 200局模拟（新经验规则）")
print("=" * 54)

all_red = 0; all_total = 0
for label, rs, ds, noise, n in CONFIGS:
	red_w = 0; turns_sum = 0
	for _ in range(n):
		w, t = run_game(rs, ds, noise)
		if w == FACTION_RED:
			red_w += 1
		turns_sum += t
	pct = red_w / n * 100
	avg_t = turns_sum / n
	mark = "✅" if abs(pct - 50) <= 6 else ("⚠️" if abs(pct - 50) <= 12 else "❌")
	print(f"{mark} {label:26s}  红:{red_w:3d}/{n}  {pct:5.1f}%  均{avg_t:.1f}回合")
	all_red += red_w; all_total += n

print("-" * 54)
print(f"   综合红胜率: {all_red}/{all_total} = {all_red/all_total*100:.1f}%")
print("=" * 54)

# ── 进化速度统计 ─────────────────────────────────────────────────────────────
from game_engine import GameState as GS
evo_turns = []
for _ in range(100):
	cfg  = GameConfig()
	game = GS(cfg)
	game.setup()
	first_evo = None
	for t in range(40):
		if game.winner:
			break
		ai_plan(game, FACTION_RED, "守阵", 0.15)
		ai_plan(game, FACTION_DIS, "噬溃", 0.15)
		game.execute_turn()
		if first_evo is None:
			for u in game.alive_units():
				if hasattr(u, "_pending_evo") or hasattr(u, "_pending_evo3"):
					first_evo = t + 1
					break
		for u in list(game.alive_units()):
			if hasattr(u, "_pending_evo") or hasattr(u, "_pending_evo3"):
				from ui import EVO_TABLE
				opts = EVO_TABLE.get((u.faction, u.name), [])
				if opts:
					game.evolve_unit(u.uid, random.choice(opts)["name"])
				else:
					game.skip_evolution(u.uid)
	evo_turns.append(first_evo or 40)

avg_evo = sum(evo_turns) / len(evo_turns)
print(f"\n首次进化平均回合：{avg_evo:.1f}  (目标: 5-10回合)")
print(f"最早第{min(evo_turns)}回合，最晚第{max(evo_turns)}回合")
