const { app, BrowserWindow, dialog, ipcMain, shell } = require("electron");
const { spawn } = require("node:child_process");
const path = require("node:path");
const fs = require("node:fs");

app.setName("SkillDock");
let worker, window, backendOrigin;
const single = app.requestSingleInstanceLock();
if (!single) app.quit();
app.on("second-instance", () => {
  if (window) {
    window.show();
    window.focus();
  }
});

function launch() {
  const candidates = [
    process.env.SKILLDOCK_PYTHON,
    "/opt/homebrew/bin/python3",
    "/usr/local/bin/python3",
    "/usr/bin/python3",
  ].filter(Boolean);
  const python = candidates.find((p) => fs.existsSync(p));
  if (!python) {
    dialog.showErrorBox(
      "缺少 Python 3",
      "SkillDock 需要 Python 3.10 或更新版本。请安装后再打开。",
    );
    app.quit();
    return;
  }
  const data =
    process.env.SKILLDOCK_DATA || path.join(app.getPath("userData"), "store");
  const args = [path.join(__dirname, "app", "server.py"), "--data", data];
  if (process.env.SKILLDOCK_EMPTY === "1") args.push("--empty");
  worker = spawn(python, args, {
    stdio: ["ignore", "pipe", "pipe"],
    env: { ...process.env, PYTHONUNBUFFERED: "1" },
  });
  let output = "",
    errors = "",
    loaded = false;
  worker.stderr.on("data", (b) => {
    errors = (errors + b.toString()).slice(-4000);
  });
  worker.on("error", (e) => {
    dialog.showErrorBox("无法启动本地服务", e.message);
    app.quit();
  });
  worker.on("exit", (code) => {
    if (code && !app.isQuitting) {
      dialog.showErrorBox("本地服务已退出", errors || `退出码 ${code}`);
      app.quit();
    }
  });
  worker.stdout.on("data", (buffer) => {
    output += buffer.toString();
    const match = output.match(
      /SKILLDOCK_URL=(http:\/\/127\.0\.0\.1:\d+\/\?token=[^\s]+)/,
    );
    if (!match || loaded) return;
    loaded = true;
    backendOrigin = new URL(match[1]).origin;
    window = new BrowserWindow({
      width: 1400,
      height: 920,
      minWidth: 760,
      minHeight: 600,
      title: "SkillDock",
      titleBarStyle: "hiddenInset",
      backgroundColor: "#f5f6f4",
      trafficLightPosition: { x: 22, y: 20 },
      show: false,
      webPreferences: {
        preload: path.join(__dirname, "preload.cjs"),
        contextIsolation: true,
        nodeIntegration: false,
        sandbox: true,
        webSecurity: true,
      },
    });
    const external = async (url) => {
      try {
        const u = new URL(url);
        if (["https:", "http:"].includes(u.protocol))
          await shell.openExternal(u.href);
      } catch (_) {}
    };
    window.webContents.setWindowOpenHandler(({ url }) => {
      external(url);
      return { action: "deny" };
    });
    window.webContents.on("will-navigate", (event, url) => {
      if (new URL(url).origin !== backendOrigin) {
        event.preventDefault();
        external(url);
      }
    });
    window.webContents.session.setPermissionRequestHandler((_, __, callback) =>
      callback(false),
    );
    window.once("ready-to-show", () => window.show());
    window.loadURL(match[1]);
    window.on("closed", () => {
      window = null;
      app.quit();
    });
  });
  setTimeout(() => {
    if (!loaded && !app.isQuitting) {
      dialog.showErrorBox("启动超时", errors || "本地服务未能启动");
      app.quit();
    }
  }, 20000).unref();
}
app.whenReady().then(() => {
  ipcMain.handle("choose-directory", async (event) => {
    if (
      !backendOrigin ||
      new URL(event.senderFrame.url).origin !== backendOrigin
    )
      return null;
    const result = await dialog.showOpenDialog(window, {
      title: "选择 agent 的技能目录",
      properties: ["openDirectory", "createDirectory"],
    });
    return result.canceled ? null : result.filePaths[0];
  });
  launch();
});
app.on("before-quit", () => {
  app.isQuitting = true;
  if (worker && !worker.killed) worker.kill();
});
app.on("window-all-closed", () => app.quit());
