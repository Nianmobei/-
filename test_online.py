# test_online.py  —  联机流程自动测试（无 Pygame UI）

import subprocess, sys, time, socket, tempfile, os
sys.path.insert(0, r"D:\学习资料\创作项目\血棋")

from network import NetworkClient
from constants import FACTION_RED, FACTION_DIS

PORT = 17655
URL  = f"ws://localhost:{PORT}"
PASS = "✅"
FAIL = "❌"


def start_server():
	log_path = os.path.join(tempfile.gettempdir(), "xueqi_srv.log")
	lf = open(log_path, "w")
	proc = subprocess.Popen(
		[sys.executable, r"D:\学习资料\创作项目\血棋\server.py", str(PORT)],
		stdout=lf, stderr=lf,
		creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
	)
	for _ in range(40):
		time.sleep(0.2)
		try:
			s = socket.create_connection(("localhost", PORT), timeout=0.3)
			s.close()
			print(f"    服务器就绪 pid={proc.pid}")
			return proc
		except OSError:
			pass
	# 超时 → 打印日志
	lf.flush(); lf.close()
	with open(log_path) as f:
		print("    服务器日志:\n" + f.read()[:600])
	return proc


def wait_msg(net: NetworkClient, msg_type: str, timeout=8.0):
	t0 = time.time()
	while time.time() - t0 < timeout:
		for msg in net.poll():
			if msg.get("type") == msg_type:
				return msg
		time.sleep(0.05)
	return None


def check(label, cond, detail=""):
	s = PASS if cond else FAIL
	print(f"  {s}  {label}" + (f"  [{detail}]" if detail else ""))
	return cond


def run_test():
	print("\n══════════════════════════════════════")
	print("  兵戮灾 · 联机流程自动测试")
	print("══════════════════════════════════════")
	ok = True

	print("\n[1] 启动服务器")
	srv = start_server()

	try:
		print("\n[2] 两客户端连接")
		host  = NetworkClient(); host.connect(URL)
		guest = NetworkClient(); guest.connect(URL)
		time.sleep(1.5)
		ok &= check("host 已连接",  host.connected)
		ok &= check("guest 已连接", guest.connected)
		if not ok:
			return False

		print("\n[3] 创建房间")
		host.send({"type": "create_room", "name": "房主"})
		msg = wait_msg(host, "room_created")
		ok &= check("room_created", msg is not None)
		if not msg:
			return False
		room_id = msg["room_id"]
		ok &= check("房主=红方", msg["faction"] == FACTION_RED, msg["faction"])
		ok &= check("房间ID 4位", len(room_id) == 4, room_id)

		print("\n[4] 加入房间")
		guest.send({"type": "join_room", "room_id": room_id, "name": "客人"})
		r_joined = wait_msg(guest, "room_joined")
		r_notify = wait_msg(host,  "player_joined")
		ok &= check("guest room_joined",  r_joined is not None)
		ok &= check("host player_joined", r_notify is not None)
		if r_joined:
			ok &= check("客人=灾方", r_joined["faction"] == FACTION_DIS, r_joined["faction"])

		print("\n[5] 双方就绪 → 开局")
		host.send({"type": "set_conditions", "conditions": []})
		time.sleep(0.2)
		host.send({"type": "ready"})
		guest.send({"type": "ready"})
		gs_host  = wait_msg(host,  "game_start", timeout=6)
		gs_guest = wait_msg(guest, "game_start", timeout=6)
		ok &= check("host game_start",  gs_host  is not None)
		ok &= check("guest game_start", gs_guest is not None)
		if not gs_host:
			return False
		units = gs_host["units"]
		reds  = [u for u in units if u["faction"] == FACTION_RED]
		diss  = [u for u in units if u["faction"] == FACTION_DIS]
		ok &= check("单位总数 10", len(units) == 10, str(len(units)))
		ok &= check("红方 5 个",   len(reds) == 5,   str(len(reds)))
		ok &= check("灾方 5 个",   len(diss) == 5,   str(len(diss)))

		print("\n[6] 回合1：双方提交规划")
		host.send({"type": "submit_plan",
			"plans": [{"uid": u["uid"], "dir": [0, 1],  "action": "none"} for u in reds]})
		opp = wait_msg(guest, "opponent_submitted", timeout=3)
		ok &= check("guest 收到 opponent_submitted", opp is not None)
		guest.send({"type": "submit_plan",
			"plans": [{"uid": u["uid"], "dir": [0, -1], "action": "none"} for u in diss]})
		tr_host  = wait_msg(host,  "turn_result", timeout=5)
		tr_guest = wait_msg(guest, "turn_result", timeout=5)
		ok &= check("host turn_result",  tr_host  is not None)
		ok &= check("guest turn_result", tr_guest is not None)
		if tr_host:
			ok &= check("turn=2",       tr_host["turn"] == 2, str(tr_host["turn"]))
			ok &= check("log 非空",     len(tr_host.get("log", [])) > 0)
			ok &= check("无立即胜负",   tr_host.get("winner") is None)

		print("\n[7] 回合2：验证双端单位状态一致")
		u2  = tr_host["units"]
		r2  = [u for u in u2 if u["faction"] == FACTION_RED]
		d2  = [u for u in u2 if u["faction"] == FACTION_DIS]
		host.send({"type": "submit_plan",
			"plans": [{"uid": u["uid"], "dir": [0, 1],  "action": "none"} for u in r2]})
		guest.send({"type": "submit_plan",
			"plans": [{"uid": u["uid"], "dir": [0, -1], "action": "none"} for u in d2]})
		tr2h = wait_msg(host,  "turn_result", timeout=5)
		tr2g = wait_msg(guest, "turn_result", timeout=5)
		ok &= check("回合2 两端均收到 turn_result", tr2h is not None and tr2g is not None)
		if tr2h and tr2g:
			hps_h = sorted(u["hp"] for u in tr2h["units"])
			hps_g = sorted(u["hp"] for u in tr2g["units"])
			ok &= check("双端 HP 完全一致", hps_h == hps_g, f"{hps_h}")
			# 单位应该有受伤（双方接触）
			total_hp = sum(u["hp"] for u in tr2h["units"])
			max_hp   = sum(u["max_hp"] for u in tr2h["units"])
			ok &= check("有战斗伤害", total_hp < max_hp, f"{total_hp}/{max_hp}")

		print("\n[8] 断线：host 关闭 → guest 收通知")
		host._send_q.put(None)   # 放 None 触发 send_loop 异常关闭
		time.sleep(1.0)
		disc = wait_msg(guest, "opponent_disconnected", timeout=4)
		ok &= check("guest 收到 opponent_disconnected", disc is not None)

	finally:
		try:
			import signal
			srv.send_signal(subprocess.signal.CTRL_BREAK_EVENT)
		except Exception:
			srv.terminate()
		srv.wait(timeout=3)

	print("\n══════════════════════════════════════")
	r = PASS if ok else FAIL
	print(f"  {r}  {'全部通过' if ok else '存在失败项，请检查上方'}")
	print("══════════════════════════════════════\n")
	return ok


if __name__ == "__main__":
	sys.exit(0 if run_test() else 1)
