#!/usr/bin/env python3
"""
Rust2D / 幫我試玩看看 全球多人大廳與封包中繼伺服器 (Global Lobby & TCP Relay Server)
+ 開發者專用：全服遊玩玩家資料庫 (Developer-Only Player Analytics & Registry)
"""

import asyncio
import datetime
import json
import os
import signal
import sys
import time
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

DEV_SECRET_KEY = "bonegold_dev_2026"
DB_FILE = "players_db.json"


@dataclass
class Room:
    room_id: int
    host_name: str
    is_public: bool
    host_writer: asyncio.StreamWriter
    next_client_id: int = 1
    clients: Dict[int, asyncio.StreamWriter] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    @property
    def player_count(self) -> int:
        return 1 + len(self.clients)


class PlayerRegistry:
    def __init__(self, db_path: str = DB_FILE) -> None:
        self.db_path = db_path
        self.players: Dict[str, dict] = {}
        self.load()

    def load(self) -> None:
        if os.path.exists(self.db_path):
            try:
                with open(self.db_path, "r", encoding="utf-8") as f:
                    self.players = json.load(f)
                print(f"[*] Loaded {len(self.players)} players from {self.db_path}", flush=True)
            except Exception as e:
                print(f"[!] Failed to load db: {e}", flush=True)

    def save(self) -> None:
        try:
            with open(self.db_path, "w", encoding="utf-8") as f:
                json.dump(self.players, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[!] Failed to save db: {e}", flush=True)

    def record_player(
        self,
        name: str,
        platform: str = "Unknown",
        world: int = 1,
        hp: int = 100,
        max_hp: int = 100,
        atk: int = 10,
        defense: int = 0,
        ip: str = "",
        action: str = "ONLINE",
    ) -> None:
        if not name or name == "未知" or name == "生還者":
            return
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if name not in self.players:
            self.players[name] = {
                "name": name,
                "platform": platform,
                "first_seen": now_str,
                "last_seen": now_str,
                "ip": ip,
                "world": world,
                "hp": hp,
                "max_hp": max_hp,
                "attack": atk,
                "defense": defense,
                "play_count": 1,
                "last_action": action,
            }
            print(f"[★ NEW PLAYER REGISTERED] '{name}' on {platform} (IP: {ip})", flush=True)
        else:
            p = self.players[name]
            p["last_seen"] = now_str
            if platform != "Unknown":
                p["platform"] = platform
            if ip:
                p["ip"] = ip
            if world > 0:
                p["world"] = world
            if max_hp > 0:
                p["hp"] = hp
                p["max_hp"] = max_hp
            if atk > 0:
                p["attack"] = atk
            if defense >= 0:
                p["defense"] = defense
            p["play_count"] = p.get("play_count", 1) + 1
            p["last_action"] = action
            print(f"[★ PLAYER ACTIVE] '{name}' (World {world}, HP {hp}/{max_hp}, Atk {atk}, Def {defense})", flush=True)
        self.save()

    def get_all_players(self) -> list:
        return sorted(
            self.players.values(),
            key=lambda x: x.get("last_seen", ""),
            reverse=True,
        )


class RelayServer:
    def __init__(self) -> None:
        self.rooms: Dict[int, Room] = {}
        self.next_room_id: int = 1
        self.registry = PlayerRegistry()

    async def send_line(self, writer: asyncio.StreamWriter, line: str) -> bool:
        try:
            if not line.endswith("\n"):
                line += "\n"
            writer.write(line.encode("utf-8"))
            await writer.drain()
            return True
        except Exception:
            return False

    async def close_writer(self, writer: Optional[asyncio.StreamWriter]) -> None:
        if writer is None:
            return
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass

    def build_dev_html(self, authorized: bool) -> str:
        if not authorized:
            return f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Rust2D 開發者驗證</title>
    <style>
        body {{ background: #0d1117; color: #c9d1d9; font-family: sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }}
        .card {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 32px; width: 360px; text-align: center; box-shadow: 0 8px 24px rgba(0,0,0,0.6); }}
        h2 {{ color: #f1c40f; margin-top: 0; }}
        input {{ width: 90%; padding: 10px; margin: 16px 0; border: 1px solid #30363d; border-radius: 6px; background: #0d1117; color: #fff; font-size: 15px; text-align: center; }}
        button {{ width: 96%; padding: 10px; background: #238636; border: none; border-radius: 6px; color: #fff; font-weight: bold; font-size: 15px; cursor: pointer; }}
        button:hover {{ background: #2ea043; }}
    </style>
</head>
<body>
    <div class="card">
        <h2>🔒 開發者權限驗證</h2>
        <p style="color:#8b949e; font-size:14px;">此頁面僅供遊戲開發團隊檢視全服玩家資料庫</p>
        <form method="GET" action="/">
            <input type="password" name="key" placeholder="請輸入開發者存取金鑰" required autofocus />
            <button type="submit">解鎖資料庫</button>
        </form>
    </div>
</body>
</html>"""

        players = self.registry.get_all_players()
        rows = ""
        for p in players:
            plat_badge = (
                '<span class="badge pc">PC 電腦端</span>'
                if p.get("platform") == "PC"
                else '<span class="badge pe">Android 手機端</span>'
            )
            rows += f"""
            <tr>
                <td><strong>{p.get('name')}</strong></td>
                <td>{plat_badge}</td>
                <td>第 {p.get('world', 1)} 世界</td>
                <td><span class="hp">{p.get('hp', 100)} / {p.get('max_hp', 100)}</span></td>
                <td>⚔️ {p.get('attack', 10)} | 🛡️ {p.get('defense', 0)}</td>
                <td>{p.get('play_count', 1)} 次</td>
                <td>{p.get('last_seen', '-')}</td>
                <td><code>{p.get('ip', '-')}</code></td>
            </tr>
            """
        if not rows:
            rows = '<tr><td colspan="8" style="text-align:center; padding:20px; color:#888;">尚未記錄到玩家資料</td></tr>'

        return f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>【開發者專用】全服玩家資料庫・Rust2D 控制台</title>
    <style>
        body {{
            background: #0d1117;
            color: #c9d1d9;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            margin: 0;
            padding: 24px;
        }}
        .container {{
            max-width: 1100px;
            margin: 0 auto;
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 8px;
            padding: 24px;
            box-shadow: 0 8px 24px rgba(0,0,0,0.5);
        }}
        h1 {{
            color: #f1c40f;
            margin-top: 0;
            display: flex;
            align-items: center;
            gap: 12px;
            border-bottom: 1px solid #30363d;
            padding-bottom: 16px;
        }}
        .stats {{
            display: flex;
            gap: 16px;
            margin-bottom: 20px;
        }}
        .stat-card {{
            background: #21262d;
            padding: 12px 18px;
            border-radius: 6px;
            border: 1px solid #30363d;
        }}
        .stat-card .num {{
            font-size: 24px;
            font-weight: bold;
            color: #58a6ff;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 10px;
        }}
        th, td {{
            padding: 12px 14px;
            text-align: left;
            border-bottom: 1px solid #21262d;
        }}
        th {{
            background: #21262d;
            color: #8b949e;
            font-size: 13px;
        }}
        tr:hover {{
            background: #1c2128;
        }}
        .badge {{
            display: inline-block;
            padding: 3px 8px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: bold;
        }}
        .badge.pc {{ background: #1f6feb; color: #fff; }}
        .badge.pe {{ background: #238636; color: #fff; }}
        .hp {{ color: #e74c3c; font-weight: bold; }}
        code {{ background: #21262d; padding: 2px 6px; border-radius: 4px; font-size: 12px; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🕵️‍♂️【開發者專用】全服玩家資料庫</h1>
        <div class="stats">
            <div class="stat-card">
                <div>已登記玩家總數</div>
                <div class="num">{len(players)}</div>
            </div>
            <div class="stat-card">
                <div>當前活躍房間數</div>
                <div class="num">{len(self.rooms)}</div>
            </div>
        </div>
        <table>
            <thead>
                <tr>
                    <th>玩家暱稱</th>
                    <th>登入平台</th>
                    <th>世界進度</th>
                    <th>生命值 (HP)</th>
                    <th>戰力屬性</th>
                    <th>遊玩次數</th>
                    <th>最後連線時間</th>
                    <th>連線 IP</th>
                </tr>
            </thead>
            <tbody>
                {rows}
            </tbody>
        </table>
    </div>
</body>
</html>"""

    async def handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        peer = writer.get_extra_info("peername")
        client_ip = peer[0] if peer else "Unknown"
        role: str = "NONE"
        my_room: Optional[Room] = None
        my_client_id: int = 0
        current_player_name: str = "生還者"

        try:
            while True:
                raw = await reader.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                if not line:
                    continue

                # 0. 支援 HTTP 瀏覽器即時查看 (免設定、支援網頁表單解鎖)
                if line.startswith("GET ") and "HTTP/" in line:
                    while True:
                        hdr = await reader.readline()
                        if not hdr or hdr == b"\r\n" or hdr == b"\n":
                            break
                    path = line.split(" ")[1] if len(line.split(" ")) > 1 else "/"
                    if path == "/favicon.ico":
                        resp = b"HTTP/1.1 204 No Content\r\n\r\n"
                    else:
                        is_auth = (f"key={DEV_SECRET_KEY}" in path)
                        html_bytes = self.build_dev_html(is_auth).encode("utf-8")
                        resp = (
                            f"HTTP/1.1 200 OK\r\n"
                            f"Content-Type: text/html; charset=utf-8\r\n"
                            f"Content-Length: {len(html_bytes)}\r\n"
                            f"Connection: close\r\n\r\n"
                        ).encode("utf-8") + html_bytes
                    writer.write(resp)
                    await writer.drain()
                    await asyncio.sleep(0.05)
                    break

                # 1. 開發者協議: DEV_QUERY_PLAYERS|<secret_key>
                if line.startswith("DEV_QUERY_PLAYERS|"):
                    parts = line.split("|", 1)
                    key = parts[1].strip() if len(parts) >= 2 else ""
                    if key == DEV_SECRET_KEY:
                        players = self.registry.get_all_players()
                        await self.send_line(writer, f"DEV_PLAYERS_START|{len(players)}")
                        for p in players:
                            await self.send_line(
                                writer,
                                f"DEV_PLAYER|{p.get('name')}|{p.get('platform')}|"
                                f"{p.get('world', 1)}|{p.get('hp', 100)}|{p.get('max_hp', 100)}|"
                                f"{p.get('attack', 10)}|{p.get('defense', 0)}|"
                                f"{p.get('play_count', 1)}|{p.get('last_seen', '')}|{p.get('ip', '')}",
                            )
                        await self.send_line(writer, "DEV_PLAYERS_END")
                    else:
                        await self.send_line(writer, "DEV_ERR|ACCESS_DENIED")
                    continue

                # 2. 玩家同步狀態封包: PLAYER_SYNC|<name>|<platform>|<world>|<hp>|<max_hp>|<atk>|<def>
                if line.startswith("PLAYER_SYNC|"):
                    parts = line.split("|")
                    if len(parts) >= 8:
                        p_name = parts[1].strip()
                        p_plat = parts[2].strip()
                        try:
                            p_world = int(parts[3])
                            p_hp = int(float(parts[4]))
                            p_max_hp = int(float(parts[5]))
                            p_atk = int(float(parts[6]))
                            p_def = int(float(parts[7]))
                        except Exception:
                            p_world, p_hp, p_max_hp, p_atk, p_def = 1, 100, 100, 10, 0
                        current_player_name = p_name
                        self.registry.record_player(
                            name=p_name,
                            platform=p_plat,
                            world=p_world,
                            hp=p_hp,
                            max_hp=p_max_hp,
                            atk=p_atk,
                            defense=p_def,
                            ip=client_ip,
                            action="SYNC",
                        )
                    continue

                # 3. 房主註冊房間: RELAY_HOST|<host_name>|<is_public:0/1>
                if line.startswith("RELAY_HOST|") and role == "NONE":
                    parts = line.split("|", 3)
                    host_name = parts[1].strip() if len(parts) >= 2 and parts[1].strip() else "生還者"
                    is_public = (parts[2].strip() != "0") if len(parts) >= 3 else True

                    current_player_name = host_name
                    self.registry.record_player(
                        name=host_name,
                        ip=client_ip,
                        action="HOST_ROOM",
                    )

                    rid = self.next_room_id
                    self.next_room_id += 1
                    room = Room(
                        room_id=rid,
                        host_name=host_name[:31],
                        is_public=is_public,
                        host_writer=writer,
                    )
                    self.rooms[rid] = room
                    my_room = room
                    role = "HOST"
                    print(
                        f"[+] Room #{rid} created by '{room.host_name}' "
                        f"({'PUBLIC' if is_public else 'PRIVATE'}) from {peer}",
                        flush=True,
                    )
                    await self.send_line(writer, f"RELAY_HOST_OK|{rid}")
                    continue

                # 4. 查詢全球房間列表: RELAY_LIST
                if line == "RELAY_LIST":
                    for rid, r in list(self.rooms.items()):
                        pub_flag = 1 if r.is_public else 0
                        await self.send_line(
                            writer,
                            f"RELAY_ROOM|{rid}|{r.host_name}|{pub_flag}|{r.player_count}",
                        )
                    await self.send_line(writer, "RELAY_LIST_END")
                    continue

                # 5. 玩家加入房間: RELAY_JOIN|<room_id>
                if line.startswith("RELAY_JOIN|") and role == "NONE":
                    parts = line.split("|", 2)
                    try:
                        rid = int(parts[1].strip())
                    except Exception:
                        await self.send_line(writer, "RELAY_ERR|INVALID_ROOM_ID")
                        continue

                    room = self.rooms.get(rid)
                    if room is None:
                        await self.send_line(writer, "RELAY_ERR|ROOM_NOT_FOUND")
                        continue

                    cid = room.next_client_id
                    room.next_client_id += 1
                    room.clients[cid] = writer
                    my_room = room
                    my_client_id = cid
                    role = "CLIENT"
                    print(
                        f"[>] Client #{cid} joined Room #{rid} ('{room.host_name}') from {peer}",
                        flush=True,
                    )
                    await self.send_line(writer, f"RELAY_JOIN_OK|{rid}|{cid}")
                    await self.send_line(room.host_writer, f"RELAY_PEER_JOIN|{cid}")
                    continue

                # 6. 客戶端 HELLO 封包監聽以記錄玩家名單
                if role == "CLIENT" and my_room is not None and line.startswith("HELLO|"):
                    parts = line.split("|")
                    if len(parts) >= 2:
                        current_player_name = parts[1].strip()
                        world_id = int(parts[2]) if len(parts) >= 3 and parts[2].isdigit() else 1
                        self.registry.record_player(
                            name=current_player_name,
                            world=world_id,
                            ip=client_ip,
                            action="JOIN_ROOM",
                        )

                # 7. 房主轉發封包給指定玩家: RELAY_TO|<target_id>|<payload>
                if role == "HOST" and my_room is not None and line.startswith("RELAY_TO|"):
                    parts = line.split("|", 2)
                    if len(parts) == 3:
                        try:
                            target_id = int(parts[1])
                        except Exception:
                            continue
                        target_writer = my_room.clients.get(target_id)
                        if target_writer is not None:
                            await self.send_line(target_writer, parts[2])
                    continue

                # 8. 房主廣播封包給所有玩家: RELAY_BCAST|<exclude_id>|<payload>
                if role == "HOST" and my_room is not None and line.startswith("RELAY_BCAST|"):
                    parts = line.split("|", 2)
                    if len(parts) == 3:
                        try:
                            exclude_id = int(parts[1])
                        except Exception:
                            exclude_id = -1
                        payload = parts[2]
                        for cid, cw in list(my_room.clients.items()):
                            if cid != exclude_id:
                                await self.send_line(cw, payload)
                    continue

                # 9. 玩家送給房主的遊戲封包: 直接轉包為 RELAY_FROM|<client_id>|<line>
                if role == "CLIENT" and my_room is not None:
                    await self.send_line(
                        my_room.host_writer, f"RELAY_FROM|{my_client_id}|{line}"
                    )
                    continue

        except asyncio.CancelledError:
            pass
        except Exception as exc:
            print(f"[!] Error with {peer}: {exc}", flush=True)
        finally:
            if role == "HOST" and my_room is not None:
                print(
                    f"[-] Room #{my_room.room_id} ('{my_room.host_name}') closed",
                    flush=True,
                )
                self.rooms.pop(my_room.room_id, None)
                for cw in list(my_room.clients.values()):
                    await self.close_writer(cw)
                my_room.clients.clear()
            elif role == "CLIENT" and my_room is not None:
                my_room.clients.pop(my_client_id, None)
                print(
                    f"[<] Client #{my_client_id} ('{current_player_name}') left Room #{my_room.room_id}",
                    flush=True,
                )
                if my_room.room_id in self.rooms:
                    await self.send_line(
                        my_room.host_writer, f"RELAY_PEER_LEFT|{my_client_id}"
                    )
            await self.close_writer(writer)


async def main() -> None:
    port = int(os.environ.get("PORT", "25569"))
    host = "0.0.0.0"
    relay = RelayServer()
    server = await asyncio.start_server(relay.handle_client, host, port)
    addrs = ", ".join(str(sock.getsockname()) for sock in server.sockets or [])
    print(f"[*] Rust2D Global Relay & Player DB Server listening on {addrs}", flush=True)

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig_name in ("SIGINT", "SIGTERM"):
        sig = getattr(signal, sig_name, None)
        if sig is not None:
            try:
                loop.add_signal_handler(sig, stop_event.set)
            except NotImplementedError:
                pass

    serve_task = asyncio.create_task(server.serve_forever())
    await stop_event.wait()
    server.close()
    await server.wait_closed()
    serve_task.cancel()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
