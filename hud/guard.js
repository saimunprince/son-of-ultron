// What the HUD window may load, and who in it may use the microphone, camera and position. Pure (no Electron), so
// `node --test` covers it; main.js wires it to will-navigate, the window-open handler and the permission handlers.
//
// The HUD window carries the preload bridge (ultronWin, ultronSys): any page that loads in it gets them. Only the
// HUD itself may: the page the core serves (CORE + /hud/) or the local copy (hud.html next to main.js).
'use strict';
const { pathToFileURL } = require('url');

const HUD_PATHS = ['/hud', '/hud/', '/hud/hud.html'];  // server.py: /hud redirects to /hud/, which serves hud.html
const PERMISSIONS = ['media', 'geolocation', 'fullscreen', 'notifications'];

function parse(u) { try { return new URL(String(u)); } catch (_) { return null; } }

// url: a page about to load or loaded in the HUD window; core: the backend's base URL; hudFile: the local hud.html path
function trustedPage(url, core, hudFile) {
  const u = parse(url);
  if (!u) return false;
  if (u.protocol === 'file:') {
    if (!hudFile) return false;
    u.search = ''; u.hash = '';  // ?ask= / ?nofeed are the HUD's own switches
    return u.href.toLowerCase() === pathToFileURL(hudFile).href.toLowerCase();  // Windows paths ignore case
  }
  const c = parse(core);
  return !!c && (u.protocol === 'http:' || u.protocol === 'https:') && u.origin === c.origin && HUD_PATHS.includes(u.pathname);
}

// permission: Electron's name; pageUrl: the URL of the window's page; requesting: the requesting frame's URL or origin
// (a frame inside the page may come from somewhere else). Both must be the HUD's own.
function permissionAllowed(permission, pageUrl, requesting, core, hudFile) {
  if (!PERMISSIONS.includes(permission) || !trustedPage(pageUrl, core, hudFile)) return false;
  if (!requesting) return true;
  const r = parse(requesting);
  if (!r) return false;
  if (r.protocol === 'file:') return parse(pageUrl).protocol === 'file:' && (r.pathname === '/' || trustedPage(requesting, core, hudFile));
  const c = parse(core);
  return parse(pageUrl).protocol !== 'file:' && r.origin === c.origin;
}

module.exports = { trustedPage, permissionAllowed, PERMISSIONS, HUD_PATHS };
