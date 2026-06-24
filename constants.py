# 血轨：常量与地图配置

FPS = 60

FACTION_RED = "red"
FACTION_DIS = "disaster"

# ─── 颜色 ───────────────────────────────────
C_BG         = (18, 12, 8)
C_BG_MENU    = (12, 8, 6)
C_GRID       = (55, 38, 28)
C_CELL       = (26, 17, 11)
C_CELL_ALT   = (32, 21, 14)
C_BASE_RED   = (70, 18, 10)
C_BASE_DIS   = (10, 42, 18)
C_BASE_SHARE = (55, 28, 10)
C_RED        = (200, 50, 40)
C_RED_LITE   = (240, 100, 80)
C_DIS        = (60, 160, 80)
C_DIS_LITE   = (100, 210, 130)
C_WHITE      = (230, 220, 210)
C_GRAY       = (120, 110, 100)
C_DARK_GRAY  = (55, 50, 46)
C_GOLD       = (200, 160, 58)
C_HIGHLIGHT  = (255, 220, 80)
C_SEL        = (255, 255, 60)
C_MOVE_HINT  = (50, 110, 200)
C_MOVE_SEL   = (100, 180, 255)
C_ATK_HINT   = (200, 70, 40)
C_ATK_PREV   = (220, 80, 40)
C_PANEL_BG   = (20, 13, 9)
C_PANEL_BDR  = (75, 48, 28)
C_HP_GREEN   = (55, 180, 60)
C_HP_RED     = (180, 50, 40)
C_OCCUPY_RED = (180, 40, 20)
C_OCCUPY_DIS = (40, 150, 70)
C_EMBYO      = (95, 88, 78)
C_GHOST      = (180, 180, 180)

# ─── 行动类型 ────────────────────────────────
ACT_NONE   = "none"
ACT_ATTACK = "attack"
ACT_DEFEND = "defend"
ACT_OCCUPY = "occupy"
ACT_MAKE   = "make"

# ─── 方向（保留，用于碰撞判定辅助） ──────────
DIR_NONE  = (0, 0)
DIR_UP    = (0, -1)
DIR_DOWN  = (0, 1)
DIR_LEFT  = (-1, 0)
DIR_RIGHT = (1, 0)

DIR_NAMES = {
	DIR_NONE: "不动",
	DIR_UP:   "↑",
	DIR_DOWN: "↓",
	DIR_LEFT: "←",
	DIR_RIGHT:"→",
}

EVO_A = "conservative"
EVO_B = "evolved"

# ─── 地形 ────────────────────────────────────
# 战壕 (4,4)：驻守减伤1；高地 (0,4) (8,4)：攻击+1
# 暂时清空地形（功能代码保留，重新启用时填回坐标即可）
TERRAIN_TRENCH = None            # 原 (4, 4)
TERRAIN_HIGH   = ()              # 原 ((0, 4), (8, 4))
C_TERRAIN_TRENCH = (40, 55, 80)
C_TERRAIN_HIGH   = (70, 55, 28)


# ─────────────────── 地图配置 ───────────────────

class GameConfig:
	"""持有所有与地图尺寸相关的空间参数（9×9 唯一地图）"""

	def __init__(self, mode: str = "9x9"):
		self.mode = "9x9"
		self.grid_size      = 9
		self.cell_size      = 76
		self.board_offset_x = 210
		self.board_offset_y = 58
		self.panel_width    = 190
		# 双本阵：关于中心 (4,4) 点对称，主阵微后置至边缘
		self.red_base       = (4, 1)
		self.dis_base       = (4, 7)
		self.shared_base    = None
		# 开局条件（由选择界面写入）
		self.conditions: set = set()
		# 极端地形：由 GameState.setup() 随机生成后写入
		self._extra_terrain: dict = {}  # {(x,y): "high"/"trench"}
		# 视角翻转（联机红方客户端：将己方翻转至屏幕下方）
		self.view_flip: bool = False

	@property
	def screen_w(self) -> int:
		return self.board_offset_x + self.grid_size * self.cell_size + self.panel_width + 20

	@property
	def screen_h(self) -> int:
		return self.board_offset_y + self.grid_size * self.cell_size + 118

	def game_to_screen(self, gx: float, gy: float) -> tuple:
		"""游戏坐标（支持浮点插值）→ 屏幕像素中心，考虑视角翻转。"""
		if self.view_flip:
			gx = self.grid_size - 1 - gx
			gy = self.grid_size - 1 - gy
		return (
			int(self.board_offset_x + gx * self.cell_size + self.cell_size / 2),
			int(self.board_offset_y + gy * self.cell_size + self.cell_size / 2),
		)

	def cell_center(self, cx: int, cy: int) -> tuple:
		return self.game_to_screen(cx, cy)

	def screen_to_cell(self, px: int, py: int):
		"""屏幕像素 → 棋盘格坐标；越界返回 None"""
		cx = (px - self.board_offset_x) // self.cell_size
		cy = (py - self.board_offset_y) // self.cell_size
		if 0 <= cx < self.grid_size and 0 <= cy < self.grid_size:
			if self.view_flip:
				cx = self.grid_size - 1 - cx
				cy = self.grid_size - 1 - cy
			return cx, cy
		return None

	def all_bases(self) -> list:
		return [(self.red_base, FACTION_RED), (self.dis_base, FACTION_DIS)]

	def is_base(self, x: int, y: int) -> bool:
		return any((x, y) == pos for pos, _ in self.all_bases())

	def terrain_at(self, x: int, y: int) -> str:
		"""返回地形类型：'trench' / 'high' / None（先查实例动态地形）"""
		if (x, y) in self._extra_terrain:
			return self._extra_terrain[(x, y)]
		if (x, y) == TERRAIN_TRENCH:
			return "trench"
		if (x, y) in TERRAIN_HIGH:
			return "high"
		return None

	def base_owner(self, x: int, y: int):
		for pos, owner in self.all_bases():
			if (x, y) == pos:
				return owner
		return None

	def base_color(self, owner):
		if owner == FACTION_RED:  return C_BASE_RED
		if owner == FACTION_DIS:  return C_BASE_DIS
		return C_BASE_SHARE

	def initial_positions(self) -> dict:
		# 9×9：32阵型（前3+后2），关于中心 (4,4) 点对称，主阵后置至 y=0/y=8
		# 红方：前锋(y=2) x3，后卫(y=1) x2（两翼护阵，中心留给本阵）
		red = [(3, 2), (4, 2), (5, 2), (3, 1), (5, 1)]
		# 灾方：点对称 (8-x, 8-y)
		dis = [(5, 6), (4, 6), (3, 6), (5, 7), (3, 7)]
		return {FACTION_RED: red, FACTION_DIS: dis}

	def tide_positions(self) -> dict:
		"""潮水开局：7个基础兵种，分布更分散"""
		red = [(2, 3), (3, 2), (4, 2), (5, 2), (6, 3), (2, 1), (6, 1)]
		dis = [(8 - x, 8 - y) for x, y in red]
		return {FACTION_RED: red, FACTION_DIS: dis}


# 全局常量（9×9 唯一地图）
GRID_SIZE      = 9
CELL_SIZE      = 76
BOARD_OFFSET_X = 210
BOARD_OFFSET_Y = 58
PANEL_WIDTH    = 190
SCREEN_W       = BOARD_OFFSET_X + GRID_SIZE * CELL_SIZE + PANEL_WIDTH + 20
SCREEN_H       = BOARD_OFFSET_Y + GRID_SIZE * CELL_SIZE + 118
