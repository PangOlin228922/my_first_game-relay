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
import urllib.parse
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

DEV_SECRET_KEY = "bonegold_dev_2026"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
VERSION_INFO_FILE = os.path.join(SCRIPT_DIR, "version_info.json")
DOWNLOADS_DIR = os.path.join(SCRIPT_DIR, "downloads")

def find_release_file(filename: str):
    candidates = [
        os.path.join(DOWNLOADS_DIR, filename),
        os.path.join(SCRIPT_DIR, filename),
        os.path.join("downloads", filename),
        filename,
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None

DEFAULT_VERSION_INFO = {
    "version": "v0.67.130",
    "version_code": 6830,
    "release_date": "2026-11-14",
    "title": "背包操作與多人副本同步更新",
    "changelog": [
        "修復製造面板點擊觸控判定與配方對齊",
        "同步手機與電腦端特製料理與藥水增益效果",
        "優化客戶端版本比對機制與自動下載更新流程"
    ],
    "apk_filename": "game.apk",
    "exe_filename": "game.exe",
    "zip_filename": "game.zip"
}

def load_version_info() -> dict:
    if os.path.exists(VERSION_INFO_FILE):
        try:
            with open(VERSION_INFO_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return DEFAULT_VERSION_INFO

def save_version_info(data: dict) -> None:
    try:
        with open(VERSION_INFO_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[!] Failed to save version info: {e}", flush=True)

def is_version_newer(srv_ver: str, client_ver: str) -> bool:
    try:
        def parse_v(v: str):
            clean = v.lstrip("vV").strip()
            return [int(x) for x in clean.split(".") if x.isdigit()]
        return parse_v(srv_ver) > parse_v(client_ver)
    except Exception:
        return False

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
        self.wiped_path = "wiped_players.json"
        self.players: Dict[str, dict] = {}
        self.wiped_players: set = set()
        self.load()
        self.load_wiped()

    def load_wiped(self) -> None:
        if os.path.exists(self.wiped_path):
            try:
                with open(self.wiped_path, "r", encoding="utf-8") as f:
                    self.wiped_players = set(json.load(f))
                print(f"[*] Loaded {len(self.wiped_players)} wiped players from {self.wiped_path}", flush=True)
            except Exception as e:
                print(f"[!] Failed to load wiped db: {e}", flush=True)

    def save_wiped(self) -> None:
        try:
            with open(self.wiped_path, "w", encoding="utf-8") as f:
                json.dump(list(self.wiped_players), f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[!] Failed to save wiped db: {e}", flush=True)

    def is_wiped(self, name: str) -> bool:
        return name in self.wiped_players

    def consume_wipe(self, name: str) -> bool:
        """單次消耗清除標記：若在待清除名單中，立即移除並保存，保證同名只被清除一次"""
        if not name:
            return False
        if name in self.wiped_players:
            self.wiped_players.discard(name)
            self.save_wiped()
            print(f"[WIPE CONSUMED] Discharged pending wipe for '{name}'. Name is now free to reuse without repeat wipes.", flush=True)
            return True
        return False

    def clear_all_wipes(self) -> None:
        """清空所有待清除標記，解除全部同名鎖定"""
        self.wiped_players.clear()
        self.save_wiped()
        print("[ALL WIPES CLEARED] Wiped players registry cleared.", flush=True)

    def delete_and_wipe_player(self, name: str) -> bool:
        if not name:
            return False
        if name in self.players:
            del self.players[name]
            self.save()
            print(f"[PLAYER WIPED] Removed '{name}' from DB.", flush=True)
        return True

    def clear_wiped_ack(self, name: str) -> None:
        if name in self.wiped_players:
            self.wiped_players.discard(name)
            self.save_wiped()

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
        if not name or name == "未知":
            return
        if self.is_wiped(name):
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
            print(f"[NEW PLAYER REGISTERED] '{name}' on {platform} (IP: {ip})", flush=True)
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
            print(f"[PLAYER ACTIVE] '{name}' (World {world}, HP {hp}/{max_hp}, Atk {atk}, Def {defense})", flush=True)
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
        self.active_writers: Dict[str, asyncio.StreamWriter] = {}

    async def wipe_player_and_kick(self, name: str) -> bool:
        if not name:
            return False
        self.registry.delete_and_wipe_player(name)
        online = False
        # 1. 直接發送強制清除指令給現有活躍連線
        writer = self.active_writers.pop(name, None)
        if writer:
            try:
                await self.send_line(writer, "FORCE_WIPE_ACCOUNT")
                await self.close_writer(writer)
                online = True
            except Exception:
                pass
        # 2. 檢查所有房間房主
        for rid, room in list(self.rooms.items()):
            if room.host_name == name:
                try:
                    await self.send_line(room.host_writer, "FORCE_WIPE_ACCOUNT")
                    await self.close_writer(room.host_writer)
                    online = True
                except Exception:
                    pass
        # 3. 若玩家在線，指令已即時送達並清空其本地設備，無需排隊，可自由重設同名！
        # 若該玩家剛好不在線，才需要放入一次性待清除名冊 (等其下次連線時清除一次並自動銷毀標記)
        if not online:
            self.registry.wiped_players.add(name)
            self.registry.save_wiped()
            print(f"[PLAYER WIPED] Offline player '{name}' queued for 1-time wipe on next connect.", flush=True)
        else:
            self.registry.wiped_players.discard(name)
            self.registry.save_wiped()
            print(f"[FORCE WIPE EXECUTED] Online player '{name}' wiped and kicked instantly. Name is clean.", flush=True)
        return True

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


    def build_download_html(self) -> str:
        vinfo = load_version_info()
        ver = vinfo.get("version", "v0.67.67")
        vdate = vinfo.get("release_date", "2026-11-13")
        vtitle = vinfo.get("title", "最新版本更新")
        changelog_items = "".join(f"<li>{item}</li>" for item in vinfo.get("changelog", []))
        total_players = len(self.registry.players)
        active_rooms = len(self.rooms)

        apk_path = find_release_file(vinfo.get("apk_filename", "game.apk"))
        exe_path = find_release_file(vinfo.get("exe_filename", "game.exe"))
        zip_path = find_release_file(vinfo.get("zip_filename", "game.zip"))
        apk_size = f"{os.path.getsize(apk_path) / 1024:.1f} KB" if (apk_path and os.path.exists(apk_path)) else "168 KB"
        exe_size = f"{os.path.getsize(exe_path) / 1024:.1f} KB" if (exe_path and os.path.exists(exe_path)) else "582 KB"
        zip_size = f"{os.path.getsize(zip_path) / 1024:.1f} KB" if (zip_path and os.path.exists(zip_path)) else "582 KB"

        return f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>這是測試版本</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            background: #0f141c;
            color: #d1d7e0;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            align-items: center;
            padding: 32px 16px;
        }}
        .container {{
            max-width: 620px;
            width: 100%;
            background: #161d27;
            border: 1px solid #2a3442;
            border-radius: 10px;
            padding: 32px 28px;
        }}
        .header {{
            text-align: center;
            margin-bottom: 24px;
        }}
        .title {{
            font-size: 24px;
            font-weight: 700;
            color: #f0f6fc;
            margin-bottom: 6px;
        }}
        .subtitle {{
            color: #8b949e;
            font-size: 14px;
        }}
        .badge-row {{
            display: flex;
            justify-content: center;
            gap: 8px;
            margin-top: 14px;
            flex-wrap: wrap;
        }}
        .badge {{
            display: inline-block;
            background: #0f141c;
            border: 1px solid #2a3442;
            border-radius: 6px;
            padding: 4px 10px;
            font-size: 12px;
            color: #8b949e;
        }}
        .badge-ver {{
            color: #3fb950;
            border-color: #238636;
        }}
        .badge-live {{
            color: #58a6ff;
            border-color: #1f6feb;
        }}
        .btn-group {{
            display: flex;
            flex-direction: column;
            gap: 12px;
            margin: 24px 0;
        }}
        @media (min-width: 520px) {{
            .btn-group {{
                flex-direction: row;
            }}
        }}
        .btn {{
            flex: 1;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            padding: 16px 18px;
            border-radius: 8px;
            text-decoration: none;
            font-weight: 600;
            font-size: 15px;
            border: 1px solid transparent;
            cursor: pointer;
            transition: background 0.15s ease, border-color 0.15s ease;
        }}
        .btn-apk {{
            background: #238636;
            color: #ffffff;
            border-color: #2ea043;
        }}
        .btn-apk:hover {{
            background: #2ea043;
        }}
        .btn-exe {{
            background: #1f6feb;
            color: #ffffff;
            border-color: #388bfd;
        }}
        .btn-exe:hover {{
            background: #388bfd;
        }}
        .btn small {{
            font-size: 12px;
            font-weight: 400;
            opacity: 0.9;
            margin-top: 4px;
        }}
        .card-section {{
            background: #0f141c;
            border: 1px solid #2a3442;
            border-radius: 8px;
            padding: 18px 20px;
            margin-bottom: 18px;
        }}
        .card-section h3 {{
            color: #f0f6fc;
            font-size: 15px;
            margin-bottom: 10px;
        }}
        .card-section ul {{
            padding-left: 20px;
            color: #8b949e;
            font-size: 13px;
            line-height: 1.8;
        }}
        .card-section ul li {{
            margin-bottom: 3px;
        }}
        .guide-box {{
            background: #0f141c;
            border: 1px solid #2a3442;
            border-radius: 8px;
            padding: 14px 18px;
            font-size: 13px;
            color: #8b949e;
            line-height: 1.7;
        }}
        .guide-box strong {{
            color: #c9d1d9;
        }}
        .footer {{
            text-align: center;
            font-size: 12px;
            color: #484f58;
            margin-top: 24px;
        }}
        .footer a {{
            color: #58a6ff;
            text-decoration: none;
        }}
        .footer a:hover {{
            text-decoration: underline;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="title">這是測試版本</div>
            <div class="subtitle">客戶端下載與伺服器狀態</div>
            <div class="badge-row">
                <span class="badge badge-ver">版本：{ver}</span>
                <span class="badge badge-live">伺服器狀態：正常</span>
                <span class="badge">已登記角色：{total_players}</span>
                <span class="badge">活躍房間：{active_rooms}</span>
            </div>
        </div>

        <div class="btn-group">
            <a href="/download/apk" class="btn btn-apk">
                <span>下載 Android 版</span>
                <small>game.apk ({apk_size})</small>
            </a>
            <a href="/download/zip" class="btn btn-exe">
                <span>下載 Windows 版</span>
                <small>game.zip ({zip_size})</small>
            </a>
        </div>

        <div class="card-section">
            <h3>更新內容 ({vdate})</h3>
            <ul>
                {changelog_items}
            </ul>
        </div>

        <div class="guide-box">
            <strong>說明：</strong><br>
            • <strong>Android</strong>：下載安裝後即可遊玩。<br>
            • <strong>Windows</strong>：下載解壓縮後執行 game.exe 即可遊玩。
        </div>

        <div class="footer">
            這是測試版本 &copy; 2026 ・ <a href="/dev">後台管理</a>
        </div>
    </div>
</body>
</html>"""

    def build_dev_html(self, authorized: bool) -> str:
        if not authorized:
            return f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>開發者驗證</title>
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
        <h2>開發者驗證</h2>
        <p style="color:#8b949e; font-size:14px;">此頁面供管理人員檢視玩家資料庫</p>
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
                <td>{p.get('attack', 10)} / {p.get('defense', 0)}</td>
                <td>{p.get('play_count', 1)} 次</td>
                <td>{p.get('last_seen', '-')}</td>
                <td><code>{p.get('ip', '-')}</code></td>
                <td>
                    <button class="btn-del" onclick="confirmDelete('{p.get('name')}')">註銷清除</button>
                </td>
            </tr>
            """
        if not rows:
            rows = '<tr><td colspan="9" style="text-align:center; padding:20px; color:#888;">尚未記錄到玩家資料</td></tr>'

        return f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>玩家資料庫管理</title>
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
        .btn-del {{
            background: #da3633;
            color: #ffffff;
            border: 1px solid rgba(248,81,73,0.4);
            padding: 5px 10px;
            border-radius: 6px;
            font-size: 12px;
            font-weight: bold;
            cursor: pointer;
            transition: all 0.2s;
        }}
        .btn-del:hover {{
            background: #b62324;
            transform: scale(1.04);
        }}
    </style>
</head>
<body>
    <div class="container">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px;">
            <h1 style="margin:0;">玩家資料庫</h1>
            <a href="/dev/clear_wipes?key={DEV_SECRET_KEY}" onclick="return confirm('確定要清空所有待清除標記嗎？\\n\\n這將解除所有先前被清除帳號的同名限制，任何名稱皆可立即重新登入註冊！')" style="background:#21262d; border:1px solid #30363d; color:#c9d1d9; padding:8px 16px; border-radius:6px; text-decoration:none; font-size:13px; font-weight:bold;">清空待清除名單</a>
        </div>
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
                    <th>攻擊 / 防禦</th>
                    <th>遊玩次數</th>
                    <th>最後連線時間</th>
                    <th>連線 IP</th>
                    <th>管理操作</th>
                </tr>
            </thead>
            <tbody>
                {rows}
            </tbody>
        </table>
    </div>
    <script>
    function confirmDelete(name) {{
        if (confirm("【註銷玩家帳號】\\n\\n確定要註銷玩家【" + name + "】嗎？\\n\\n執行後：\\n1. 資料庫立即清除該玩家紀錄\\n2. 該玩家設備本地存檔刪除並強制閃退\\n3. 該玩家重進後可重新輸入暱稱正常開始（不會被重複清除）！")) {{
            window.location.href = "/dev/delete?key=" + encodeURIComponent("{DEV_SECRET_KEY}") + "&name=" + encodeURIComponent(name);
        }}
    }}
    </script>
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

                # 0. 支援 HTTP 瀏覽器即時查看 (免設定、支援網頁表單解鎖與帳號註銷)
                if (line.startswith("GET ") or line.startswith("POST ")) and "HTTP/" in line:
                    while True:
                        hdr = await reader.readline()
                        if not hdr or hdr == b"\r\n" or hdr == b"\n":
                            break
                    raw_path = line.split(" ")[1] if len(line.split(" ")) > 1 else "/"
                    parsed = urllib.parse.urlparse(raw_path)
                    path = parsed.path
                    qs = urllib.parse.parse_qs(parsed.query)

                    if path == "/favicon.ico":
                        resp = b"HTTP/1.1 204 No Content\r\n\r\n"
                    elif path == "/dev/delete":
                        key = qs.get("key", [""])[0]
                        target_name = qs.get("name", [""])[0]
                        if key == DEV_SECRET_KEY and target_name:
                            await self.wipe_player_and_kick(target_name)
                        resp = (
                            f"HTTP/1.1 302 Found\r\n"
                            f"Location: /dev?key={DEV_SECRET_KEY}\r\n"
                            f"Connection: close\r\n\r\n"
                        ).encode("utf-8")
                    elif path == "/dev/clear_wipes":
                        key = qs.get("key", [""])[0]
                        if key == DEV_SECRET_KEY:
                            self.registry.clear_all_wipes()
                        resp = (
                            f"HTTP/1.1 302 Found\r\n"
                            f"Location: /dev?key={DEV_SECRET_KEY}\r\n"
                            f"Connection: close\r\n\r\n"
                        ).encode("utf-8")
                    elif path == "/download":
                        resp = (
                            f"HTTP/1.1 302 Found\r\n"
                            f"Location: /download/zip\r\n"
                            f"Connection: close\r\n\r\n"
                        ).encode("utf-8")
                    elif path == "/download/zip":
                        vinfo = load_version_info()
                        zip_fname = vinfo.get("zip_filename", "game.zip")
                        zip_file = find_release_file(zip_fname)
                        if zip_file and os.path.exists(zip_file):
                            with open(zip_file, "rb") as f:
                                data = f.read()
                            ver_tag = vinfo.get("version", "latest")
                            resp = (
                                f"HTTP/1.1 200 OK\r\n"
                                f"Content-Type: application/zip\r\n"
                                f"Content-Disposition: attachment; filename=\"game.zip\"\r\n"
                                f"X-Content-Type-Options: nosniff\r\n"
                                f"Content-Length: {len(data)}\r\n"
                                f"Connection: close\r\n\r\n"
                            ).encode("utf-8") + data
                        else:
                            err = b"ZIP file not found on server."
                            resp = f"HTTP/1.1 404 Not Found\r\nContent-Length: {len(err)}\r\n\r\n".encode("utf-8") + err
                    elif path == "/download/apk":
                        vinfo = load_version_info()
                        apk_fname = vinfo.get("apk_filename", "game.apk")
                        apk_file = find_release_file(apk_fname)
                        if apk_file and os.path.exists(apk_file):
                            with open(apk_file, "rb") as f:
                                data = f.read()
                            resp = (
                                f"HTTP/1.1 200 OK\r\n"
                                f"Content-Type: application/vnd.android.package-archive\r\n"
                                f"Content-Disposition: attachment; filename=\"{apk_fname}\"\r\n"
                                f"Content-Length: {len(data)}\r\n"
                                f"Connection: close\r\n\r\n"
                            ).encode("utf-8") + data
                        else:
                            err = b"APK file not found on server."
                            resp = f"HTTP/1.1 404 Not Found\r\nContent-Length: {len(err)}\r\n\r\n".encode("utf-8") + err
                    elif path == "/download/exe":
                        vinfo = load_version_info()
                        exe_fname = vinfo.get("exe_filename", "game.exe")
                        exe_file = find_release_file(exe_fname)
                        if exe_file and os.path.exists(exe_file):
                            with open(exe_file, "rb") as f:
                                data = f.read()
                            resp = (
                                f"HTTP/1.1 200 OK\r\n"
                                f"Content-Type: application/octet-stream\r\n"
                                f"Content-Disposition: attachment; filename=\"{exe_fname}\"\r\n"
                                f"X-Content-Type-Options: nosniff\r\n"
                                f"Content-Length: {len(data)}\r\n"
                                f"Connection: close\r\n\r\n"
                            ).encode("utf-8") + data
                        else:
                            err = b"EXE file not found on server."
                            resp = f"HTTP/1.1 404 Not Found\r\nContent-Length: {len(err)}\r\n\r\n".encode("utf-8") + err
                    elif path == "/api/version":
                        vinfo = load_version_info()
                        j_data = json.dumps(vinfo, ensure_ascii=False).encode("utf-8")
                        resp = (
                            f"HTTP/1.1 200 OK\r\n"
                            f"Content-Type: application/json; charset=utf-8\r\n"
                            f"Access-Control-Allow-Origin: *\r\n"
                            f"Content-Length: {len(j_data)}\r\n"
                            f"Connection: close\r\n\r\n"
                        ).encode("utf-8") + j_data
                    elif path == "/dev":
                        key = qs.get("key", [""])[0]
                        is_auth = (key == DEV_SECRET_KEY)
                        html_bytes = self.build_dev_html(is_auth).encode("utf-8")
                        resp = (
                            f"HTTP/1.1 200 OK\r\n"
                            f"Content-Type: text/html; charset=utf-8\r\n"
                            f"Content-Length: {len(html_bytes)}\r\n"
                            f"Connection: close\r\n\r\n"
                        ).encode("utf-8") + html_bytes
                    else:
                        # 預設首頁與 /download 導向專屬下載網頁
                        html_bytes = self.build_download_html().encode("utf-8")
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

                                # 1b. 版本檢查協議: CHECK_VERSION|<client_version>
                if line.startswith("CHECK_VERSION|"):
                    client_ver = line.split("|", 1)[1].strip() if len(line.split("|")) > 1 else ""
                    vinfo = load_version_info()
                    srv_ver = vinfo.get("version", "v0.67.68")
                    has_update = 1 if is_version_newer(srv_ver, client_ver) else 0
                    c_notes = "; ".join(vinfo.get("changelog", []))
                    await self.send_line(writer, f"VERSION_INFO|{srv_ver}|{has_update}|/download/exe|{c_notes}")
                    continue

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

                # 1b. 開發者協議: DEV_DELETE_PLAYER|<secret_key>|<target_name>
                if line.startswith("DEV_DELETE_PLAYER|"):
                    parts = line.split("|")
                    if len(parts) >= 3 and parts[1].strip() == DEV_SECRET_KEY:
                        target = parts[2].strip()
                        await self.wipe_player_and_kick(target)
                        await self.send_line(writer, f"DEV_DELETE_OK|{target}")
                    else:
                        await self.send_line(writer, "DEV_ERR|ACCESS_DENIED")
                    continue

                # 1c. 客戶端清除完成回報: WIPE_ACK|<player_name>
                if line.startswith("WIPE_ACK|"):
                    parts = line.split("|", 1)
                    if len(parts) >= 2:
                        self.registry.clear_wiped_ack(parts[1].strip())
                    continue

                # 2. 玩家同步狀態封包: PLAYER_SYNC|<name>|<platform>|<world>|<hp>|<max_hp>|<atk>|<def>
                if line.startswith("PLAYER_SYNC|"):
                    parts = line.split("|")
                    if len(parts) >= 8:
                        p_name = parts[1].strip()
                        current_player_name = p_name
                        self.active_writers[p_name] = writer

                        # 若該玩家已被管理員註銷，單次下發強制清除進度指令並立即銷毀標記（同名不再重複清除）！
                        if self.registry.consume_wipe(p_name):
                            print(f"[!] Consumed pending wipe for '{p_name}' - dispatching FORCE_WIPE_ACCOUNT", flush=True)
                            await self.send_line(writer, "FORCE_WIPE_ACCOUNT")
                            if current_player_name in self.active_writers and self.active_writers[current_player_name] == writer:
                                self.active_writers.pop(current_player_name, None)
                            await self.close_writer(writer)
                            break

                        p_plat = parts[2].strip()
                        try:
                            p_world = int(parts[3])
                            p_hp = int(float(parts[4]))
                            p_max_hp = int(float(parts[5]))
                            p_atk = int(float(parts[6]))
                            p_def = int(float(parts[7]))
                        except Exception:
                            p_world, p_hp, p_max_hp, p_atk, p_def = 1, 100, 100, 10, 0
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
                        await self.send_line(writer, "PLAYER_SYNC_OK")
                    continue

                # 3. 房主註冊房間: RELAY_HOST|<host_name>|<is_public:0/1>
                if line.startswith("RELAY_HOST|") and role == "NONE":
                    parts = line.split("|", 3)
                    host_name = parts[1].strip() if len(parts) >= 2 and parts[1].strip() else "生還者"
                    is_public = (parts[2].strip() != "0") if len(parts) >= 3 else True

                    if self.registry.consume_wipe(host_name):
                        print(f"[!] Consumed pending wipe for host '{host_name}' - dispatching FORCE_WIPE_ACCOUNT", flush=True)
                        await self.send_line(writer, "FORCE_WIPE_ACCOUNT")
                        if current_player_name in self.active_writers and self.active_writers[current_player_name] == writer:
                            self.active_writers.pop(current_player_name, None)
                        await self.close_writer(writer)
                        break

                    current_player_name = host_name
                    self.active_writers[host_name] = writer
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
                        self.active_writers[current_player_name] = writer
                        if self.registry.consume_wipe(current_player_name):
                            print(f"[!] Consumed pending wipe for client '{current_player_name}' - dispatching FORCE_WIPE_ACCOUNT", flush=True)
                            await self.send_line(writer, "FORCE_WIPE_ACCOUNT")
                            if current_player_name in self.active_writers and self.active_writers[current_player_name] == writer:
                                self.active_writers.pop(current_player_name, None)
                            await self.close_writer(writer)
                            break
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
            if current_player_name in self.active_writers and self.active_writers[current_player_name] == writer:
                self.active_writers.pop(current_player_name, None)
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



























