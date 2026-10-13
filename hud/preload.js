// Bridge between the HUD and the desktop shell:
//  - window.ultronSys: machine telemetry from the main process
//  - window.ultronWin: controls for the frameless window (the HUD draws its own buttons)
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('ultronSys', {
  get: () => ipcRenderer.invoke('sys'),
});

contextBridge.exposeInMainWorld('ultronWin', {
  minimize: () => ipcRenderer.send('win', 'minimize'),
  toggleFullscreen: () => ipcRenderer.send('win', 'fullscreen'),
  close: () => ipcRenderer.send('win', 'close'),
  getState: () => ipcRenderer.invoke('win-state'),
  onState: cb => ipcRenderer.on('win-state', (e, s) => cb(s)),
});
