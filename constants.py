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


# ─────────────────── 地图配置 ───────────────────

class GameConfig:
	"""持有所有与地图尺寸相关的空间参数"""

	def __init__(self, mode: str = "5x5"):
		self.mode = mode

		if mode == "10x10":
			self.grid_size      = 10
			self.cell_size      = 68
			self.board_offset_x = 210
			self.board_offset_y = 58
			self.panel_width    = 190
			# 双本阵：关于中心 (4.5,4.5) 对称
			self.red_base       = (4, 3)
			self.dis_base       = (4, 6)
			self.shared_base    = None
		else:  # 5x5
			self.grid_size      = 5
			self.cell_size      = 110
			self.board_offset_x = 220
			self.board_offset_y = 80
			self.panel_width    = 200
			self.red_base       = None
			self.dis_base       = None
			self.shared_base    = (2, 2)

	@property
	def screen_w(self) -> int:
		return self.board_offset_x + self.grid_size * self.cell_size + self.panel_width + 20

	@property
	def screen_h(self) -> int:
		return self.board_offset_y + self.grid_size * self.cell_size + 118

	def cell_center(self, cx: int, cy: int) -> tuple:
		return (
			self.board_offset_x + cx * self.cell_size + self.cell_size // 2,
			self.board_offset_y + cy * self.cell_size + self.cell_size // 2,
		)

	def screen_to_cell(self, px: int, py: int):
		"""屏幕像素 → 棋盘格坐标；越界返回 None"""
		cx = (px - self.board_offset_x) // self.cell_size
		cy = (py - self.board_offset_y) // self.cell_size
		if 0 <= cx < self.grid_size and 0 <= cy < self.grid_size:
			return cx, cy
		return None

	def all_bases(self) -> list:
		if self.mode == "10x10":
			return [(self.red_base, FACTION_RED), (self.dis_base, FACTION_DIS)]
		return [(self.shared_base, None)]

	def is_base(self, x: int, y: int) -> bool:
		return any((x, y) == pos for pos, _ in self.all_bases())

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
		if self.mode == "10x10":
			# 221三层阵型，以 (4.5,4.5) 为中心点对称
			# 红方：前锋(y=3) x2，中坚(y=2) x2，后卫(y=1) x1
			red = [(3, 3), (6, 3), (4, 2), (5, 2), (4, 1)]
			# 灾方：点对称 (9-x, 9-y)
			dis = [(6, 6), (3, 6), (5, 7), (4, 7), (5, 8)]
			return {FACTION_RED: red, FACTION_DIS: dis}
		# 5×5：221三层阵型，以 (2,2) 为中心点对称
		# 红方：前锋(y=1) x2，中坚(y=0,x=0~1) x2，后卫(y=0,x=0最左)
		# 修正：back 单位从侧翼 (0,2) 移至 (0,1)，与前锋同行纵深、
		#       避免 back 单位到战场距离红灾不等的几何偏差
		red = [(1, 1), (2, 1), (0, 1), (1, 0), (0, 0)]
		# 灾方：点对称 (4-x, 4-y)
		dis = [(3, 3), (2, 3), (4, 3), (3, 4), (4, 4)]
		return {FACTION_RED: red, FACTION_DIS: dis}


# 向后兼容（5×5 默认值）
GRID_SIZE      = 5
CELL_SIZE      = 110
BOARD_OFFSET_X = 220
BOARD_OFFSET_Y = 80
PANEL_WIDTH    = 200
SCREEN_W       = BOARD_OFFSET_X + GRID_SIZE * CELL_SIZE + PANEL_WIDTH + 20
SCREEN_H       = BOARD_OFFSET_Y + GRID_SIZE * CELL_SIZE + 118
BASE_CAMP      = (2, 2)
