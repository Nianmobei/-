# 血轨：红教团兵棋推演规程 — 主程序入口 v1.2
# 支持 5×5 / 10×10 | 拖拽移动 | 动画效果

import sys
import os
import pygame
from constants import *
from game_engine import GameState
from renderer import Renderer
from ui import UIState
from animator import AnimationManager


# ─────────────── 字体 ───────────────────

def load_fonts():
	candidates = [
		r"C:\Windows\Fonts\msyh.ttc",
		r"C:\Windows\Fonts\msyhbd.ttc",
		r"C:\Windows\Fonts\simsun.ttc",
		r"C:\Windows\Fonts\simhei.ttf",
		r"C:\Windows\Fonts\STKAITI.TTF",
	]
	fp = None
	for p in candidates:
		if os.path.isfile(p):
			fp = p; break

	def make(sz):
		if fp:
			try: return pygame.font.Font(fp, sz)
			except: pass
		return pygame.font.SysFont("arial", sz)

	return {
		"title": make(30), "bold": make(17),
		"small": make(13), "unit": make(11), "tiny": make(10),
	}


# ─────────────── 地图选择 ───────────────

def show_map_select(screen, fonts, clock) -> str:
	sw, sh = screen.get_size()
	BTN_W, BTN_H = 320, 90
	gap = 36
	total_h = BTN_H * 2 + gap
	sy = sh // 2 - total_h // 2
	btn5   = pygame.Rect(sw // 2 - BTN_W // 2, sy,            BTN_W, BTN_H)
	btn10  = pygame.Rect(sw // 2 - BTN_W // 2, sy + BTN_H + gap, BTN_W, BTN_H)

	while True:
		clock.tick(60)
		mx, my = pygame.mouse.get_pos()
		for event in pygame.event.get():
			if event.type == pygame.QUIT:
				pygame.quit(); sys.exit(0)
			if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
				if btn5.collidepoint(mx, my):   return "5x5"
				if btn10.collidepoint(mx, my):  return "10x10"

		screen.fill(C_BG_MENU)
		title = fonts["title"].render("血轨 · 选择战场规模", True, C_GOLD)
		screen.blit(title, title.get_rect(center=(sw // 2, sy - 58)))
		sub = fonts["small"].render("两种地图各有不同的本阵规则与初始布局", True, C_GRAY)
		screen.blit(sub, sub.get_rect(center=(sw // 2, sy - 30)))

		for btn, mode, d1, d2, col in [
			(btn5,  "5×5  标准战场",   "共享本阵 (2,2)",             "先连续占领2回合者胜", C_RED),
			(btn10, "10×10  扩展战场", "红阵(4,3) | 灾阵(4,6)",     "占领敌方本阵2回合者胜", C_DIS),
		]:
			hov = btn.collidepoint(mx, my)
			pygame.draw.rect(screen, (50, 32, 13) if hov else (26, 16, 9), btn, border_radius=10)
			pygame.draw.rect(screen, col if hov else C_PANEL_BDR, btn, 2, border_radius=10)
			ts = fonts["bold"].render(mode, True, col)
			screen.blit(ts, ts.get_rect(center=(btn.centerx, btn.y + 22)))
			d1s = fonts["small"].render(d1, True, C_WHITE)
			screen.blit(d1s, d1s.get_rect(center=(btn.centerx, btn.y + 48)))
			d2s = fonts["tiny"].render(d2, True, C_GRAY)
			screen.blit(d2s, d2s.get_rect(center=(btn.centerx, btn.y + 68)))

		pygame.display.flip()


# ─────────────── 主循环 ─────────────────

def main():
	pygame.init()
	cfg    = GameConfig("9x9")
	screen = pygame.display.set_mode((cfg.screen_w, cfg.screen_h))
	pygame.display.set_caption("兵戮灾 · 红之纷争  v1.4")
	clock  = pygame.time.Clock()
	fonts  = load_fonts()

	game     = GameState(cfg)
	game.setup()
	ui       = UIState(cfg.screen_w, cfg.screen_h)
	renderer = Renderer(screen, fonts)
	anim     = AnimationManager()

	ui.show_phase_banner = True
	ui.banner_text = "兵戮灾 · 红之纷争  战壕(4,4)减伤  高地(0,4)(8,4)攻+1  |  点击开始"

	running   = True
	pre_snap  = {}

	while running:
		dt = clock.tick(60) / 1000.0   # 秒

		for event in pygame.event.get():
			if event.type == pygame.QUIT:
				running = False; continue

			signal = ui.handle_event(event, game)

			if signal == "execute":
				# 保存执行前快照，立即执行，然后启动动画
				pre_snap = {u.uid: (u.x, u.y, u.hp) for u in game.alive_units()}
				game.execute_turn()
				anim.setup(pre_snap, game)
				ui.phase = "animating"

			elif signal == "new_round":
				for u in game.alive_units():
					u.clear_turn_state()
				ui.phase = "p1_plan"

		# 动画更新（每帧）
		if ui.phase == "animating":
			done = anim.update(dt, game)
			if done:
				ui.phase = "result"
				ui.queue_evolutions(game)
				if game.winner:
					ui.phase = "game_over"
					wname = "红骑士团" if game.winner == FACTION_RED else "灾兽群"
					ui.show_phase_banner = True
					ui.banner_text = f"🏆 {wname} 获胜！  {game.win_reason}  |  关闭窗口退出"

		renderer.draw(game, ui, anim if anim.is_playing else None)
		pygame.display.flip()

	pygame.quit()
	sys.exit(0)


if __name__ == "__main__":
	main()
