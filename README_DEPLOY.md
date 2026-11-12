# 全球多人大廳與中繼伺服器部署指南

本資料夾包含純 Python 3 撰寫的全球房間大廳與 TCP 中繼伺服器（`relay_server.py`），可讓世界各地的 PC 與 Android 手機玩家免開路由器 Port、免輸入 IP 跨國連線遊玩。

## 方式一：部署到 Railway（推薦，支援免費額度與一鍵 TCP Proxy）
1. 將 `relay_server` 資料夾上傳到 GitHub（或使用 Railway CLI）。
2. 到 [Railway](https://railway.app/) 建立 New Project → Deploy from GitHub repo。
3. 部署完成後，進入服務的 **Settings → Networking → Public Networking → TCP Proxy**，輸入內部埠號 `25569` 並啟用。
4. Railway 會給你一組公開位址，例如：`monorail.proxy.rlwy.net:12345`。
5. 打開遊戲內的「🌐 多人連線」選單，將「全球伺服器位址」填入該位址並儲存，全世界的玩家輸入同一組伺服器位址就能立刻開房、搜尋公開房與互加好友！

## 方式二：部署到 Fly.io（原生 Raw TCP，低延遲）
1. 安裝 `flyctl` 並登入：`fly auth login`
2. 在本資料夾執行：
   ```bash
   fly launch --no-deploy
   fly ips allocate-v4 --shared
   fly deploy
   ```
3. 取得 Fly 分配的域名（例如 `rust2d-global-relay.fly.dev:25569`），填入遊戲內的「全球伺服器位址」即可。

## 方式三：自行在有公網 IP 的主機 / VPS 執行
```bash
python3 relay_server.py
```
（預設監聽 `0.0.0.0:25569`，可用 `PORT=你的埠號` 環境變數更改；記得防火牆放行 TCP 25569。）
