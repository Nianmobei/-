# 血轨：兵种定义与单位类
# 红骑士团（有序战争）vs 灾兽（混乱传播）

from constants import *

# ─────────────────── 兵种模板 ───────────────────

UNIT_TEMPLATES = {
	# ── 红骑士团 ──────────────────────────────────
	# 1级
	"铁卫":   dict(faction=FACTION_RED, level=1, max_hp=4, atk=2, spd=1, trait="列阵",  ranged=False, can_make=False),
	# 2级
	"盾卫":   dict(faction=FACTION_RED, level=2, max_hp=6, atk=2, spd=2, trait="铁壁",  ranged=False, can_make=False),
	"弩卫":   dict(faction=FACTION_RED, level=2, max_hp=5, atk=2, spd=3, trait="劲弩",  ranged=True,  can_make=False),
	# 3级 A路（精锐化）——速度封顶3，固有防+1由_calc_damage处理
	"盾卫3A": dict(faction=FACTION_RED, level=3, max_hp=8, atk=3, spd=2, trait="铁壁",  ranged=False, can_make=False),
	"弩卫3A": dict(faction=FACTION_RED, level=3, max_hp=7, atk=3, spd=3, trait="劲弩",  ranged=True,  can_make=False),
	# 3级 B路（突破化）——战车冲阵速度3（原5，9×9棋盘过强）
	"旗卫":   dict(faction=FACTION_RED, level=3, max_hp=8, atk=4, spd=3, trait="战旗",  ranged=False, can_make=False),
	"战车":   dict(faction=FACTION_RED, level=3, max_hp=7, atk=2, spd=3, trait="冲阵",  ranged=False, can_make=False),
	# ── 灾兽 ──────────────────────────────────────
	# 1级
	"散兽":   dict(faction=FACTION_DIS, level=1, max_hp=3, atk=2, spd=1, trait="噬溃",  ranged=False, can_make=False),
	# 2级
	"甲兽":   dict(faction=FACTION_DIS, level=2, max_hp=6, atk=2, spd=2, trait="硬壳",  ranged=False, can_make=False),
	"炮兽":   dict(faction=FACTION_DIS, level=2, max_hp=5, atk=2, spd=3, trait="投射",  ranged=True,  can_make=False),
	# 3级 A路（强化）
	"甲兽3A": dict(faction=FACTION_DIS, level=3, max_hp=8, atk=3, spd=2, trait="硬壳",  ranged=False, can_make=False),
	"炮兽3A": dict(faction=FACTION_DIS, level=3, max_hp=7, atk=3, spd=3, trait="投射",  ranged=True,  can_make=False),
	# 3级 B路（灾化）
	"恐兽":   dict(faction=FACTION_DIS, level=3, max_hp=8, atk=4, spd=2, trait="威压",  ranged=False, can_make=False),
	"猎群兽": dict(faction=FACTION_DIS, level=3, max_hp=7, atk=2, spd=3, trait="集群",  ranged=True,  can_make=False),
	# 胚体
	"胚体":   dict(faction=None,        level=0, max_hp=1, atk=0, spd=1, trait="",      ranged=False, can_make=False),
}

_uid_counter = [0]


def _new_uid():
	_uid_counter[0] += 1
	return _uid_counter[0]


class Unit:
	def __init__(self, name: str, faction: str, x: int, y: int):
		tmpl = UNIT_TEMPLATES[name]
		self.uid       = _new_uid()
		self.name      = name
		self.faction   = faction if faction else tmpl["faction"]
		self.level     = tmpl["level"]
		self.max_hp    = tmpl["max_hp"]
		self.hp        = self.max_hp
		self.base_atk  = tmpl["atk"]
		self.base_spd  = tmpl["spd"]
		self.trait     = tmpl["trait"]
		self.ranged    = tmpl["ranged"]
		self.can_make  = tmpl.get("can_make", True)
		self.x         = x
		self.y         = y
		self.is_embryo = (name == "胚体")
		# 进化
		self.kills     = 0
		self.made_unit = False
		# 回合内临时状态
		# planned_dir = (dx, dy)，可以是多格位移（菱形范围）
		self.planned_dir    = DIR_NONE
		self.planned_action = ACT_NONE
		self.pending_dmg    = 0
		self.stun_move      = False
		self.did_move       = False
		self.defending      = False
		self.dead           = False

	@property
	def atk(self):
		return self.base_atk

	@property
	def spd(self):
		return self.base_spd

	def has_trait(self, t: str) -> bool:
		return self.trait == t

	def attack_range(self) -> int:
		return 2 if self.ranged else 1

	def move_range(self) -> int:
		"""移动范围 = 速度（菱形半径）"""
		return self.base_spd

	def clear_turn_state(self):
		self.planned_dir    = DIR_NONE
		self.planned_action = ACT_NONE
		self.pending_dmg    = 0
		self.defending      = False
		self.did_move       = False
		self.stun_move      = False
		for attr in ("_collision_partner", "_pending_evo", "_pending_evo3", "_high_ground_bonus"):
			if hasattr(self, attr):
				delattr(self, attr)

	def take_damage(self, dmg: int):
		self.hp = max(0, self.hp - max(0, dmg))
		if self.hp == 0:
			self.dead = True

	def heal(self, amount: int):
		self.hp = min(self.max_hp, self.hp + amount)

	def __repr__(self):
		return f"<{self.name}[{self.uid}] @({self.x},{self.y}) hp={self.hp}/{self.max_hp}>"
