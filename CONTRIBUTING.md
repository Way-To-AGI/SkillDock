# 贡献

欢迎补充 Agent 目录规则、改进交互或修复缺陷。目录规则在 `app/agent-catalog.json`；请附上产品官方文档或官方源码的依据。不要将项目技能目录登记成全局目录。

运行 `npm test`。测试只操作临时目录，不要求安装 Electron 或联网。`npm run test:network` 会访问 skills.sh 和 GitHub，并在临时目录验证安装；请勿向测试添加真实个人技能。

提交问题时提供系统、Python 版本、操作步骤和错误信息；请移除技能内容、账户、访问令牌和个人路径。界面逻辑位于 `app/web/`，文件服务位于 `app/server.py`，发现逻辑位于 `app/discovery.py`。
