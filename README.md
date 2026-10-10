# SkillDock

macOS 独立桌面窗口应用，统一管理本机各类 Agent 的**用户级全局技能**。

[下载 macOS Apple Silicon 应用](https://github.com/Way-To-AGI/SkillDock/releases) · [测试记录](docs/TESTING.md) · MIT License

## 打开应用

双击 `release/SkillDock-darwin-arm64/SkillDock.app`。也可以将它拖到「应用程序」文件夹。

本次构建适用于 Apple Silicon。需要 Python 3.10 或更新版本；应用依次查找 Homebrew、`/usr/local/bin` 和系统 Python，也可以通过环境变量 `SKILLDOCK_PYTHON` 指定可执行文件。首次启动会扫描技能目录，数量较多时请稍等。

## 管理范围

应用从各 Agent 的用户级目录读取技能，创建、编辑和删除直接操作对应目录。全局技能供对应 Agent 在跨项目工作时使用；不会自动扫描当前项目。列表显示 Agent，编辑器及删除弹窗显示实际路径。

`~/.agents/skills` 是共享全局目录，一些 Agent（例如 Codex、Cline、Kimi、Pi、Warp、Zed）可使用它；实际加载行为取决于对应 Agent 版本。`~/.codex/skills` 也单独管理。共享目录只有一份磁盘内容，编辑会影响所有读取该内容的 Agent；复制到其他目录之后则是独立副本。

### 目录发现

内置 **77 类 Agent** 的用户级目录规则（截至 2026-10-10），包括 Claude Code、Codex、Cursor、Windsurf、Gemini CLI、OpenCode、OpenClaw 等；共享路径合并为一个目录，并列出适用 Agent。规则在 [`app/agent-catalog.json`](app/agent-catalog.json)。目录存在表示发现了路径，不代表 Agent 已安装或实际加载了技能。

同时在用户隐藏配置目录、`~/.local/share`、macOS Application Support 及 Windows AppData 中查找包含 `*/SKILL.md` 的 `skills` 集合。未知目录标记为 **待确认、只读**，点击「全局目录 → 确认管理」后开放编辑。「重新扫描」更新目录；也可以手动添加任意全局技能路径。

扫描不进入项目、依赖、构建、临时、凭证或缓存目录，不跟随目录符号链接；最多访问 2,400 个目录、每层 200 个子目录、深度 4 层，时间预算 2 秒。达到上限会在界面提示。支持 `XDG_CONFIG_HOME`、`CODEX_HOME`、`CLAUDE_CONFIG_DIR`、`VIBE_HOME`、`HERMES_HOME`、`AUTOHAND_HOME` 和 `GROK_HOME` 的绝对路径配置。

无法保证穷尽所有 Agent、未来版本和自定义位置；不遵循 SKILL.md 格式的产品需要单独适配。未知位置经结构推断，需由用户确认。

新添加目录明确登记为全局目录。历史配置中登记为其他范围的目录保留，但不出现在全局列表。

## 界面与功能（v1.3.0）

采用左侧导航、中间技能列表、右侧详情的工作台布局。侧栏提供全部、可编辑、多 Agent 和需检查视图，及各 Agent 筛选。同名技能合并为一项；右侧展示安装分布、SKILL.md 编辑和附件。多个 Agent 副本可分别打开。

- 新建只填写名称、描述和目标 Agent。
- 勾选后显示批量复制和删除；删除弹窗列出实际副本与路径。
- 复制包含技能附件，已有同名目录跳过，失败会报告已完成的数量。
- 保存直接写入当前路径，保留原版本备份，外部修改时拒绝覆盖。
- 删除移入回收站，通知可撤销本次删除；历史删除从回收站恢复。
- 侧栏提供 skills.sh 搜索与安装、Agent 目录管理和回收站，顶部提供刷新、新建。

快捷键：/ 搜索、⌘S 保存、Esc 关闭。与 HTML 原型不同，桌面应用会真实修改本地技能文件。

Codex 的 `.system` 内置技能和插件缓存只读，可复制到个人技能目录后编辑。技能目录的符号链接可跳转到已登记的全局源技能编辑，详情会显示发现的引用目录；链接本身只读。删除可移除个人目录中的链接，保留链接指向的源目录。复制跳过符号链接附件、依赖目录和构建目录。

「新建技能」会创建所选 Agent 的目录。是否被 Agent 加载取决于该 Agent 的技能目录规则；必要时重新启动 Agent。SkillDock 不控制各 Agent 的启用开关或运行过程。

## 数据与隐私

实际技能保留在各 Agent 的原目录。应用配置、回收站和旧版文档默认位于：

`~/Library/Application Support/SkillDock/store/`

- `settings.json`：技能目录、回收站索引和最近操作。
- `trash/`：移出的完整技能文件夹。
- `history/`：编辑前的 `SKILL.md` 备份。
- `cache/`：短期缓存的公开仓库压缩包。

本地服务只监听 `127.0.0.1`，每次启动生成独立会话。发现技能时会向 skills.sh 发送搜索词，预览和安装时访问 GitHub。不会上传本地技能。

不要删除 `store` 文件夹后再期待恢复回收站内容。要备份应用数据，请同时备份该目录和实际技能目录。

## 远程来源说明

搜索接口参照 [Vercel skills 官方客户端](https://github.com/vercel-labs/skills/blob/main/src/find.ts) 的调用方式。目录约定参考 [官方 Agent 注册表](https://github.com/vercel-labs/skills/blob/main/src/agents.ts)。

skills.sh API 可能变化。非 GitHub 来源目前提供外部详情链接；应用内自动安装支持公开 GitHub 仓库。安装取仓库当前 HEAD，保留来源和压缩包哈希到 `.skilldock-source.json`；暂不提供远程版本升级或版本锁定。

## 从源码运行

在本目录执行：

```sh
npm install
npm start
```

打包 Apple Silicon 应用：

```sh
npm run package
```

Electron 下载网络较慢时可对本次命令使用 `ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/`；不会修改全局 npm 配置。

源码结构：`desktop.cjs` 为桌面入口，`preload.cjs` 提供原生目录选择接口，`app/server.py` 为仅依赖 Python 标准库的本地文件服务，`app/web/` 为界面。

此构建未签名、未公证。若 macOS 拦截，可在 Finder 右键选择「打开」。

## 测试

Python 3.10+ 和 Node 22+：

```sh
npm test
npm run test:network # 可选：真实联网搜索、预览和临时目录安装
```

自动测试使用临时目录；无需联网或安装 Electron。GitHub Actions 在 Python 3.10、3.13 下运行离线测试。详情见 [测试记录](docs/TESTING.md)。
