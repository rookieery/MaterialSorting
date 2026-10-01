# 浏览器直连真机对拍报告 — prd-machine-browser-direct US-005（2026-10-01）

## 0. 结论速览

| 验收项 | 结果 |
|---|---|
| Chrome 真机：HTTPS 页面 fetch `http://127.0.0.1:8011/api/machine/ping` 预检全绿拿到 JSON | ✅（loopback 页面源 + 内网页面源双形态 ALL GREEN） |
| Edge 真机：同上 | ✅（双形态 ALL GREEN） |
| 零回归反证：未配置白名单 MS 同请求被浏览器拦 | ✅（双浏览器 4 组运行全数 `TypeError: Failed to fetch`；服务端日志实证预检 405 后**零后续实调**） |
| 白名单外 Origin 纵深防御 | ✅（curl 实拍 403 中文错误体，无任何 CORS 头） |
| PNA 请求头真机行为实证 | ℹ️ Chrome 153 / Edge 154 **已不携带** `Access-Control-Request-Private-Network`（16 条捕获预检 0 在场，含 private→local 形态）；MS 应答头 `Access-Control-Allow-Private-Network: true` 无害兼容（旧引擎在请求时该应答头是硬前提） |

**一句话**：双引擎真机直连全绿、零回归反证成立；PNA 预检头在 2026-10 当前引擎（LNA 时代）已不携带，中间件五头应答对「在请求 / 不在请求」两形态均兼容，浏览器策略时效风险被实证框定（详见 §4）。

## 1. 对拍环境（真机）

| 项 | 值 |
|---|---|
| 机器 | 开发机 Windows（ASUS），同机浏览器与 MS |
| Chrome | 153.0.8010.54（`C:\Program Files\Google\Chrome\Application\chrome.exe`，headless，UA `HeadlessChrome/153.0.0.0`） |
| Edge | 154.0.4258.37（`C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`，headless，UA `…Chrome/154.0.0.0…Edg/154.0.`） |
| HTTPS 静态测试页 | `out/browser_direct_test/pna_test.html`（自包含，无外部依赖）；自签证书 SAN = `IP:127.0.0.1, IP:192.168.2.10, DNS:localhost`（`openssl req -x509`，7 天） |
| 页面源双形态 | `https://127.0.0.1:8443`（loopback 地址空间，local）与 `https://192.168.2.10:8443`（内网 private 地址空间）—— 同一 ThreadingHTTPServer+TLS 0.0.0.0:8443 |
| MS 实例 A（白名单） | `MS_WEB_PORT=8011 MS_MACHINE_ALLOWED_ORIGINS="https://127.0.0.1:8443,https://192.168.2.10:8443"` + 隔离 `MS_OUT_DIR`（源码跑 `python -m materialsorting.web.server`，当前分支 ralph/machine-browser-direct 含 US-001~004 全量） |
| MS 实例 B（未配置对照） | `MS_WEB_PORT=8012` + 隔离 `MS_OUT_DIR`（无 env 无 sidecar → `resolve_machine_allowed_origins()` = None = 零回归现状档）；8011/8012 均在契约口径 8010-8019 扫描族内（8010 被本机常驻冻结版占用，备案不杀） |
| 头捕获桩 | `capture_server.py` 127.0.0.1:8021：镜像 machine_cors 预检五头应答，落盘浏览器**实际发来的全部预检/实调请求头**（`capture_log.jsonl`） |
| 浏览器旗标 | `--headless --ignore-certificate-errors --no-proxy-server --user-data-dir=<隔离目录> --virtual-time-budget=30000`（真实引擎/网络栈/CORS+PNA 策略，未动任何实验旗标）；每组合跑 `--dump-dom`（文本证据）与 `--screenshot`（截图证据）各一遍 |

测试页四探针（每组合各跑一遍，序贯）：

| 探针 | 请求 | 期望 |
|---|---|---|
| A 预检 fetch | `GET http://127.0.0.1:8011/api/machine/ping` + 头 `x-machine-token: pna-probe`（自定义头 → 强制 OPTIONS 预检） | 200 + `{"ok":true,"service":"machine"}` |
| B simple GET | 同 URL 无自定义头（无预检，靠响应 ACAO 回显可读） | 200 + body 可读 |
| C 零回归反证 | 同 A 打 8012（未配置 MS） | fetch 拒绝（`TypeError: Failed to fetch`），服务端零改动照常 200 |
| D 头捕获 | 同 A 打 8021 捕获桩 | 回显浏览器预检实际携带头（PNA 头在场性实证） |

## 2. 结果矩阵（4 组合 × 探针 A/B/C）

| 浏览器 | 页面源（地址空间） | A 预检 fetch | B simple GET | C 零回归反证 | 总判定 |
|---|---|---|---|---|---|
| Chrome 153 | `https://192.168.2.10:8443`（private→local，PNA 语义形态） | ✅ HTTP 200 `{"ok":true,"service":"machine"}` | ✅ 同 | ✅ 被浏览器拦 | **ALL GREEN** |
| Chrome 153 | `https://127.0.0.1:8443`（local→local） | ✅ 同 | ✅ 同 | ✅ 同 | **ALL GREEN** |
| Edge 154 | `https://192.168.2.10:8443`（private→local） | ✅ 同 | ✅ 同 | ✅ 同 | **ALL GREEN** |
| Edge 154 | `https://127.0.0.1:8443`（local→local） | ✅ 同 | ✅ 同 | ✅ 同 | **ALL GREEN** |

DOM 文本证据（`--dump-dom` 逐字摘录，Chrome 内网页面源；其余三组同形）：

```
PASS A. 白名单 MS 预检 fetch：HTTP 200 body={"ok":true,"service":"machine"}
PASS B. 白名单 MS simple GET：HTTP 200 body={"ok":true,"service":"machine"}
PASS C. 未配置 MS 预检 fetch：被浏览器拦（TypeError: Failed to fetch） —— 零回归反证成立：服务端 200 照常但无 CORS 头，浏览器拒绝暴露响应
··· D. 预检请求头捕获：共 2 条请求（OPTIONS → GET）；Access-Control-Request-Private-Network: true 不在场（本 origin 地址空间未触发 PNA，仅普通 CORS 预检）
总判定：ALL GREEN —— 预检全绿拿到 JSON + 零回归反证成立
```

## 3. 服务端视角对拍（curl 预检 + 访问日志）

curl 直打（浏览器行为前的服务端形状逐字节核验）：

| 请求 | 实拍 | 期望 |
|---|---|---|
| OPTIONS 8011 + 白名单内 Origin + `ACR-Method: GET` + `ACR-Private-Network: true` | `200` + 恰五头（ACAO 回显 / Methods `GET, POST, DELETE` / Headers `x-machine-token, content-type` / **PNA `true`** / Max-Age `86400`）+ `Vary: Origin` | ✅ US-002 契约金标 |
| GET 8011 ping + 白名单内 Origin | `200 {"ok":true,"service":"machine"}` + ACAO 回显 + Vary | ✅ |
| GET 8011 ping + Origin `https://evil.example` | `403 {"error":"Origin https://evil.example 不在机器对接白名单内…"}`，**无任何 CORS 头** | ✅ 白名单外纵深防御 |
| OPTIONS 8012（未配置）+ Origin | `405 Method Not Allowed`（落路由现状档，无 CORS 头）→ 浏览器预检必败 | ✅ 零回归 |
| GET 8012 ping + Origin | `200` **不带 ACAO**（服务端照常，浏览器拒读） | ✅ 零回归 |

MS 访问日志（uvicorn，浏览器真机运行期间）：

- 实例 A（白名单 8011）：`OPTIONS /api/machine/ping 200` ×9（1 curl + 8 浏览器组合运行）+ `GET … 200` ×17 —— **预检先于实调，逐条配对在案**。
- 实例 B（未配置 8012）：浏览器 `OPTIONS … 405` ×8 后 **GET 0 条** —— 预检失败浏览器直接放弃实调，「浏览器拦」不是前端猜测而是可观测事实（未配置形态 = 旧版无 CORS 行为逐字节保持，老部署零回归）。

## 4. PNA 请求头真机实证（浏览器策略时效风险框定）

捕获桩 16 条浏览器请求（4 组合 × dump/screenshot 两遍 × OPTIONS+GET）全量检视：

- 预检 OPTIONS **全部**携带：`Origin`、`Access-Control-Request-Method: GET`、`Access-Control-Request-Headers: x-machine-token`（自定义头强制预检语义成立）。
- `Access-Control-Request-Private-Network` **0/16 在场** —— 含内网页面源（192.168.2.10，private 地址空间 → 127.0.0.1 local）形态。Chrome 153 / Edge 154（2026-10）对「HTTPS 页面 → http://127.0.0.1」**不再附加 PNA 预检头**（PNA 预检强制时代已被 Local Network Access 权限模型取代；loopback 目标且页面非公网源时不触发额外闸）。
- **对 MS 侧的含义**：machine_cors 预检应答无条件附 `Access-Control-Allow-Private-Network: true` —— 当前引擎「未请求而多应答」无害（实测全绿），PNA 预检强制的旧引擎（Chrome/Edge ~104–13x、部分 WebView2 内嵌形态）「请求而必应答」仍是硬前提。应答头不动 = 新旧两态兼容，**策略时效风险实证框定**：YL 侧无需按引擎版本分支。
- 残余风险注记（写进契约文档 §0）：若 YL 生产页面为**公网**源（public → local），LNA 权限模型下浏览器可能弹「访问本地网络设备」类用户授权提示 —— 该提示是浏览器产品行为非 MS 可控，授予后行为与本报告一致（内网源实测无提示直连全绿）。

## 5. 对拍工件清单（out/browser_direct_test/，gitignore 区，验收时点留存）

| 工件 | 说明 |
|---|---|
| `pna_test.html` | HTTPS 静态测试页（四探针，自包含） |
| `cert.pem` / `key.pem` | 内网自签证书（SAN 三值） |
| `https_server.py` / `capture_server.py` | harness 两服务器（页面 TLS / 预检头捕获桩） |
| `dump_chrome_lan.html` / `dump_edge_lan.html` / `dump_chrome_loop.html` / `dump_edge_loop.html` | 四组合 `--dump-dom` 文本证据（含 UA / page origin / 四探针结果 / 总判定） |
| `shot_chrome_lan.png` / `shot_edge_lan.png` / `shot_chrome_loop.png` / `shot_edge_loop.png` | 四组合截图（PASS 绿行 + ALL GREEN 总判定可见） |
| `capture_log.jsonl` | 16 条浏览器实际请求头全量（PNA 头在场性证据源） |
| `msA_8011.log` / `msB_8012.log` | 两 MS 实例访问日志（预检/实调配对 + 未配置零后续实调） |
| `outA/` / `outB/` | 两 MS 实例隔离 out 目录 |
| `err_*.txt` / `https_8443.log` / `capture_8021.log` | harness 运行杂项日志 |

验毕清理：四服务（8011/8012/8443/8021）PowerShell `Stop-Process` 按 PID 杀净、端口释放确认；headless 浏览器为 one-shot 自退（核验 0 残留进程引用本 harness 目录）；8010 常驻冻结版（PID 4676，非本会话所起）未触碰。

## 6. 契约收口联动（本报告落地的三处文档）

1. `agent-api-reference.md` §0「浏览器直连部署形态」小节（地址口径 / 127.0.0.1 字面量红线 / 白名单配置 / token 可选语义 / PNA 前提与本报告结论）+ §6.5 YL 透传指引浏览器直连注意事项。
2. `web/AGENTS.md` machine.py / machine_cors.py 行补 US-005 真机对拍与契约收口注记。
3. `README.md` 运行方式节浏览器直连支持一句说明。
