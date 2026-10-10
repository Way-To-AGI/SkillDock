const { contextBridge, ipcRenderer } = require("electron");
contextBridge.exposeInMainWorld(
  "skilldock",
  Object.freeze({
    desktop: true,
    chooseDirectory: () => ipcRenderer.invoke("choose-directory"),
  }),
);
