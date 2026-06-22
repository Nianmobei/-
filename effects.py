# 血轨：战场效果定义

import random

EFFECTS = [
	{
		"name": "血潮",
		"desc": "所有棋子攻击力+1",
		"tag":  "blood_surge",
	},
	{
		"name": "蚀地蔓延",
		"desc": "棋盘边缘变为蚀地，进入者本回合无法移动",
		"tag":  "erode",
	},
	{
		"name": "红之低语",
		"desc": "所有棋子速度+1",
		"tag":  "red_whisper",
	},
	{
		"name": "寂静",
		"desc": "本回合无人可以攻击",
		"tag":  "silence",
	},
	{
		"name": "兽群本能",
		"desc": "攻击时相邻有己方棋子则攻击力+1",
		"tag":  "beast_instinct",
	},
	{
		"name": "铁砧回响",
		"desc": "本回合不移动则回合结束恢复1生命",
		"tag":  "anvil_echo",
	},
	{
		"name": "裂痕",
		"desc": "本阵格本回合不可被占领",
		"tag":  "rift",
	},
	{
		"name": "回音",
		"desc": "回合结束时所有棋子恢复1生命",
		"tag":  "echo",
	},
	{
		"name": "崩解",
		"desc": "移动阶段后，双方各指定一个敌方棋子失去1生命",
		"tag":  "collapse",
	},
	{
		"name": "血轨共鸣",
		"desc": "本回合所有棋子可额外行动一次（移动或攻击）",
		"tag":  "resonance",
	},
]

EFFECT_TAGS = [e["tag"] for e in EFFECTS]


class EffectManager:
	"""管理当前战场效果的循环"""

	def __init__(self):
		# 开局随机抽取起点
		start = random.randint(0, len(EFFECTS) - 1)
		self._order = EFFECTS[start:] + EFFECTS[:start]
		self._ptr = 0
		self.current = self._order[0]
		self.erode_ring = 0  # 蚀地扩张层数

	def advance(self):
		"""每3回合调用一次，切换到下一个效果"""
		self._ptr = (self._ptr + 1) % len(self._order)
		self.current = self._order[self._ptr]
		if self.current["tag"] == "erode":
			self.erode_ring += 1

	def tag(self) -> str:
		return self.current["tag"]

	def name(self) -> str:
		return self.current["name"]

	def desc(self) -> str:
		return self.current["desc"]

	def erode_cells(self, grid_size: int = 9) -> set:
		"""返回当前蚀地格坐标集合（圆环向内扩张）"""
		if self.tag() != "erode":
			return set()
		ring = self.erode_ring
		cells = set()
		gs = grid_size
		for x in range(gs):
			for y in range(gs):
				if x <= ring or x >= gs - 1 - ring or y <= ring or y >= gs - 1 - ring:
					cells.add((x, y))
		return cells
