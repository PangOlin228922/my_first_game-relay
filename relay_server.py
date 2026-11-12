#!/usr/bin/env python3
"""
Rust2D / 幫我試玩看看 全球多人大廳與封包中繼伺服器 (Global Lobby & TCP Relay Server)
純 Python 3 標準函式庫 (asyncio) 實作，無需安裝任何第三方套件。
預設監聽 PORT 環境變數或 25569，支援 Railway (TCP Proxy) / Fly.io / 任何 VPS。
"""

import asyncio
import os
import signal
import sys
import time
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple


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


class RelayServer:
    def __init__(self) -> None:
        self.rooms: Dict[int, Room] = {}
        self.next_room_id: int = 1

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

    async def handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        peer = writer.get_extra_info("peername")
        role: str = "NONE"  # "HOST" | "CLIENT"
        my_room: Optional[Room] = None
        my_client_id: int = 0

        try:
            while True:
                raw = await reader.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                if not line:
                    continue

                # 1. 房主註冊房間: RELAY_HOST|<host_name>|<is_public:0/1>
                if line.startswith("RELAY_HOST|") and role == "NONE":
                    parts = line.split("|", 3)
                    host_name = parts[1].strip() if len(parts) >= 2 and parts[1].strip() else "生還者"
                    is_public = (parts[2].strip() != "0") if len(parts) >= 3 else True

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

                # 2. 查詢全球房間列表: RELAY_LIST
                if line == "RELAY_LIST":
                    for rid, r in list(self.rooms.items()):
                        pub_flag = 1 if r.is_public else 0
                        await self.send_line(
                            writer,
                            f"RELAY_ROOM|{rid}|{r.host_name}|{pub_flag}|{r.player_count}",
                        )
                    await self.send_line(writer, "RELAY_LIST_END")
                    continue

                # 3. 玩家加入房間: RELAY_JOIN|<room_id>
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

                # 4. 房主轉發封包給指定玩家: RELAY_TO|<target_id>|<payload>
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

                # 5. 房主廣播封包給所有玩家 (排除 exclude_id): RELAY_BCAST|<exclude_id>|<payload>
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

                # 6. 玩家送給房主的遊戲封包: 直接轉包為 RELAY_FROM|<client_id>|<line>
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
                    f"[<] Client #{my_client_id} left Room #{my_room.room_id}",
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
    print(f"[*] Rust2D Global Relay Server listening on {addrs}", flush=True)

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
