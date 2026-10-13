// SYRAX desktop shell: runs the HUD fullscreen and feeds it real machine telemetry.
// The HUD itself is served by SYRAX's own backend (http://127.0.0.1:8765/hud) so it talks to the
// core from the core's own origin; while the core is down the shell shows the local copy, which
// keeps calling the core (hud/link.js) and reloads from it once it answers.
const { app, BrowserWindow, ipcMain, session, nativeTheme } = require('electron');
const path = require('path');
const si = require('systeminformation');

const CORE = (process.env.SYRAX_URL || 'http://127.0.0.1:8765').replace(/\/$/, '');

// dark native chrome everywhere (window borders, context menus), never the light Windows theme
nativeTheme.themeSource = 'dark';

// let the hum and the greeting play without waiting for a click
app.commandLine.appendSwitch('autoplay-policy', 'no-user-gesture-required');

const sys = { static: null, fast: null, slow: null, t: 0 };

async function pollStatic() {
  const [cpu, os, gfx] = await Promise.all([si.cpu(), si.osInfo(), si.graphics()]);
  sys.static = {
    cpu: `${cpu.manufacturer} ${cpu.brand}`.trim(),
    cores: cpu.cores, physical: cpu.physicalCores, ghz: cpu.speedMax || cpu.speed,
    os: `${os.distro} ${os.build || os.release}`.trim(), host: os.hostname,
    gpu: gfx.controllers.map(c => c.model).filter(Boolean)[0] || '—',
  };
}
async function pollFast() {
  const [load, mem, net] = await Promise.all([si.currentLoad(), si.mem(), si.networkStats()]);
  const n = net.reduce((a, x) => ({ rx: a.rx + (x.rx_sec || 0), tx: a.tx + (x.tx_sec || 0) }), { rx: 0, tx: 0 });
  sys.fast = {
    cpu: load.currentLoad, cores: load.cpus.map(c => c.load),
    memUsed: mem.active, memTotal: mem.total, swapUsed: mem.swapused,
    rx: n.rx, tx: n.tx,
  };
  sys.t = Date.now();
}
async function pollSlow() {
  const [temp, gfx, procs, disks, io] = await Promise.all([
    si.cpuTemperature(), si.graphics(), si.processes(), si.fsSize(), si.disksIO().catch(() => null),
  ]);
  const gc = gfx.controllers.find(c => c.utilizationGpu != null) || gfx.controllers[0] || {};
  sys.slow = {
    cpuTemp: temp.main > 0 ? temp.main : null,
    gpuLoad: gc.utilizationGpu ?? null, gpuTemp: gc.temperatureGpu ?? null,
    vramUsed: gc.memoryUsed ?? null, vramTotal: gc.memoryTotal ?? gc.vram ?? null,
    procCount: procs.all,
    top: procs.list.filter(p => p.name && !/^(System Idle Process|Idle)$/i.test(p.name))
      .sort((a, b) => b.cpu - a.cpu).slice(0, 6).map(p => ({ name: p.name, cpu: p.cpu, mem: p.memRss })),
    disks: disks.map(d => ({ mount: d.mount, used: d.used, size: d.size, use: d.use })),
    io: io ? { r: io.rIO_sec, w: io.wIO_sec } : null,
  };
}
// chained timers so a slow WMI query never stacks up
function every(ms, fn) {
  const run = async () => { try { await fn(); } catch (e) { console.error(fn.name, e.message); } setTimeout(run, ms); };
  run();
}

// SYRAX_SHOT=<file.png>: open windowed, save a screenshot after a few seconds, then quit (for testing)
// SYRAX_SELFTEST=1: click the HUD's window buttons one by one and print what the window did (for testing)
// SYRAX_ASK=<text>: auto-send one command after load (test hook, mirrors hud.html?ask=)
const SHOT = process.env.SYRAX_SHOT;
const SELFTEST = process.env.SYRAX_SELFTEST;
const ASK = process.env.SYRAX_ASK;

// the core serves the HUD page itself; a core too old to have /hud counts as down for loading (the local copy still links to it)
async function coreUp() {
  try { return (await fetch(CORE + '/hud', { method: 'HEAD', signal: AbortSignal.timeout(1500) })).ok; } catch (_) { return false; }
}

function sendWinState(win, fullscreen) {
  if (!win.isDestroyed()) win.webContents.send('win-state', { fullscreen });
}
function toggleFullscreen(win) {
  const target = !win.isFullScreen();
  win.setFullScreen(target);
  sendWinState(win, target);
}

// the HUD page: from the core when it answers, else the local copy until it does
async function loadHud(win) {
  const query = ASK ? '?ask=' + encodeURIComponent(ASK) : '';
  if (await coreUp()) {
    win.fromCore = true;
    try { await win.loadURL(CORE + '/hud' + query); return; } catch (e) { console.error('core page failed, local copy:', e.message); }
  }
  win.fromCore = false;
  await win.loadFile('hud.html', ASK ? { query: { ask: ASK } } : undefined);
  // the local copy keeps calling the core itself; once the core is up, the served page replaces it
  const retry = setInterval(async () => {
    if (win.isDestroyed()) return clearInterval(retry);
    if (win.fromCore || !(await coreUp())) return;
    clearInterval(retry);
    win.fromCore = true;
    win.loadURL(CORE + '/hud' + query).catch(e => { win.fromCore = false; console.error('core page failed:', e.message); });
  }, 5000);
}

function createWindow() {
  // frameless: no Windows title bar or border; the HUD draws its own minimize / fullscreen / close buttons
  const win = new BrowserWindow({
    width: SHOT ? 1872 : 1600, height: SHOT ? 993 : 900, useContentSize: true,
    frame: false, show: false, autoHideMenuBar: true,
    backgroundColor: '#000000', title: 'SYRAX',
    // never slow down when another window has focus: the HUD keeps animating and polling at full rate
    webPreferences: { preload: path.join(__dirname, 'preload.js'), contextIsolation: true, nodeIntegration: false, backgroundThrottling: false },
  });
  // show only once painted, already fullscreen, so no frame or white flash appears at launch
  win.once('ready-to-show', () => {
    // start maximized (movable by the HUD's title strip); the fullscreen button / F11 go immersive.
    // brief always-on-top so Windows' focus-steal guard can't leave the HUD behind other windows
    if (SHOT) return win.showInactive(); // test screenshots must never take focus (or the user's keystrokes)
    win.maximize();
    win.setAlwaysOnTop(true); win.show(); win.focus(); win.setAlwaysOnTop(false);
  });
  loadHud(win);

  // on Windows the fullscreen events can lag or be skipped, so each change reports the state it knows is true
  win.on('enter-full-screen', () => sendWinState(win, true));
  win.on('leave-full-screen', () => sendWinState(win, false));
  win.webContents.on('did-finish-load', () => sendWinState(win, win.isFullScreen()));

  win.webContents.on('console-message', (e, level, msg) => { if (level >= 2) console.error('[hud]', msg); });
  if (SHOT) setTimeout(async () => {
    require('fs').writeFileSync(SHOT, (await win.webContents.capturePage()).toPNG());
    console.log('SHOT', SHOT, win.fromCore ? 'from-core' : 'local-copy');
    app.quit();
  }, +process.env.SYRAX_SHOT_MS || 9000);
  if (SELFTEST) selfTest(win);
  win.webContents.on('before-input-event', (e, input) => {
    if (input.type !== 'keyDown') return;
    if (input.key === 'F11') { toggleFullscreen(win); e.preventDefault(); }
    else if (input.control && input.key.toLowerCase() === 'q') app.quit();
  });
}

async function selfTest(win) {
  const wait = ms => new Promise(r => setTimeout(r, ms));
  const click = id => win.webContents.executeJavaScript(`document.getElementById('${id}').click()`);
  const drag = () => win.webContents.executeJavaScript(`document.getElementById('drag').classList.contains('on')`);
  const report = async tag => console.log(`STEP ${tag} fullscreen=${win.isFullScreen()} maximized=${win.isMaximized()} minimized=${win.isMinimized()} dragStrip=${await drag()} hwnd=${win.getNativeWindowHandle().readBigUInt64LE()} bounds=${JSON.stringify(win.getBounds())}`);
  win.on('closed', () => console.log('STEP closed'));
  await new Promise(r => win.once('show', r));
  await wait(2500); await report('start');
  // known windowed spot on the primary display, so the harness can drag the title strip with real mouse input
  win.unmaximize(); win.setBounds({ x: 300, y: 150, width: 1200, height: 700 }); await wait(1500);
  await report('windowed');
  console.log('READY-DRAG'); await wait(4000);
  await report('after-drag');
  await click('wc-fs'); await wait(2500); await report('after-fs-click');
  await click('wc-fs'); await wait(2500); await report('after-fs-click-2');
  await click('wc-close');
}

// test runs get their own profile and skip the single-instance lock, so they work beside a running HUD
if (SHOT || SELFTEST) app.setPath('userData', path.join(app.getPath('temp'), 'syrax-hud-test-profile'));
if (!SHOT && !SELFTEST && !app.requestSingleInstanceLock()) app.quit();
else {
  app.whenReady().then(() => {
    const allowed = ['media', 'geolocation', 'fullscreen', 'notifications'];
    session.defaultSession.setPermissionRequestHandler((wc, perm, cb) => cb(allowed.includes(perm)));
    session.defaultSession.setPermissionCheckHandler((wc, perm) => allowed.includes(perm));
    ipcMain.handle('sys', () => sys);
    ipcMain.on('win', (e, cmd) => {
      const w = BrowserWindow.fromWebContents(e.sender);
      if (!w) return;
      if (cmd === 'minimize') w.minimize();
      else if (cmd === 'fullscreen') toggleFullscreen(w);
      else if (cmd === 'close') w.close();
    });
    ipcMain.handle('win-state', e => ({ fullscreen: !!BrowserWindow.fromWebContents(e.sender)?.isFullScreen() }));
    every(60000, pollStatic);
    every(1000, pollFast);
    every(5000, pollSlow);
    createWindow();
  });
  app.on('second-instance', () => BrowserWindow.getAllWindows()[0]?.focus());
  app.on('window-all-closed', () => app.quit());
}
