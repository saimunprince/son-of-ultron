// The HUD window's guard (guard.js, wired in main.js). Before it, main.js had no will-navigate guard and no
// window-open handler: a URL or file dropped on the HUD loaded that page in the HUD window, with the preload bridge
// (ultronWin, ultronSys); and media/geolocation were granted by permission name to whatever page asked.
const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('path');
const { pathToFileURL } = require('url');
const G = require('./guard.js');

const CORE = 'http://127.0.0.1:8765';
const FILE = path.join('C:\\ai-agent\\son-of-ultron\\hud', 'hud.html');
const FILE_URL = pathToFileURL(FILE).href;

test('the HUD served by the core and its local copy may load in the HUD window', () => {
  assert.equal(G.trustedPage(CORE + '/hud/', CORE, FILE), true);
  assert.equal(G.trustedPage(CORE + '/hud', CORE, FILE), true, 'server.py redirects /hud to /hud/');
  assert.equal(G.trustedPage(CORE + '/hud/?ask=open%20notepad', CORE, FILE), true, 'main.js SYRAX_ASK query');
  assert.equal(G.trustedPage(FILE_URL, CORE, FILE), true);
  assert.equal(G.trustedPage(FILE_URL + '?ask=hi#x', CORE, FILE), true);
  assert.equal(G.trustedPage(FILE_URL.toUpperCase().replace('FILE:', 'file:'), CORE, FILE), true, 'Windows paths ignore case');
});

test('anything else dropped on or followed from the HUD does not load', () => {
  for (const url of [
    'https://example.com/',
    'http://127.0.0.1:8765/',                 // the core, but not the HUD page
    'http://127.0.0.1:8765/hud/feed/iss',     // a feed is data, not a page
    'http://127.0.0.1:3000/hud/',             // another origin with the same path
    'http://localhost:8765/hud/',             // another origin name
    'file:///C:/Users/prince/Downloads/evil.html',
    pathToFileURL(path.join('C:\\ai-agent\\son-of-ultron\\hud', 'hud.html.evil')).href,
    'javascript:alert(1)',
    'data:text/html,<h1>x</h1>',
    'not a url',
    null,
  ]) assert.equal(G.trustedPage(url, CORE, FILE), false, String(url));
});

test('the mic, camera and position go to the HUD page only, and only to a frame of its own origin', () => {
  assert.equal(G.permissionAllowed('media', CORE + '/hud/', CORE + '/hud/', CORE, FILE), true);
  assert.equal(G.permissionAllowed('geolocation', CORE + '/hud/', CORE, CORE, FILE), true, 'a check handler passes the origin');
  assert.equal(G.permissionAllowed('media', CORE + '/hud/', undefined, CORE, FILE), true);
  assert.equal(G.permissionAllowed('media', FILE_URL, FILE_URL, CORE, FILE), true, 'the local copy');
  assert.equal(G.permissionAllowed('geolocation', FILE_URL, 'file:///', CORE, FILE), true, 'a file page\'s origin');
  // the bug: by permission name alone, any page in the window got them
  assert.equal(G.permissionAllowed('media', 'https://example.com/', 'https://example.com/', CORE, FILE), false);
  assert.equal(G.permissionAllowed('geolocation', 'file:///C:/Users/prince/Downloads/evil.html', 'file:///C:/Users/prince/Downloads/evil.html', CORE, FILE), false);
  assert.equal(G.permissionAllowed('media', CORE + '/hud/', 'https://ads.example.com/frame', CORE, FILE), false, 'a foreign frame inside the HUD');
  assert.equal(G.permissionAllowed('media', CORE + '/hud/', FILE_URL, CORE, FILE), false, 'a file frame inside the served HUD');
  assert.equal(G.permissionAllowed('media', null, CORE, CORE, FILE), false, 'no page: no grant');
  assert.equal(G.permissionAllowed('clipboard-read', CORE + '/hud/', CORE, CORE, FILE), false, 'only the four the HUD uses');
  assert.equal(G.permissionAllowed('media', CORE + '/hud/', 'null', CORE, FILE), false, 'an opaque origin');
});
