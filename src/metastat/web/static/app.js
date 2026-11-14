// "The window is open" signal: the server shuts down when the signals stop after the window is closed.
// When the program no longer answers (closed, started again), the window says so instead of pretending to work.
var failures = 0;
function offline() {
  var bar = document.getElementById('offline');
  if (failures >= 2 && !bar) {
    bar = document.createElement('div');
    bar.id = 'offline';
    bar.className = 'offline';
    bar.setAttribute('role', 'alert');
    bar.textContent = 'Metastat is not responding: the program was closed. Start it again from its icon; you can close this window.';
    document.body.appendChild(bar);
  } else if (failures === 0 && bar) {
    bar.remove();
  }
}
function ping() {
  fetch('/api/ping', { method: 'POST' })
    .then(function (r) { failures = r.ok ? 0 : failures + 1; offline(); })
    .catch(function () { failures += 1; offline(); });
}
ping();
setInterval(ping, 20000);

// Confirmation before an action that is hard to undo (data-confirm attribute) and a double-submit guard:
// a second click on the same form does nothing (buttons are not disabled because some of them carry a value).
var forms = document.querySelectorAll('form');
forms.forEach(function (form) {
  form.addEventListener('submit', function (ev) {
    var msg = form.getAttribute('data-confirm');
    if (msg && !window.confirm(msg)) { ev.preventDefault(); return; }
    if (form.method.toLowerCase() !== 'post') return;
    if (form.dataset.sent) { ev.preventDefault(); return; }
    form.dataset.sent = '1';
  });
});
window.addEventListener('pageshow', function (ev) {  // back via the Back button: forms are active again
  if (ev.persisted) forms.forEach(function (form) { delete form.dataset.sent; });
});

// Fields that submit their form right away (connection switcher, sorting). No scripts in the HTML (CSP).
document.querySelectorAll('[data-autosubmit]').forEach(function (el) {
  el.addEventListener('change', function () { el.form.submit(); });
});

// Live view of the background job (Sync screen) and of report building (Reports screen).
[['synclog', '/api/sync'], ['reportlog', '/api/report']].forEach(function (pair) {
  var box = document.getElementById(pair[0]);
  if (!box) return;
  var wasRunning = box.dataset.running === '1';
  function poll() {
    fetch(pair[1]).then(function (r) { return r.json(); }).then(function (s) {
      if (s.lines.length) box.textContent = s.lines.join('\n');
      box.scrollTop = box.scrollHeight;
      if (s.running) { wasRunning = true; setTimeout(poll, 1500); }
      else if (wasRunning) { location.reload(); }
    }).catch(function () { setTimeout(poll, 4000); });
  }
  poll();
});
