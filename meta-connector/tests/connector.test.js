// Tests for the Apps Script connector, run with Node's built-in test runner (no dependencies):
//   node --test meta-connector/tests/connector.test.js
// Code.gs and the panel script from Index.html run in a vm context with small stand-ins for the Google services
// and the DOM. Security tests are numbered like the audit list (7 ReDoS, 13 randomness, 16 prototype pollution,
// 17 injection into the page).
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { spawnSync } = require('node:child_process');

const DIR = path.join(__dirname, '..');
const CODE = fs.readFileSync(path.join(DIR, 'Code.gs'), 'utf8');
const HTML = fs.readFileSync(path.join(DIR, 'Index.html'), 'utf8');
const PANEL = HTML.match(/<script>([\s\S]*?)<\/script>/)[1];

// ---------- Code.gs with stand-ins for UrlFetchApp, PropertiesService and Looker Studio ----------

function respond(url) {
  if (url.includes('BOOM')) throw new Error('Address unavailable: ' + url + '&access_token=SECRET_TOKEN');
  const u = new URL(url);
  const p = u.pathname;
  if (u.searchParams.get('fields') === 'access_token') return { access_token: 'PAGE_TOKEN', id: 'X' };
  if (p.endsWith('/posts')) {
    if (u.searchParams.get('after')) return { data: [] };
    const next = p.includes('EVIL') ? 'https://evil.example/steal?after=1'
      : 'https://graph.facebook.com/v23.0/PAGE1/posts?after=1&access_token=LEAKED_TOKEN';
    return { data: [{ id: 'P1', created_time: '2026-10-02T10:00:00+0000', message: 'm', shares: { count: 1 } }],
             paging: { next } };
  }
  if (p.endsWith('/media')) {
    if (u.searchParams.get('after')) return { data: [] };
    return { data: [{ id: 'M1', timestamp: '2026-10-02T10:00:00+0000', media_type: 'IMAGE' }],
             paging: { next: 'https://graph.facebook.com/v23.0/IG1/media?access_token=LEAKED_TOKEN&after=1' } };
  }
  if (p.endsWith('/insights')) {
    const m = (u.searchParams.get('metric') || 'spend').split(',')[0];
    return { data: [{ name: m, values: [{ end_time: '2026-10-03T07:00:00+0000', value: 1 }], total_value: { value: 1 },
                      date_start: '2026-10-02', campaign_id: 'c', spend: '1' }] };
  }
  if (p.endsWith('/me')) return { name: 'Tester', id: '1' };
  if (p.endsWith('/adaccounts') || p.endsWith('/accounts')) return { data: [] };
  return { followers_count: 5, data: [] };
}

function loadCode() {
  const calls = [];
  let userError = null;
  const fetch = (url, opts) => {
    calls.push({ url, headers: (opts && opts.headers) || {} });
    const body = respond(url);
    return { getResponseCode: () => 200, getContentText: () => JSON.stringify(body) };
  };
  const chain = () => new Proxy({}, { get: (_, k) => (k === 'build' ? () => ({}) : () => chain()) });
  const ctx = {
    DataStudioApp: { createCommunityConnector: () => new Proxy({
      newUserError: () => {
        const e = { text: '', debug: '' };
        return { setDebugText(t) { e.debug = t; return this; }, setText(t) { e.text = t; return this; },
                 throwException() { userError = e; throw new Error('USER_ERROR'); } };
      },
    }, { get: (t, k) => t[k] || (() => chain()) }) },
    PropertiesService: { getUserProperties: () => ({ getProperty: () => 'SECRET_TOKEN', setProperty() {}, deleteProperty() {} }) },
    UrlFetchApp: { fetch, fetchAll: (reqs) => reqs.map((r) => fetch(r.url, r)) },
    Utilities: { formatDate: (d) => d.toISOString().replace(/[-:T]/g, '').slice(0, 14) },
    Session: { getScriptTimeZone: () => 'UTC' },
    HtmlService: {},
  };
  vm.createContext(ctx);
  vm.runInContext(CODE, ctx);
  return { ctx, calls, userError: () => userError };
}

const range = (code, src, id) => code.ctx.fetchRows_(src, id, '2026-10-01', '2026-10-03');

test('every source and the panel calls work with the stand-ins', () => {
  const code = loadCode();
  for (const s of ['ads', 'page', 'fbposts']) range(code, s, 'PAGE1');
  for (const s of ['ig', 'igposts']) range(code, s, 'IG1');
  code.ctx.panelStatus();
  code.ctx.panelAssets();
  code.ctx.setCredentials({ key: 'NEW_KEY' });
  assert.ok(code.calls.length > 20);
});

test('the token never goes into a request URL', () => {
  const code = loadCode();
  for (const s of ['ads', 'page', 'fbposts']) range(code, s, 'PAGE1');
  for (const s of ['ig', 'igposts']) range(code, s, 'IG1');
  code.ctx.panelStatus();
  code.ctx.panelAssets();
  code.ctx.setCredentials({ key: 'NEW_KEY' });
  const leaks = code.calls.filter((c) => /[?&]access_token=|SECRET_TOKEN|PAGE_TOKEN|LEAKED_TOKEN|NEW_KEY/.test(c.url));
  assert.deepEqual(leaks.map((c) => c.url), []);
  const unsigned = code.calls.filter((c) => !/^Bearer (SECRET_TOKEN|PAGE_TOKEN|NEW_KEY)$/.test(c.headers.Authorization || ''));
  assert.deepEqual(unsigned.map((c) => c.url), [], 'every request carries the token in the Authorization header');
});

test('a paging.next link outside graph.facebook.com is refused before any request', () => {
  const code = loadCode();
  assert.throws(() => range(code, 'fbposts', 'EVIL'));
  assert.ok(!code.calls.some((c) => c.url.includes('evil.example')));
});

test('report viewers never see the token in error messages', () => {
  const code = loadCode();
  assert.equal(code.ctx.isAdminUser(), false, 'debug details would be shown to every viewer of a shared report');
  assert.throws(() => code.ctx.getData({ configParams: { source: 'page', objectId: 'BOOM' }, fields: [],
                                          dateRange: { startDate: '2026-10-01', endDate: '2026-10-02' } }));
  const e = code.userError();
  assert.ok(e && e.text, 'a user-facing error was raised');
  assert.doesNotMatch(e.text + e.debug, /SECRET_TOKEN/);
});

// ---------- 7. ReDoS (in a child process with a time limit, so a runaway regex cannot hang the run) ----------

test('7: regular expressions on API data and error text stay fast on long input', () => {
  const script = `
    const vm = require('node:vm'), fs = require('node:fs');
    const ctx = { DataStudioApp: { createCommunityConnector: () => ({}) }, Utilities: { formatDate: () => '' },
                  Session: { getScriptTimeZone: () => 'UTC' } };
    vm.createContext(ctx);
    vm.runInContext(fs.readFileSync(${JSON.stringify(path.join(DIR, 'Code.gs'))}, 'utf8'), ctx);
    const N = 100000, cases = [
      ['nextUrl_', () => ctx.nextUrl_('https://graph.facebook.com/x?' + 'access_token=&'.repeat(N))],
      ['nextUrl_', () => ctx.nextUrl_('https://graph.facebook.com/x' + '?&'.repeat(N))],
      ['redact_', () => ctx.redact_('access_token='.repeat(N) + ' Bearer '.repeat(N))],
      ['redact_', () => ctx.redact_('Bearer' + ' '.repeat(N) + '!')],
      ['localTime_', () => { try { ctx.localTime_('+00'.repeat(N)); } catch (e) {} }],
    ];
    let worst = 0, which = '';
    for (const [name, fn] of cases) { const t = Date.now(); try { fn(); } catch (e) {} const d = Date.now() - t; if (d > worst) { worst = d; which = name; } }
    console.log(worst + ' ' + which);`;
  const r = spawnSync(process.execPath, ['-e', script], { encoding: 'utf8', timeout: 20000 });
  assert.equal(r.error, undefined, 'a regular expression ran for over 20 s (catastrophic backtracking)');
  assert.equal(r.status, 0, r.stderr);
  const [ms, which] = r.stdout.trim().split(' ');
  assert.ok(Number(ms) < 1000, `slowest case (${which}) took ${ms} ms`);
});

// ---------- panel (Index.html) with a small stand-in DOM ----------

function element() {
  return { value: '', innerHTML: '', outerHTML: '', textContent: '', disabled: false, hidden: false, checked: false,
           dataset: {}, style: {}, children: [], classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
           setAttribute() {}, getAttribute: () => null, addEventListener() {}, focus() {}, click() {},
           querySelector: () => element(), querySelectorAll: () => [], closest: () => null, appendChild() {} };
}

function loadPanel() {
  const els = {};
  const pending = () => new Proxy({}, { get: () => () => {} });  // server calls never answer in these tests
  const ctx = {
    document: { querySelector: (s) => (els[s] = els[s] || element()), querySelectorAll: () => [],
                createElement: () => element(), addEventListener() {}, body: element() },
    localStorage: { getItem: () => null, setItem() {} },
    google: { script: { run: { withSuccessHandler: () => ({ withFailureHandler: pending }) } } },
    setTimeout, clearTimeout, URL, Blob: function Blob() {},
  };
  ctx.window = ctx;
  vm.createContext(ctx);
  vm.runInContext(PANEL, ctx);
  // the sources and metrics the panel gets from panelStatus() in Code.gs
  ctx.S.status = JSON.parse(JSON.stringify(loadCode().ctx.panelStatus()));
  return ctx;
}

const HOSTILE = {
  post_id: 'P1', post_time: '20261002100000', post_type: '<b>Reel</b>',
  message: '<img src=x onerror=alert(1)>"\'&', image: '" onerror="alert(1)', permalink: 'javascript:alert(document.domain)',
  views: 10, reach: 5, likes: 1, comments: 0, shares: 0, saves: 0,
};

function renderPosts(panel) {
  panel.S.sourceId = 'igposts';
  panel.S.rows = [HOSTILE];
  const ms = panel.src().metrics;
  return panel.renderSheet(panel.S.rows, ms).html + panel.renderTable(panel.S.rows, ms);
}

test('17: esc() escapes every HTML special character', () => {
  const panel = loadPanel();
  assert.equal(panel.esc('<a href="x" title=\'y\'>&</a>'), '&lt;a href=&quot;x&quot; title=&#39;y&#39;&gt;&amp;&lt;/a&gt;');
  assert.equal(panel.esc(null), '');
});

test('17: post text, type and image from Meta cannot inject HTML into the panel', () => {
  const html = renderPosts(loadPanel());
  assert.doesNotMatch(html, /<img src=x/, 'the caption became an element');
  assert.doesNotMatch(html, /<b>Reel<\/b>/, 'the post type became markup');
  assert.doesNotMatch(html, /src="" onerror=/, 'the image URL broke out of its attribute');
  assert.match(html, /&lt;img src=x onerror=alert\(1\)&gt;/);
});

test('17: post links and images in the panel are only https (no javascript:, data: or http: URLs)', () => {
  const panel = loadPanel();
  const good = Object.assign({}, HOSTILE, { post_id: 'P2', message: 'ok', post_type: 'Photo',
    permalink: 'https://www.instagram.com/p/abc/', image: 'https://scontent.cdninstagram.com/a.jpg' });
  const bad = [
    HOSTILE,
    Object.assign({}, HOSTILE, { post_id: 'P3', permalink: 'data:text/html,<script>alert(1)</script>', image: 'http://x/a.jpg' }),
    Object.assign({}, HOSTILE, { post_id: 'P4', permalink: ' JavaScript:alert(1)', image: 'javascript:alert(1)' }),
  ];
  panel.S.sourceId = 'igposts';
  panel.S.rows = [good, ...bad];
  const ms = panel.src().metrics;
  const html = panel.renderSheet(panel.S.rows, ms).html + panel.renderTable(panel.S.rows, ms);
  const urls = [...html.matchAll(/(?:href|src)="([^"]*)"/g)].map((m) => m[1]).filter((u) => !u.startsWith('#'));
  for (const u of urls) assert.match(u, /^https:\/\//, `unsafe URL in the panel: ${u}`);
  assert.ok(urls.includes('https://www.instagram.com/p/abc/'), 'the normal post link must stay');
  assert.ok(urls.includes('https://scontent.cdninstagram.com/a.jpg'), 'the normal post image must stay');
});

test('17: CSV export cells never start a formula', () => {
  const m = HTML.match(/var q = function \(s\) \{[^\n]*\};/);
  assert.ok(m, 'the CSV quoting helper was not found');
  const q = vm.runInNewContext('(' + m[0].replace(/^var q = /, '').replace(/;$/, '') + ')', { String });
  for (const s of ['=HYPERLINK("http://x")', '+48 600', '-1+1', '@SUM(A1)', '\tx', '\rx']) {
    assert.match(q(s), /^"'/, s);
  }
  assert.equal(q('Plain "text"'), '"Plain ""text"""');
});

// ---------- static checks ----------

test('13: no Math.random in the connector or the panel', () => {
  for (const [name, text] of [['Code.gs', CODE], ['Index.html', HTML]]) assert.doesNotMatch(text, /Math\.random/, name);
});

test('16: no object merging or prototype access that data could reach', () => {
  for (const [name, text] of [['Code.gs', CODE], ['Index.html', HTML]]) {
    assert.doesNotMatch(text, /Object\.assign\s*\(|__proto__|\bconstructor\s*\[|\[\s*['"]prototype['"]\s*\]/, name);
  }
});

test('17: no eval, new Function, document.write or string timers', () => {
  for (const [name, text] of [['Code.gs', CODE], ['Index.html', HTML]]) {
    assert.doesNotMatch(text, /\beval\s*\(|new Function\s*\(|document\.write|setTimeout\s*\(\s*['"]/, name);
  }
});
