# nanobot Desktop

把 [nanobot](https://github.com/HKUDS/nanobot) 的 gateway + WebUI 封装成一个**面向普通用户的本地 AI Agent 桌面应用**，提供类似 Codex 的桌面体验。本目录（`desktop/`）是一个独立的子项目，负责"打包成 Windows 安装包"这一层，不改动 nanobot 本体。

## 设计目标

产品面向**非技术用户**，因此核心约束是：

- **零控制台**：全程 `pythonw.exe` 运行，**绝不弹出任何黑色命令行窗口**。
- **网页引导**：首次使用时用网页表单配置（选服务商、填 API Key、选模型），**不再用终端向导**；同样用 Pake 封装成原生窗口。
- **原生窗口**：基于 [Pake](https://github.com/tw93/pake)（Rust/Tauri）的真实原生窗口，不是浏览器 `--app` 模式。
- **自包含**：Python 运行时一并打包，用户机器**无需预装 Python**。
- **无连接报错**：Pake 窗口永远先看到一个"加载动画"页，绝不会闪过浏览器丑陋的 `ERR_CONNECTION_REFUSED`。
- **免登录本地**：本地 WebUI 不需要密码（空 `token_issue_secret` → localhost 免密 bootstrap）。
- **默认中文**：WebUI 默认简体中文。

## 整体架构

```
┌──────────────────────────────────────────────────────────────────┐
│                         nanobot Desktop                          │
│                                                                  │
│   桌面快捷方式  ──►  pythonw.exe launcher.py   （零控制台入口）   │
│                              │                                   │
│                              ▼                                   │
│        ┌──────────────────────────────────────────────────┐      │
│        │  launcher.py  （pythonw 后台控制器，不可见）       │      │
│        │   1. 启动前端路由 :8766  （秒级就绪）              │      │
│        │   2. 若已配置 → 启动 gateway :8765                │      │
│        │   3. 打开 Pake 窗口 → http://127.0.0.1:8766       │      │
│        │   4. 等待窗口关闭 → 停止 gateway → 退出           │      │
│        └──────────────────────────────────────────────────┘      │
│             │                                  │                  │
│             ▼                                  ▼                  │
│   ┌──────────────────┐           ┌───────────────────────────┐   │
│   │  Pake / Tauri    │   HTTP    │  前端路由 :8766            │   │
│   │  原生窗口         │ ────────► │  （onboard_server.py）     │   │
│   │  (系统 WebView2) │           │   • 加载动画页（友好等待）  │   │
│   │  + 中文 locale   │           │   • 网页引导表单（首次）    │   │
│   │    注入脚本       │           │   • /api/status 状态接口   │   │
│   └──────────────────┘           │   • 智能跳转 → :8765       │   │
│                                  └─────────────┬─────────────┘   │
│                                                │ 就绪后 302       │
│                                                ▼                  │
│                                  ┌───────────────────────────┐   │
│                                  │  nanobot gateway          │   │
│                                  │   • WebSocket/WebUI :8765 │   │
│                                  │   • 健康检查     :18790   │   │
│                                  └───────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```

### 端口约定

| 端口 | 服务 | 说明 |
|------|------|------|
| **8766** | 前端路由（launcher 内置） | Pake 窗口的固定入口，**始终秒回**，永不连接被拒 |
| **8765** | gateway WebSocket / WebUI | nanobot 自带的聊天界面 |
| **18790** | gateway 健康检查 | `GET /health` → `{"status":"ok"}` |

> ⚠️ 浏览器/WebUI 界面是 **8765**（由 WebSocket channel 提供），不是 18790（那只是健康端口）。

## 工作流程

### 首次运行（无配置）

```
快捷方式 → launcher 启动
   ├─ 前端路由 :8766 就绪（<100ms）
   ├─ 检测到无配置 → 不启动 gateway（gateway 必须有 provider 才能起）
   ├─ 打开 Pake → :8766 → 加载动画 → 跳转 /setup（网页引导表单）
   │      用户填写：服务商(默认 DeepSeek) / API Key / 模型(默认 deepseek-v4-pro)
   │      [无密码字段]
   ├─ 提交 → 路由写入 config.json（空 token_issue_secret → 免登录）
   ├─ launcher 启动 gateway :8765 → 等待就绪
   └─ 加载动画检测到 gateway_up → 自动跳转 :8765 → 中文聊天界面（免登录）
```

### 后续运行（已配置）

```
快捷方式 → launcher 启动
   ├─ 前端路由 :8766 就绪
   ├─ 检测到已配置 → 立即启动 gateway :8765
   ├─ 打开 Pake → :8766 → 路由见 configured && gateway_up → 直接 302 到 :8765
   └─ 用户关窗 → launcher 停止 gateway → 全部退出（不留残余进程）
```

## 目录结构

```
desktop/
├── backend/
│   ├── __init__.py
│   ├── launcher.py            # 零控制台生命周期管理器（pythonw 运行）
│   └── onboard_server.py      # 前端路由 :8766 + 网页引导 + 加载动画
├── installer/
│   └── nanobot-desktop.nsi    # NSIS Windows 安装脚本
├── scripts/
│   ├── build_all.py           # 一键构建编排（WebUI→wheel→Python→Pake→NSIS）
│   └── build_pake_env.ps1     # Pake 构建（带 VS MSVC 环境，单独可跑）
├── pake/
│   └── nanobot-desktop.json   # Pake 配置参考
├── assets/
│   ├── nanobot.ico            # Windows 图标
│   ├── nanobot_icon.png       # Pake 图标源
│   ├── nanobot_logo.png
│   └── inject-locale.js       # 中文 locale 注入脚本（构建时嵌入 Pake）
├── output/                    # 构建产物（已 gitignore）
│   ├── nanobot-desktop-setup.exe
│   ├── nanobot.exe
│   └── python-bundle/
├── .gitignore
└── README.md                  # 本文档
```

## 核心组件

### 1. `launcher.py` — 零控制台控制器

通过 `pythonw.exe` 运行（无控制台窗口）。职责：

- 启动前端路由 :8766（**先于一切**，保证 Pake 永不连接被拒）。
- **仅在已配置时**才启动 gateway（gateway 启动需要 provider，见避坑）。
- 打开唯一的 Pake 窗口。
- `pake.wait()` 等待用户关窗，`finally` 里停止 gateway + 路由，干净退出。
- 所有输出写入 `~/.nanobot/desktop-launcher.log`（pythonw 无 stdout）。

### 2. `onboard_server.py` — 前端路由 + 网页引导

一个基于标准库 `http.server` 的极小服务器（绑定 8766，秒级就绪）：

| 路由 | 行为 |
|------|------|
| `GET /` | 已配置且 gateway 就绪 → `302` 到 :8765；否则返回**加载动画页** |
| `GET /setup` | 已配置 → `302` 到 `/`；否则返回**网页引导表单** |
| `GET /api/status` | `{configured, gateway_up}`，供加载页轮询 |
| `POST /api/setup` | 接收表单 → 用 nanobot 的 `Config` 模型写 config.json → 回调 launcher 启动 gateway |

加载动画页每 0.8s 轮询 `/api/status`：未配置跳 `/setup`，已就绪跳 :8765。这样**前端永远主动跳转，不依赖后端推送**。

### 3. Pake / Tauri 原生窗口

用 `pake-cli` 把 `http://127.0.0.1:8766` 封装成原生窗口：

- 指向 **8766**（前端路由），不是 8765 —— 这是避免"连接被拒"的关键。
- `--inject inject-locale.js`：构建时嵌入中文 locale 脚本，运行时在 WebView 初始化前把 `localStorage["nanobot.locale"]="zh-CN"` 写好（仅当用户未自选时），让 WebUI 默认中文。
- 体积约 8.6MB（Rust/Tauri），远小于 Electron。

### 4. 嵌入式 Python 运行时

用 **Python Embeddable 发行版**（不是 venv）：

- 完全自包含、可分发；`python.exe` / `pythonw.exe` 在根目录。
- **不用 venv 的原因**：venv 的 `python.exe` 是个重定向器，靠 `pyvenv.cfg` 指向本机 base Python，换机器就找不到标准库 → 不可分发。
- 安装步骤：下载 embeddable zip → 解压 → 改 `python312._pth`（启用 `import site` + `Lib\site-packages`）→ `get-pip.py` → `pip install nanobot wheel`。

### 5. NSIS 安装包

`nanobot-desktop.nsi` 打包：嵌入式 Python + 后端脚本 + Pake exe + 图标。关键点：

- **快捷方式直接指向 `pythonw.exe launcher.py`**（不是 bat）—— bat 会带控制台，违背零控制台目标。
- 注册到"添加/删除程序"、创建桌面 + 开始菜单快捷方式、卸载程序。
- 卸载时保留 `~/.nanobot` 用户数据（配置、对话历史）。

## 安全模型

WebUI 里的「默认权限 / 完全访问权限」只是其中一层。nanobot 的工具安全是**分层**的：

| 层级 | 机制 | 强度 | 平台 |
|------|------|------|------|
| **L0** | 完全访问（`restrict_to_workspace=False`） | 无限制 | 全平台 |
| **L1** | 默认权限（`restrict_to_workspace=True`） | 应用层路径 guard | 全平台 |
| **L2** | 危险命令内置黑名单 | 始终生效 | 全平台 |
| **L3** | 自定义 allow/deny 命令模式 | 可配 | 全平台 |
| **L4** | 环境变量过滤 + 超时 | 可配 | 全平台 |
| **L5** | **OS 级沙箱**（最强） | 系统强制 | ⚠️ 仅 Linux/macOS |

- **L5 OS 级沙箱**：`nanobot/agent/tools/sandbox.py` 唯一后端是 `bwrap`（Bubblewrap，**Linux**）；`workspace_access.py` 另识别 `macOS App Sandbox`，靠环境变量 `NANOBOT_WORKSPACE_SANDBOX_PROVIDER` + `NANOBOT_WORKSPACE_SANDBOX_ENFORCED` 检测（由部署/容器设，nanobot 自己不启沙箱）。**Windows 无 OS 级沙箱后端**。
- **L2 黑名单**（`shell.py`）：默认拦 `rm -rf` / `del /f` / `rmdir /s` / `format` / `mkfs`·`diskpart` / `dd` / 磁盘写入 / `shutdown`·`reboot` / fork bomb / 写 `history.jsonl`·`.dream_cursor` 等，不受权限模式影响。
- **L3/L4 配置示例**（`tools.exec`）：
  ```jsonc
  "tools": { "exec": {
    "deny_patterns": ["\\bcurl\\b", "\\bwget\\b"],
    "allow_patterns": ["^ls ", "^cat "],   // 白名单优先于黑名单
    "allowed_env_keys": ["PATH"],          // 只透传指定环境变量
    "timeout": 60                           // 硬超时（秒）
  }}
  ```

> **Windows 桌面端结论**：没有比「默认权限」更安全的内置隔离。要叠加加固用 L3/L4；要真正的内核级隔离，须在 nanobot 之外跑（Windows Sandbox / Hyper-V / WSL2，WSL2 内还能用 bwrap）。

## ⚠️ 核心注意事项 / 避坑指南

这一节是本项目的"血泪经验"，改动时务必遵守：

1. **embeddable `_pth` 不加脚本目录到 sys.path**
   `launcher.py` 必须在最顶部 `sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))`，否则 `import onboard_server` 在 embeddable 下**静默失败**，pythonw 无控制台 → 看起来"快捷方式打不开任何东西"。这是最常见的坑。

2. **gateway 必须有 provider 才能启动**
   `build_provider_snapshot` 在无 API key 时直接抛错退出。所以 launcher **不能**在未配置时启动 gateway —— 必须先走网页引导、写入配置，再启动 gateway。`launcher.py` 的 `config_is_configured()` 判断就是这个目的。

3. **不要直接双击 `nanobot.exe`**
   `nanobot.exe` 只是 WebView 壳，**不会**自己启动后端。必须通过快捷方式（→ launcher）启动，由 launcher 拉起路由 + gateway。直接双击 exe 会因 8766 没人监听而 `ERR_CONNECTION_REFUSED`。

4. **Pake 构建时目标 URL 必须在线**
   `pake-cli` 构建时会抓取页面。构建 8766 的 Pake 前，**必须先临时启动 `onboard_server.py`**（它在 8766 提供页面），否则构建失败。

5. **Pake/Tauri 编译需要 VS Build Tools**
   Rust MSVC 目标需要 `link.exe` + Windows SDK（`kernel32.lib` 等）。需安装 **VS 2022 Build Tools 的 VCTools workload**。注意：Git Bash 自带的 `/usr/bin/link.exe`（Unix 硬链接工具）会和 MSVC `link.exe` 冲突，构建时要用 `build_pake_env.ps1`（它走 `vcvars64.bat` 把 MSVC 工具加到 PATH 前面）。

6. **免登录本地访问 = 空 `token_issue_secret`**
   gateway 的 `/webui/bootstrap`：`token_issue_secret` 为空时，仅校验 localhost 即可发 token → WebUI 自动登录、**无登录页**。引导表单因此**不需要密码字段**。若历史配置里残留了密码，需清掉 `token_issue_secret` 才能免登录。

7. **默认中文靠 Pake 注入，不是改 WebUI**
   WebUI 的 locale 来自 `localStorage["nanobot.locale"]`。通过 Pake `--inject inject-locale.js` 在页面脚本执行前写入，即可强制中文默认，无需改 nanobot WebUI 源码。

8. **`PYTHONNOUSERSITE=1` 防污染**
   embeddable 启用了 `import site`，默认会读取用户级 site-packages，可能混入本机其他 Python 的包。launcher 给子进程设 `PYTHONNOUSERSITE=1`，确保只用 bundle 自带的库。

9. **测试时别用真实配置路径**
   `build_and_save_config` 默认写 `~/.nanobot/config.json`（生产用途）。**手动测试要临时重定向 `get_config_path`**，否则会覆盖/删除真实配置。

## 构建流程

### 前置依赖

| 工具 | 用途 | 安装 |
|------|------|------|
| Python ≥ 3.11 | 构建 nanobot wheel、跑脚本 | https://python.org |
| Bun ≥ 1.0 | 构建 WebUI | `npm install -g bun` |
| Rust ≥ 1.85 | 编译 Pake/Tauri | https://rustup.rs |
| **VS 2022 Build Tools（VCTools）** | 提供 MSVC `link.exe` + Windows SDK | winget / VS Installer |
| Node + npm | 装 pake-cli | https://nodejs.org |
| NSIS 3.x | 生成 Windows 安装包 | https://nsis.sourceforge.io |

### 一键构建

```bash
# 完整构建（需所有依赖；Pake 步骤需 VS Build Tools）
python desktop/scripts/build_all.py
```

### 分步构建

```bash
# 1. 构建 WebUI（输出到 nanobot/web/dist/）
cd webui && bun install && bun run build

# 2. 构建 nanobot wheel（供 embeddable 安装，避免在 bundle 里编译）
python -m pip wheel . --no-deps -w desktop/output/wheels/

# 3. 制作嵌入式 Python bundle
#    （下载 embeddable → 解压 → 改 _pth → get-pip → 装 wheel）
#    见 build_all.py 的 build_python_bundle 步骤

# 4. 构建 Pake（需 VS Build Tools + 临时启动路由）
python desktop/backend/onboard_server.py &   # 临时提供 8766 页面
powershell -File desktop/scripts/build_pake_env.ps1

# 5. 生成 Windows 安装包
makensis \
  -DOUTPUT_DIR=desktop/output \
  -DASSETS_DIR=desktop/assets \
  -DBACKEND_DIR=desktop/backend \
  -DLICENSE_PATH=LICENSE \
  desktop/installer/nanobot-desktop.nsi
```

## 构建产物

`desktop/output/`（已 gitignore，不入库）：

| 文件 | 说明 |
|------|------|
| `nanobot-desktop-setup.exe` | Windows 安装包（~59MB） |
| `nanobot.exe` | Pake/Tauri 原生窗口（~8.6MB，含中文注入） |
| `python-bundle/` | 嵌入式 Python 3.12 + nanobot + 全部依赖（~250MB） |

## 跨平台：macOS 打包（Intel + ARM）

**⚠️ 无法在 Windows 上交叉构建 macOS 安装包**——Tauri/Pake 的 `.dmg`/`.app` 需要 macOS SDK + Xcode，只能在 **macOS 主机** 或 **GitHub Actions 的 macOS runner** 上构建。

本仓库提供 `.github/workflows/build-desktop.yml`，在 CI 上一次产出三目标：

| 目标 | Runner | 产物 |
|------|--------|------|
| Windows x64 | `windows-latest` | `nanobot-desktop-setup.exe`（NSIS） |
| macOS Intel | `macos-13` | `nanobot.dmg`（Pake） |
| macOS ARM (M1/M2) | `macos-14` | `nanobot.dmg`（Pake） |

触发方式：
- **手动**：GitHub → Actions → `build-desktop` → Run workflow。
- **自动**：推送 `v*` tag 且改动了 `desktop/` / `webui/` / `nanobot/` 时。

在 Mac 上本地构建（需 Xcode + Rust + Node）：
```bash
# 1. 临时启动前端路由（pake 构建要抓页面）
python desktop/backend/onboard_server.py &
# 2. 双架构（Intel + ARM 合并到一个 .dmg）
pake http://127.0.0.1:8766 --name nanobot \
  --icon desktop/assets/nanobot_icon.png \
  --width 1100 --height 720 --multi-arch \
  --inject desktop/assets/inject-locale.js
```

> macOS 的后端 bundle 用 [python-build-standalone](https://github.com/indygreg/python-build-standalone)（可重分发的独立 Python，按 `aarch64-apple-darwin` / `x86_64-apple-darwin` 分架构下载），`launcher.py` 已兼容（macOS 下找 `python3` 而非 `pythonw.exe`）。

## 安装后体验

1. 双击桌面 **"nanobot Desktop"** 快捷方式。
2. **首次**：弹出原生窗口 → 加载动画 → 网页引导（默认 DeepSeek / `deepseek-v4-pro` / 无密码）→ 填 Key → 自动进聊天。
3. **之后**：直接进中文聊天界面（免登录）。
4. 关窗口即停止后端，不留残余进程。

### 快捷方式（开始菜单）

- **nanobot Desktop** — 启动应用（唯一入口）
- **Uninstall nanobot Desktop** — 卸载（保留用户数据）

## 故障排查

- **快捷方式点了没反应**：看 `~/.nanobot/desktop-launcher.log`。多半是 embeddable `_pth` 导致 import 失败（见避坑 #1）。
- **窗口显示 `ERR_CONNECTION_REFUSED`**：说明没通过快捷方式启动（launcher 没跑）。用快捷方式启动；别直接双击 `nanobot.exe`。
- **WebUI 还弹登录页**：config 里残留 `token_issue_secret`。删掉该字段（见避坑 #6）。
- **Pake 构建失败（link.exe / kernel32.lib 找不到）**：装 VS Build Tools VCTools，用 `build_pake_env.ps1` 构建（见避坑 #5）。

## 开发调试

- **单独跑前端路由**：`python desktop/backend/onboard_server.py` → 访问 `http://127.0.0.1:8766`。
- **看 launcher 行为**：`tail -f ~/.nanobot/desktop-launcher.log`。
- **临时清空配置模拟首次**：`mv ~/.nanobot/config.json ~/.nanobot/config.json.bak`。
