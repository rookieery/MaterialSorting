# PRD: 机器对接端点浏览器直连支持(CORS+PNA 中间件 + ping 探测端点 + Origin 白名单 sidecar 交付)

## 概述 (Overview)

YL 系统将部署在服务器,MS(VB超排)exe 部署在用户本地,`/api/machine/*` 六端点现有「同机 loopback 服务端调用」假设断裂。本 PRD 为 MS 侧落地「YL 前端浏览器跨源直连本地 MS」的支撑能力:只作用于机器族的 CORS + Private Network Access 中间件、轻量 ping 探测端点(端口发现)、随安装包交付的 Origin 白名单 sidecar。配套 YL 侧改动另立 YL 仓 PRD(`D:\code\YLPatternMaking\tasks\`),服务器 MS 部署(回退通道)为纯运维动作非本 PRD 范围。

## 目标 (Goals)

- YL 前端(HTTPS 页面)可跨源直连本地 MS 的 `/api/machine/*` 全部端点:CORS 预检全绿 + PNA(`Access-Control-Allow-Private-Network: true`)通过
- **零回归**:Origin 白名单未配置时,全 web 层行为与现状逐字节一致(工作台同源面全功能不受影响)
- 终端用户零配置:Origin 白名单(YL 生产域名)随安装包 sidecar 交付,复用 key sidecar 流水线双闸先例

## 用户故事 (User Stories)

### US-001: machine_cors 配置模块(Origin 白名单三档链)
- **Description**: As a YL 对接开发者, I want 一个独立的 Origin 白名单配置模块(env → exe 旁 sidecar → license/ 回落三档链) so that 浏览器直连的跨源准入有单一配置真相源且 exe 交付零手工配置。
- **Acceptance Criteria**:
  1. 新模块 `web/machine_cors.py`,镜像 `keygate.py` 分层:模块级仅标准库 + `..paths`,`resolve_machine_allowed_origins() -> set[str] | None`
  2. 三档链:env `MS_MACHINE_ALLOWED_ORIGINS`(逗号/分号分隔)→ frozen exe 旁 `machine_allowed_origins.txt`(多行,strip 空行)→ `out/license/machine_allowed_origins.txt` 回落;**请求时读取非 import 期绑定**;三处皆无 → `None`
  3. 复用 keygate `_sidecar_candidates`/`_read_sidecar` 模式(keygate.py:112-141),适配多行列表化;`_license_dir()` 调用时取 `paths.LICENSE_DIR`(monkeypatch 生效防御)
  4. 测试 `tests/test_web_machine_cors.py` 覆盖三档优先序/多值解析/空文件回落/皆无返回 None,含 frozen 双位置对拍写法(keygate 冒烟 keygate.py:498-523 先例)
  5. AST 守卫:machine_cors.py 顶层禁 import server、全模块禁 import cli(照 test_web_keygate.py 模式)
  6. `python -m materialsorting.web.machine_cors` 冒烟:无参数打印当前白名单解析结果(三档来源标注),exit 0
- **Priority**: 1

### US-002: CORS+PNA 中间件与 server 注册
- **Description**: As a YL 前端, I want MS 对 `/api/machine/*` 正确响应 CORS 预检并附带 PNA 头 so that HTTPS 页面可以跨源调用本地 MS 并读到错误响应体。
- **Acceptance Criteria**:
  1. `machine_cors.py` 导出 `register_machine_cors(app)`,server.py 文件尾 `register_machine_routes(app)`(:643-645)之后调用;镜像补一条注册顺序 AST 断言(不破坏既有 test_server_registers_machine_after_strategy)
  2. 中间件只作用于 `request.url.path.startswith('/api/machine/')`,其余路径原样放行(`GET /`、`/static`、工作台 `/api/*` 零扰动,挂进既有 test_server_app_healthy_with_machine_router 断言)
  3. OPTIONS 预检自答(Starlette 中间件先于路由,不自答则 405):白名单内 Origin → `Access-Control-Allow-Origin: <echo 具体值,禁止 *>`、`-Allow-Methods: GET, POST, DELETE`、`-Allow-Headers: x-machine-token, content-type`、`Access-Control-Allow-Private-Network: true`、`-Max-Age: 86400`;白名单外 → 不带任何 CORS 头
  4. 白名单已配置时,所有 `/api/machine/*` 实际响应(含 401/400/404)带 ACAO 回显头(浏览器可读错误体)
  5. 白名单外 Origin 的实际请求 → 403(服务端主动校验,防恶意网页 CSRF 型 simple request 触发任务)
  6. 未配置白名单(US-001 返回 None)→ 不发 CORS 头、不校验 Origin、OPTIONS 落现状 405,**逐字节现状零回归**
  7. 测试组(照 test_web_machine.py:1336-1377 token 测试骨架):预检全绿/PNA 头精确值/401 带 ACAO/白名单外 403/未配置零变化
  8. `python -m materialsorting.web.server` 启动冒烟:注册中间件后 `GET /` 200、`/api/machine/solve` 405(无OPTIONS头)现状不变
- **Priority**: 2(依赖 US-001)

### US-003: GET /api/machine/ping 轻量探测端点
- **Description**: As a YL 前端, I want 一个无 task_id 无 token 的 ping 端点 so that 可以探测本地 MS 是否启动并发现实际端口(8010-8019)。
- **Acceptance Criteria**:
  1. machine.py 第七端点 `GET /api/machine/ping`:无 task_id 闸、无 token 闸(响应零敏感信息),响应恰 `{ok: true, service: 'machine'}`
  2. 端点落在既有 `router`(APIRouter 同风格),CORS 中间件覆盖(白名单外网页读不到)
  3. 测试:无 Origin 直打 200;带白名单内 Origin 响应带 ACAO
  4. `python -m materialsorting.web.server` 冒烟:curl ping 返回 200 三键
- **Priority**: 1(与 US-001 无依赖可并行)

### US-004: sidecar 交付链(generate-dist 同步 + 预检硬校验)
- **Description**: As a 交付运维, I want Origin 白名单 sidecar 随安装包流水线自动同步 so that exe 交付自带 YL 生产域名、终端用户零配置,且缺文件有闸门报警。
- **Acceptance Criteria**:
  1. 维护位 `out/license/machine_allowed_origins.txt`(单源,预填 YL 生产域名,可多行多 Origin)
  2. `scripts/build_freeze.py` 的 step_dist_check 自动同步 sidecar 到 exe 旁(镜像 key sidecar 双闸先例:覆盖 `--installer-only` 变体 + 预检硬校验,交付包缺 sidecar 即构建失败)
  3. launcher `--check` 回显白名单三档来源与条数(镜像 keygate `describe_*` 先例 launcher.py:243-261;仅供诊断,业务路径不消费)
  4. 测试:纯桩覆盖同步逻辑(照 tests/test_spyrrow_wheel.py 桩模式或 build_freeze 既有测试挂点)
  5. `python -m materialsorting.launcher --check` 冒烟输出含 machine_allowed_origins 行
- **Priority**: 3(依赖 US-001)

### US-005: 契约文档更新 + 真机 PNA 对拍验收
- **Description**: As a YL 对接开发者, I want 契约文档补浏览器直连部署形态并完成 HTTPS 真机对拍 so that YL 侧可仅凭文档对接且浏览器策略时效风险被实证排除。
- **Acceptance Criteria**:
  1. `.docs/technical/agent-api-reference.md` §0 补「浏览器直连部署形态」小节(直连地址口径 `127.0.0.1:8010-8019`、白名单 sidecar、token 可选语义、PNA 前提);§2 端点表加 ping 行 + curl;YL 透传指引补浏览器直连注意事项(127.0.0.1 字面量/预检头)
  2. `web/AGENTS.md` machine.py 行(49 行)补 machine_cors 中间件 + ping 条目
  3. 真机对拍:构造 HTTPS 静态测试页(内网自签)fetch `http://127.0.0.1:8010/api/machine/ping`,Edge + Chrome 预检全绿拿到 JSON;未配置白名单的对照 MS 实例同请求被浏览器拦(零回归反证);对拍记录归档 `.docs/business/`
  4. README 运行方式节附一句浏览器直连支持说明
- **Priority**: 4(收尾,依赖 US-001~004)

## 功能需求 (Functional Requirements)

- FR-1: Origin 白名单三档链解析(env `MS_MACHINE_ALLOWED_ORIGINS` 逗号/分号分隔 → frozen exe 旁 `machine_allowed_origins.txt` 多行 → `out/license/` 回落),请求时读取
- FR-2: 未配置白名单 = 不发 CORS 头、不校验 Origin、OPTIONS 落 405,与现状逐字节一致
- FR-3: 白名单内 OPTIONS 预检自答:ACAO echo 具体值 / Methods GET,POST,DELETE / Headers x-machine-token,content-type / `Access-Control-Allow-Private-Network: true` / Max-Age 86400
- FR-4: 白名单已配置时所有 `/api/machine/*` 实际响应(含错误态)带 ACAO 回显头
- FR-5: 白名单外 Origin 的 `/api/machine/*` 实际请求 403(服务端主动校验)
- FR-6: 中间件只作用于 `/api/machine/` 前缀,工作台同源面零扰动
- FR-7: `GET /api/machine/ping` 端点:无 task_id、无 token,响应 `{ok, service}`
- FR-8: sidecar 随 generate-dist 流水线同步 + 预检硬校验 + launcher `--check` 回显

## 非目标 (Non-Goals)

- 不改六端点业务逻辑与 `X-Machine-Token` 机制本身(未设放行 = loopback 假设口径不变;设了 token 则预检已放行该头,两模式不互斥)
- 不改服务绑定地址(恒 `127.0.0.1`,launcher 端口探测 8010-8019 不变)
- 不做 WebSocket 跨源(工作台 `/ws/solve` 同源,不属机器族)
- 不做 YL 仓任何改动(YL 侧另立 YL 仓 PRD)
- 不做服务器 MS 部署本身(回退通道 = 纯运维:pip 装 ms-web + 设 `MS_MACHINE_TOKEN`,代码零改动)
- 不做 IP 白名单(明确否决:回环绑定 + Origin 白名单已覆盖)

## 设计考虑 (Design Considerations)

- 中间件必须**自答 OPTIONS**:Starlette 中间件先于路由,`/api/machine/*` 无 OPTIONS 路由匹配会落 405,预检必挂
- `X-Machine-Token` 是自定义头,使带 token 的跨源请求**必触发预检**;multipart POST solve 即使 simple request 在 PNA 下同样要预检——预检路径是全链硬前提
- 浏览器直连模式建议 MS 不设 `MS_MACHINE_TOKEN`(token 随 JS 下发无增量防线,徒增 YL 前端负担);防线 = 回环绑定 + Origin 白名单 + 主动 403

## 技术考虑 (Technical Considerations)

- **PNA/LNA 时效**:2026 年 Chromium 对 Private Network Access → Local Network Access(用户授权提示)推进状态需真机验证(US-005);dev 态 localhost 页面 local→local 不触发 PNA,与生产行为不同
- **必须 `127.0.0.1` 字面量**:MS 只绑 IPv4 loopback,`localhost` 可能解析 `::1`;本机局域网 IP 会被 HTTPS mixed content 硬拦
- ACAO 必须 echo 具体 Origin,禁止 `*`(PNA 预检要求具体值)
- AST 守卫三处:machine_cors.py 顶层禁 import server、全模块禁 import cli、server.py 注册顺序镜像断言
- 分层红线照 keygate:模块级仅标准库 + `..paths`

## 成功指标 (Success Metrics)

- [ ] pytest 全量绿(含新增 tests/test_web_machine_cors.py 全组)
- [ ] HTTPS 页面直连 ping + 六端点全链预检通过(Edge/Chrome 真机)
- [ ] 未配置白名单时全 web 层现状逐字节(OPTIONS 405、无 CORS 头)
- [ ] 工作台同源面(`GET /`、上传/求解/导出/编辑)零扰动
- [ ] generate-dist 产物 exe 旁含 `machine_allowed_origins.txt` 且 `--check` 可见

## 待确认问题 (Open Questions)

- YL 生产域名的具体值(协议+域名+端口)——交付前由运维填入维护位 sidecar(方案已确认「固定域名」形态,具体值待 YL 部署定时提供)
- YL 域名若含多个环境(测试/生产),sidecar 多行即可,无代码改动
