---
name: generate-dist
description: 构建生产 exe 发版包：scripts/build_freeze.py Nuitka 冻结七步流水 → dist/MaterialSorting.dist/（onedir 本体）+ Setup 中文安装包 + 绿色 zip。含前置停服/前端 build/spyrrow 钉板/key sidecar 预检、后台长跑监控、构建后验收。支持 --dry-run / --installer-only / --launch 变体。
allowed-tools: Bash
---

# Generate Dist Skill（生产 exe 冻结打包）

## 上下文
- 项目根：`d:/code/MaterialSorting`；必须用仓库 venv Python：`d:/code/MaterialSorting/.venv/Scripts/python.exe`（裸 `python` 撞 Store 别名勿用；nuitka/spyrrow/materialsorting 均装在 venv）。
- 权威脚本 [scripts/build_freeze.py](../../scripts/build_freeze.py)：一条命令跑完七步流水；权威手册 [.docs/technical/本地部署构建与发版手册.md](../../.docs/technical/本地部署构建与发版手册.md)。
- 产物三件套（`dist/` 已 gitignore）：
  | 产物 | 说明 |
  |------|------|
  | `dist/MaterialSorting.dist/MaterialSorting.exe` | Nuitka standalone **onedir** 本体（~230 MiB，源码真编译机器码；不用 onefile） |
  | `dist/MaterialSorting-Setup-<版本>.exe` | Inno 中文安装包（~59 MiB，需 ISCC 在场；缺席打印指引跳过不失败） |
  | `dist/MaterialSorting-portable-<版本>.zip` | 绿色 zip（~90 MiB，恒产） |
- `<版本>` = `pyproject 版本 + git describe 短哈希[ dirty]`（如 `0.1.0-g590375b-dirty`），与 exe 属性页同源。

## 解析意图（从用户消息 / args）
- 默认：**全量构建 + 安装包**（`--installer`）。
- 变体（用户明说才用）：`dry-run`（只打印命令不编译）、`installer-only` / `补打包`（对既有 dist 补 6+7 步不重编译）、`launch` / `冒烟`（直接拉起既有 dist）。
- 正式发版（用户说「发版」）：构建前先打 tag `git tag v<x.y.z> && git push origin v<x.y.z>`（版本串锚）；日常验证构建可跳过。

## 执行步骤

### 0. 前置检查（构建红线，缺一不可）
1. **停常驻 CPU 负载**（叠加 = 双倍风暴，2026-09-27 整机假死事故）：
   ```bash
   for port in 8010 5173 8110; do
     for pid in $(netstat -ano | grep -E ":${port}[[:space:]]" | grep -i LISTENING | awk '{print $NF}' | sort -u); do
       MSYS_NO_PATHCONV=1 taskkill /PID $pid /F /T 2>/dev/null && echo "killed :${port} pid=$pid"
     done
   done
   ```
   （:8010 ms-web / :5173 Vite / :8110 keyserver；另有长跑 solver 子进程一并确认停。）
2. **前端 build**（发版前必跑，勿信既有 static/）：
   ```bash
   cd d:/code/MaterialSorting/materialSorting-web && npm run build
   ```
   失败（tsc 报错）→ 报错给用户，**不启动构建**。
3. **key 接线 sidecar 维护位检查**（红线④闸一，2026-09-29「交付包缺 sidecar → 客户机授权服务器未配置」事故防复发；缺 = 客户机装完必报错）：
   ```bash
   ls d:/code/MaterialSorting/materialSorting-server/out/license/   # 须含两文件且非空
   ```
   - `key_server_url.txt` = keyserver 公网基址一行（如 `http://<frps>:8083`）；`key_client_token.txt` = 与 keyserver 侧 `MS_KEY_CLIENT_TOKEN` 同值一行。
   - 该目录是**单一维护位**（dev 部署的 keygate 与打包共用）；构建期自动同步进包，**勿再手工往 dist 铺文件**（会被纠正为维护位现值）。
   - 缺失 → 指引用户补文件，**不启动构建**；确属内部测试构建才 `--skip-key-sidecar`。
4. （可选快速验证）`--dry-run` 先过一遍前置自检（nuitka/ordered-set/spyrrow 钉板/key sidecar 预检/孤儿进程扫描），失败口径与手册 §2 一致：
   ```bash
   cd d:/code/MaterialSorting && .venv/Scripts/python.exe scripts/build_freeze.py --dry-run
   ```

### 1. 后台启动构建（**必须后台**）
```bash
cd d:/code/MaterialSorting && .venv/Scripts/python.exe scripts/build_freeze.py --installer
```
- **`run_in_background: true`** —— 全量预算 30~90 分钟，前台跑 600s 会被静默杀。
- 脚本自带资源防护：jobs 上限 8（缺省 `min(8, max(2, 核数//4))` + 每 job ≥3GB 内存钳制）、BELOW_NORMAL 优先级、孤儿进程 fail-fast（命中时与用户确认后可 `--force` 放行）。
- 启动横幅会打印版本串/jobs 推导/预估时长，回显给用户。

### 2. 监控与完成判定
- 后台任务退出时读尾部输出，判定口径：
  - `[DONE] 冻结产物就绪：...MaterialSorting.exe` + `[DONE] 发版产物` 三件套 = 成功；
  - `[FAIL] 步骤「<名>」：...` = 失败，把步骤名与原因原样报给用户。
- 七步流水（任一步失败 exit 1）：① 前端 static 检查 + 样例母版预检 + key sidecar 预检（维护位两文件非空）② 环境自检（nuitka 4.3rc3 / ordered-set）③ spyrrow 私有 wheel 钉板（须 `0.9.0+msN` N≥1 且 warm 探测 True）④ 孤儿编译进程扫描 ⑤ Nuitka 编译（MinGW64）⑥ dist 自检（key sidecar 维护位→exe 旁同步 + 硬校验 + 源码泄漏 grep 零命中 + `exe --check`）⑦ 安装包 + 绿色 zip。
- 中途用户问进度：读后台任务输出尾部回显当前步骤，不要重复启动构建。

### 3. 构建后验收
```bash
# 冒烟拉起（Ctrl-C / kill 退出；浏览器自动开属正常）
cd d:/code/MaterialSorting && .venv/Scripts/python.exe scripts/build_freeze.py --launch
# 深度验收（可选，六相位；含 key sidecar 回归锁 P0f~P0h，47 项基线；
# --rerun-family 的 family 复跑段暂红 —— 豁免收紧后三冒烟直传不豁免待改样例入口）
node scripts/smoke_freeze.mjs
```
- 无副作用检查也可用：`dist/MaterialSorting.dist/MaterialSorting.exe --check`（回显 frozen/warm/version/key 接线，不起服务不开浏览器）。
- 汇报产物路径与版本串；正式发版提醒归档三件套（网盘/U盘）+ 记录 tag ↔ 产物哈希（手册 §2 ③）。

## 常见失败处置
| 现象 | 处置 |
|------|------|
| 步骤③ spyrrow 钉板不一致 | `python scripts/spyrrow_wheel.py status` → `use-local <wheel>` 校正后重跑 |
| 步骤④ 孤儿进程命中 | `tasklist` 确认后杀掉重跑；确属残留误报才 `--force` |
| 编译中断后重试 | 直接重跑即可（clcache 在 `%LOCALAPPDATA%/Nuitka` 跨重试生效） |
| 链接期 `CVTRES CVT1107 .obj 已损坏` | 硬重启留零填充 clcache → 删 `%LOCALAPPDATA%/Nuitka/Nuitka/Cache/clcache` 全量重编 |
| nuitka/ordered-set 缺失 | `.venv/Scripts/python.exe -m pip install nuitka==4.3rc3 ordered-set`（4.2.2 优化器对本闭包偶发崩，勿降级） |
| ISCC 未找到 | 不算失败（zip 照常产）；指引 `winget install --id JRSoftware.InnoSetup --scope user` 后 `--installer-only` 补打包 |
| 步骤①/⑥ key sidecar 缺失 | 维护位 `materialSorting-server/out/license/` 补 `key_server_url.txt`（keyserver 公网基址一行）+ `key_client_token.txt`（client token 一行）后重跑；内部测试构建可 `--skip-key-sidecar`（交付包禁用） |
| 前端 static 缺失 | 本 skill 步骤 0.2 已预防；跳过检查产出的属无效包 |

## 注意事项
- **绝不裸跑全核**：`--jobs` 勿超 8（override 高于 8 脚本会打警告，2026-09-27 全核并发假死事故）。
- dist 幂等：先清后建无增量，重跑 = 全量重编（正常）。
- 用户数据物理分离：安装/运行期用户数据在 `%LOCALAPPDATA%\MaterialSorting\out`，与构建无关，勿动。
- key 接线 sidecar 单一维护位 = `materialSorting-server/out/license/`（dev 部署与打包共用），构建/补打包自动同步进包 —— 勿手工往 dist 铺 sidecar（会被纠正为维护位现值）；全量重编会清空 dist 重建，sidecar 由流水自动补回不依赖残留。
- `--installer-only` 版本串取**当前** git 态 —— dist 若构建于其他提交，正式发版仍以全量 `--installer` 为准。
