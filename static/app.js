var S = { chats: [], cid: 0, files: [], live: {}, me: null };

function $(id) { return document.getElementById(id); }
function el(tag, cls, html) {
  var d = document.createElement(tag);
  if (cls) d.className = cls;
  if (html != null) d.innerHTML = html;
  return d;
}
function esc(t) {
  return String(t == null ? '' : t).replace(/[&<>"]/g, function (c) {
    return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
  });
}
function ic(name, cls) { return '<i data-lucide="' + name + '"' + (cls ? ' class="' + cls + '"' : '') + '></i>'; }
function icons() { if (window.lucide && lucide.createIcons) lucide.createIcons(); }

function md(text) {
  var blocks = [];
  var t = esc(text);
  t = t.replace(/```([a-z0-9+#._-]*)\n?([\s\S]*?)```/gi, function (m, lang, code) {
    blocks.push('<pre><code>' + code.replace(/\s+$/, '') + '</code></pre>');
    return '\u0001' + (blocks.length - 1) + '\u0001';
  });
  t = t.replace(/`([^`\n]+)`/g, '<code>$1</code>');
  t = t.replace(/\*\*([^*\n]+)\*\*/g, '<b>$1</b>');
  t = t.replace(/(^|\s)(https?:\/\/[^\s<]+)/g, '$1<a href="$2" target="_blank" rel="noopener">$2</a>');
  var out = [], ul = null, lines = t.split('\n');
  function flush() { if (ul) { out.push('<ul>' + ul.join('') + '</ul>'); ul = null; } }
  for (var i = 0; i < lines.length; i++) {
    var ln = lines[i];
    var h = ln.match(/^#{1,4}\s+(.*)$/);
    var li = ln.match(/^\s*[-*]\s+(.*)$/);
    var pre = ln.match(/^\u0001\d+\u0001$/);
    if (h) { flush(); out.push('<p><b>' + h[1] + '</b></p>'); }
    else if (li) { if (!ul) ul = []; ul.push('<li>' + li[1] + '</li>'); }
    else if (ln.trim() === '') { flush(); }
    else { flush(); out.push(pre ? ln : '<p>' + ln + '</p>'); }
  }
  flush();
  return out.join('').replace(/\u0001(\d+)\u0001/g, function (m, i) { return blocks[+i]; });
}

async function jget(path, opts) {
  opts = opts || {};
  opts.headers = Object.assign({ 'Content-Type': 'application/json' }, opts.headers || {});
  var r = await fetch(path, opts);
  if (r.status === 401) { location.href = '/'; throw new Error('401'); }
  if (!r.ok) throw new Error('http ' + r.status);
  return r.json();
}

function renderChats() {
  var box = $('chats');
  box.innerHTML = '';
  S.chats.forEach(function (c) {
    var n = el('div', 'chat' + (c.id === S.cid ? ' on' : ''));
    n.appendChild(el('span', null, esc(c.title || 'без имени')));
    var d2 = new Date((c.updated || c.created) * 1000);
    if (!isNaN(d2)) {
      n.appendChild(el('span', 'm', d2.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' })
        + ' ' + d2.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' }) + (c.n ? ' · ' + c.n : '')));
    }
    n.onclick = function () { openChat(c.id); };
    box.appendChild(n);
  });
}

async function loadChats() {
  var d = await jget('/api/chats');
  S.chats = d.chats || [];
  renderChats();
}

function reset() {
  $('wrap').innerHTML = '';
  $('title').textContent = '';
  var inp = $('input');
  if (inp) { inp.value = ''; inp.style.height = 'auto'; }
  S.files = [];
  renderAtt();
  updateSend();
}

async function openChat(cid) {
  if (S.live && S.live[cid]) {
    S.cid = cid;
    var c1 = S.chats.filter(function (x) { return x.id === cid; })[0];
    $('title').textContent = c1 ? c1.title : '';
    await loadChats();
    $('app').classList.remove('nav');
    return;
  }
  S.cid = cid;
  dropLive(cid);
  var d = await jget('/api/chats/' + cid + '/messages');
  var c0 = S.chats.filter(function (x) { return x.id === cid; })[0];
  if (c0 && c0.mode) aiThemeSet('mode', c0.mode);
  var wrap = $('wrap');
  wrap.innerHTML = '';
  (d.messages || []).forEach(function (m) { addMsg(m.role, m.content, m.meta); });
  var c = S.chats.filter(function (x) { return x.id === cid; })[0];
  $('title').textContent = c ? c.title : '';
  await loadChats();
  icons();
  scroll(true);
  $('app').classList.remove('nav');
  jget('/api/turns').then(function (t) {
    if ((t.cids || []).indexOf(cid) >= 0) attachLive(cid);
  }).catch(function () {});
}

function newChat() {
  S.cid = 0;
  reset();
  renderChats();
  $('app').classList.remove('nav');
  $('input').focus();
}

function addMsg(role, text, meta) {
  meta = meta || {};
  var wrap = $('wrap');
  if (role === 'user') {
    var t = el('div', 'turn mine');
    var inner = el('div', 'inner');
    var bub = el('div', 'bubble');
    if (meta.files && meta.files.length) bub.appendChild(attList(meta.files));
    if (text) bub.appendChild(el('div', 'txt', esc(text)));
    inner.appendChild(bub);
    t.appendChild(inner);
    wrap.appendChild(t);
    return t;
  }
  var a = el('div', 'turn');
  var ans = el('div', 'ans');
  histNodes(ans, meta);
  if (text) ans.appendChild(el('div', 'body', md(text)));
  if (meta.partial) ans.appendChild(el('div', 'stopmark', 'ответ не дописан, связь оборвалась на середине'));
  a.appendChild(ans);
  wrap.appendChild(a);
  icons();
  return ans;
}

function attList(files) {
  var f = el('div', 'att');
  files.forEach(function (x) {
    if ((/\.(png|jpe?g|gif|webp|heic|heif|avif|bmp|tiff?)$/i.test(x.name || '') || x.kind === 'image') && safeUrl(x.url)) {
      var im = document.createElement('img');
      im.src = safeUrl(x.url); im.alt = x.name || '';
      f.appendChild(im);
    } else {
      var a = document.createElement('a');
      var u = safeUrl(x.url);
      if (u) a.href = u;
      a.textContent = x.name || 'файл';
      f.appendChild(a);
    }
  });
  return f;
}

function stepNode(s) {
  var d = el('details', 'step' + (s.ok === false ? ' fail' : ''));
  var sum = el('summary');
  sum.innerHTML = '<span class="ar">›</span>' + ic('terminal', 'ic') +
    '<span class="nm">' + esc(s.name) + '</span><span class="ms">' +
    (s.ok === false ? 'ошибка' : s.out ? 'готово' : 'идёт') + '</span>';
  d.appendChild(sum);
  d.appendChild(el('pre', null, esc(wrapLong(s.out || ''))));
  return d;
}

function wrapLong(t) {
  return String(t).replace(/[^\s]{80,}/g, function (m) { return m.replace(/(.{60})/g, '$1\u200b'); });
}

function scroll(force) {
  var feed = $('feed');
  if (force || feed.scrollHeight - feed.scrollTop - feed.clientHeight < 200) feed.scrollTop = feed.scrollHeight;
}

/* ход живёт на сервере: send только запускает его и сразу возвращается,
   контент приезжает по EventSource с /stream. этот транспорт сам переподключается
   и доносит Last-Event-ID, поэтому f5, обрыв связи и закрытие вкладки ничего не теряют */

function newTurnUI() {
  var box = el('div', 'turn');
  var ans = el('div', 'ans');
  var state = el('div', 'state', '<span class="bar"></span><span class="st">думает</span>');
  var steps = el('div', 'steps');
  var think = el('details', 'think');
  think.appendChild(el('summary', null, 'ход мыслей'));
  var thinkPre = el('pre');
  think.appendChild(thinkPre);
  var body = el('div', 'body');
  ans.appendChild(state); ans.appendChild(steps); ans.appendChild(think); ans.appendChild(body);
  box.appendChild(ans);
  $('wrap').appendChild(box);
  return { box: box, ans: ans, state: state, steps: steps, think: think, thinkPre: thinkPre, body: body,
           raw: '', thought: '', thinkOpen: false,
           set: function (t) { var s = state.querySelector('.st'); if (s) s.textContent = t; } };
}

function stopMark(ui, t) {
  if (ui.box.querySelector('.stopmark')) return;
  ui.box.querySelector('.ans').insertAdjacentHTML('beforeend', '<div class="stopmark">' + esc(t) + '</div>');
}

/* шаги тулов из состояния хода: рисуем с нуля, когда sse не успел их принести */
function syncSteps(ui, steps) {
  ui.steps.innerHTML = '';
  ui.steps._open = {};
  (steps || []).forEach(function (e) {
    if (e.t === 'tool') {
      var d = el('details', 'step');
      var sum = el('summary');
      sum.innerHTML = '<span class="ar">›</span>' + ic('terminal', 'ic') +
        '<span class="nm">' + esc(e.name) + '</span><span class="ms">идёт</span>';
      d.appendChild(sum);
      d.appendChild(el('pre', null, esc(JSON.stringify(e.args || {}, null, 1))));
      ui.steps.appendChild(d);
      ui.steps._open[e.name] = d;
    } else if (e.t === 'tool_done') {
      var n = ui.steps._open[e.name];
      if (n) {
        n.querySelector('.ms').textContent = (e.took != null ? e.took + ' с' : '');
        if (e.ok === false) n.classList.add('fail');
        n.querySelector('pre').textContent = wrapLong(e.out || '');
      }
    }
  });
  icons();
}

/* живой блок ответа поверх истории. пока ход идёт, живой блок — единственный источник
   правды по тексту, шагам и мыслям: историю в это время не перерисовываем, иначе
   ответ дублируется. когда ход кончился — блок снимаем и рисуем чат из базы */
function attachLive(cid, ui) {
  ui = ui || newTurnUI();
  if (S.live && S.live[cid]) return S.live[cid].ui;
  liveStream(ui, cid, function () {
    if (ui.finalized) return;
    ui.finalized = true;
    ui.box.remove();
    if (S.cid === cid) openChat(cid).catch(function () {});
    else loadChats().catch(function () {});
    updateSend();
  });
  updateSend();
  return ui;
}

/* живой блок гасим молча, когда перерисовываем чат из истории:
   иначе живой текст ляжет поверх уже сохранённого ответа и задвоится */
function dropLive(cid) {
  var l = S.live && S.live[cid];
  if (l) l.close(true);
}

/* живой ответ на экране: подписка на серверный ход этого чата.
   возвращает closure-управление; при уходе со страницы подписка закроется сама */
function liveStream(ui, cid, onEnd) {
  // одна живая подписка на чат: если уже была — молча гасим, новая получит снимок с нуля
  S.live = S.live || {};
  var prev = S.live[cid];
  if (prev) prev.close(true);
  var es = new EventSource('/api/chats/' + cid + '/stream');
  var openSteps = {};
  var ended = false, stopmark = false, sawLive = false;
  var poll = null, misses = 0, lastSeq = 0, lastSt = '', holding = true;
  function finish(silent) {
    if (ended) return;
    ended = true;
    es.close();
    if (poll) { clearInterval(poll); poll = null; }
    if (S.live[cid] === api) delete S.live[cid];
    if (!silent && onEnd) onEnd(sawLive);
  }
  var api = { close: finish, raw: '', ui: ui };

  /* страховка от обрыва sse. cloudflare регулярно роняет поток /stream, и раньше
     ответ замирал на середине до f5. теперь раз в 1.5 сек тянем состояние хода
     одним json: если стрим отстал или умер — добираем текст, мысли и шаги оттуда.
     опрос не рисует живой блок сам: он только доедает уже начатый, поэтому
     фантомов из прошлых ходов не бывает — их гасит ev.t === 'idle' */
  function startPoll() {
    if (poll) return;
    poll = setInterval(async function () {
      try {
        var r = await fetch('/api/chats/' + cid + '/turn', { cache: 'no-store' });
        if (r.status === 401) { location.href = '/'; return; }
        if (!r.ok) throw new Error('http ' + r.status);
        var st = await r.json();
        misses = 0;
      } catch (err) {
        misses++;
        // сеть моргнула пару раз — не трогаем, sse обычно доезжает сам
        if (misses < 2) return;
        if (ui.raw && ui.raw.length > lastSt.length) {
          ui.raw = lastSt; api.raw = ui.raw; ui.body.innerHTML = md(ui.raw);
        }
        ui.state.remove();
        finish();
        return;
      }
      if (st.seq && st.seq !== lastSeq) {
        lastSeq = st.seq;
        if (st.thought && !ui.thought) {
          ui.thought = st.thought;
          ui.thinkPre.textContent = st.thought.slice(-8000);
          if (!ui.thinkOpen) { ui.think.open = true; ui.thinkOpen = true; }
          ui.state.style.display = 'none';
        }
        if (st.status) { ui.set(st.status); ui.state.style.display = ''; }
        if ((st.steps || []).length > ui.steps.children.length) syncSteps(ui, st.steps);
        var s = st.answer || '';
        if (s.length > ui.raw.length) {
          ui.raw = s;
          api.raw = s;
          ui.body.innerHTML = md(s);
          lastSt = s;
          scroll();
        }
      }
      if (st.stopped && !stopmark) { stopmark = true; stopMark(ui, 'остановлено'); }
      if (st.done) {
        if (!ui.raw.trim() && !ui.body.querySelector('.err')) {
          ui.body.innerHTML = '<div class="err">ответ не пришёл. попробуй ещё раз или смени режим</div>';
        }
        ui.state.remove();
        if (!ui.thought) ui.think.remove();
        finish();
        return;
      }
      if (st.active) { ui.set(st.status || 'думает'); ui.state.style.display = ''; }
    }, 1500);
  }
  startPoll();
  ui.onText = function (t) { api.raw = t; };
  S.live[cid] = api;
  // снимок не рисуем: если ход мёртв, блок снесём без мигания
  var buffered = [];
  function apply(e) {
    // чужие события не трогают общий интерфейс: бейдж режима меняет только
    // ход ТЕКУЩЕГО открытого чата (иначе mode из фонового чата перебивал видимый)
    var visible = S.cid === cid;
    if (e.t === 'start') {
      if (visible && e.mode && window.aiThemeSet) aiThemeSet('mode', e.mode);
    }
    else if (e.t === 'status') ui.set(e.d);
    else if (e.t === 'reason') {
      ui.thought += e.d;
      ui.thinkPre.textContent = ui.thought.slice(-8000);
      if (!ui.thinkOpen) { ui.think.open = true; ui.thinkOpen = true; }
      ui.state.style.display = 'none';
    }
    else if (e.t === 'tool') {
      var node = el('details', 'step');
      var sum = el('summary');
      sum.innerHTML = '<span class="ar">›</span>' + ic('terminal', 'ic') +
        '<span class="nm">' + esc(e.name) + '</span><span class="ms">идёт</span>';
      node.appendChild(sum);
      node.appendChild(el('pre', null, esc(JSON.stringify(e.args || {}, null, 1))));
      ui.steps.appendChild(node);
      icons();
      openSteps[e.name] = node;
      ui.set(e.name);
    }
    else if (e.t === 'tool_done') {
      var n2 = openSteps[e.name];
      if (n2) {
        n2.querySelector('.ms').textContent = (e.took != null ? e.took + ' с' : '');
        if (e.ok === false) n2.classList.add('fail');
        n2.querySelector('pre').textContent = wrapLong(e.out || '');
      }
      ui.set('думает');
    }
    else if (e.t === 'attach') { ui.body.appendChild(attachNode(e)); }
    else if (e.t === 'site') { ui.body.appendChild(siteNode(e)); }
    else if (e.t === 'text') { ui.raw += e.d; api.raw = ui.raw; ui.body.innerHTML = md(ui.raw); }
    else if (e.t === 'error') {
      ui.body.insertAdjacentHTML('beforeend', '<div class="err">' + esc(e.d) + '</div>');
    }
    else if (e.t === 'stopped') { stopmark = true; stopMark(ui, 'остановлено'); }
    else if (e.t === 'idle') {
      // сервер про этот чат уже ничего не помнит: показываем что есть и перерисуемся из базы
      ui.state.remove();
      if (!ui.thought) ui.think.remove();
      finish();
      return;
    }
    else if (e.t === 'done') {
      if (visible && e.meta && e.meta.mode && window.aiThemeSet) aiThemeSet('mode', e.meta.mode);
      if (e.answer) { ui.raw = e.answer; api.raw = ui.raw; ui.body.innerHTML = md(ui.raw); }
    }
    scroll();
    if (e.t === 'end') {
      if (!sawLive && !ui.raw.trim()) {
        // подключились к уже завершённому ходу с пустым снимком: фантом, убираем
        ui.box.remove();
        finish();
        return;
      }
      if (!ui.raw.trim() && !ui.body.querySelector('.err')) {
        ui.body.innerHTML = '<div class="err">ответ не пришёл. попробуй ещё раз или смени режим</div>';
      }
      ui.state.remove();
      if (!ui.thought) ui.think.remove();
      finish();
    }
  }
  es.onmessage = function (ev) {
    var e; try { e = JSON.parse(ev.data); } catch (err) { return; }
    // live — серверный маркер «снимок кончился, ход ещё пишется».
    // end без live = ход завершился до нашего подключения: снимок старого хода
    // не рендерим вовсе (он уже в истории), блок-фантом сносим
    if (e.t === 'live') {
      sawLive = true;
      holding = false;
      var buf = buffered; buffered = [];
      buf.forEach(apply);
      return;
    }
    if (holding && e.t !== 'end' && e.t !== 'idle') { buffered.push(e); return; }
    apply(e);
  };
  es.onerror = function () { /* EventSource сам переедет; при end/idle мы закрылись сами */ };
  return { close: finish };
}

async function send() {
  var input = $('input'), text = input.value.trim();
  if ((S.live && S.live[S.cid]) || (!text && !S.files.length)) return;

  var files = S.files.slice();
  input.value = '';
  autoSize();
  S.files = [];
  renderAtt();
  updateSend();

  addMsg('user', text, { files: files.map(function (f) { return { name: f.name, url: f.url, kind: f.kind }; }) });
  scroll(true);

  var ui = newTurnUI();
  var payload = { text: text, mode: (window.aiTheme ? aiTheme().mode : 'max'),
                  files: files.map(function (f) { return { path: f.path, kind: f.kind }; }) };
  try {
    var r = await fetch('/api/chats/' + (S.cid || 0) + '/send', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (r.status === 401) { location.href = '/'; return; }
    var j = await r.json().catch(function () { return {}; });
    if (!r.ok) {
      ui.body.innerHTML = '<div class="err">' + esc(j.error || ('сервер ответил ' + r.status)) + '</div>';
      return;
    }
    if (j.chat) S.cid = j.chat;
    attachLive(S.cid, ui);
  } catch (e) {
    ui.body.innerHTML = '<div class="err">связи с сервером нет</div>';
    updateSend();
  }
}

/* если сервер сейчас пишет ответ по этому чату — открываем его и клеим живой блок.
   зовётся после загрузки страницы: так ответ не теряется при f5 и не мигает фантомом */
async function resumeTurns() {
  try {
    var d = await jget('/api/turns');
    if (!d.cids || !d.cids.length) return;
    var cid = d.cids[0];
    await openChat(cid);
  } catch (e) {}
}

async function upload(list) {
  for (var i = 0; i < list.length; i++) {
    var f = list[i];
    if (f.size > 64 * 1024 * 1024) { note('больше 64мб не влезет'); continue; }
    var fd = new FormData();
    fd.append('file', f, f.name);
    try {
      var r = await fetch('/api/upload', { method: 'POST', body: fd });
      if (r.status === 401) { location.href = '/'; return; }
      var d = await r.json().catch(function () { return {}; });
      if (!r.ok || d.error) { note(d.error || ('сервер ответил ' + r.status)); continue; }
      var kind = d.kind;
      if (kind !== 'image' && /\.(png|jpe?g|gif|webp|bmp|heic|heif|avif|tiff?)$/i.test(d.name || '')) kind = 'image';
      S.files.push({ name: d.name, path: d.path, kind: kind, url: d.url });
    } catch (e) { note('не загрузилось'); }
  }
  renderAtt();
  updateSend();
}

function renderAtt() {
  var box = $('att');
  box.innerHTML = '';
  S.files.forEach(function (f, i) {
    var it = el('div', 'it');
    if (f.kind === 'image') {
      var im = document.createElement('img');
      im.src = f.url;
      it.appendChild(im);
    }
    it.appendChild(el('span', null, esc(f.name.length > 24 ? f.name.slice(0, 22) + '…' : f.name)));
    var x = el('button', null, '×');
    x.onclick = function () { S.files.splice(i, 1); renderAtt(); updateSend(); };
    it.appendChild(x);
    box.appendChild(it);
  });
}

function setMode(m) {
  if (!m) return;
  aiThemeSet('mode', m);
  fetch('/api/me/mode', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode: m })
  }).catch(function () {});
  if (S.cid) {
    fetch('/api/chats/' + S.cid + '/mode', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode: m })
    }).catch(function () {});
  }
  var lb = window.__modeLabel || {};
  note('режим: ' + (lb[m] || m));
  accLabels();
}

function accLabels() {
  var T = window.aiTheme ? aiTheme() : {};
  var m = $('acc-model-cur');
  if (m) {
    var n = (window.__modelName || {})[T.model || ''];
    m.textContent = T.model ? (n || T.model) : 'как в режиме';
  }
}

function histNodes(av, meta) {
  meta = meta || {};
  av.appendChild(stepList(meta.steps || []));
  av.appendChild(thinkBox(meta.thought || ''));
  (meta.attached || []).forEach(function (a) { av.appendChild(attachNode(a)); });
  (meta.sites || []).forEach(function (x) { av.appendChild(siteNode(x)); });
}

function stepList(steps) {
  var box = el('div', 'steps');
  (steps || []).forEach(function (s) { if (s && s.t === 'tool') box.appendChild(stepNode(s)); });
  return box;
}

function thinkBox(text) {
  var d = el('details', 'think');
  d.appendChild(el('summary', null, 'ход мыслей'));
  d.appendChild(el('pre', null, esc(text)));
  return d;
}

function safeUrl(u) {
  var t = String(u || '').trim();
  return /^\/(?!\/)/.test(t) || /^https?:\/\//i.test(t) ? t : '';
}

function attachNode(e) {
  var box = el('div', 'attach');
  var u = safeUrl(e.url);
  if (e.kind === 'image' && u) {
    var th = el('button', 'th');
    th.type = 'button';
    th.title = 'открыть на весь экран';
    var im = document.createElement('img');
    im.src = u; im.alt = e.name || '';
    im.loading = 'lazy';
    th.appendChild(im);
    th.onclick = function () { lightbox(u, e.name || ''); };
    box.appendChild(th);
  }
  var a = el('a', null, esc(e.name || 'файл'));
  if (!safeUrl(e.url)) { a.removeAttribute('href'); } else
  a.href = e.url; a.target = '_blank'; a.rel = 'noopener';
  box.appendChild(a);
  if (e.caption) box.appendChild(el('span', 'cap', esc(e.caption)));
  return box;
}

function lightbox(url, name) {
  var box = el('div', 'lb on');
  var im = document.createElement('img');
  im.src = url; im.alt = name || '';
  var x = el('div', 'x');
  x.innerHTML = '<i data-lucide="x"></i>';
  x.onclick = function (ev) { ev.stopPropagation(); close(); };
  var op = el('a', 'op', 'открыть в новой вкладке');
  op.href = url; op.target = '_blank'; op.rel = 'noopener';
  op.onclick = function (ev) { ev.stopPropagation(); };
  var pic = el('div', 'pic');
  pic.appendChild(im);
  box.appendChild(pic); box.appendChild(x); box.appendChild(op);
  box.onclick = function () { close(); };
  document.body.appendChild(box);
  icons();
  function onKey(ev) { if (ev.key === 'Escape') close(); }
  function close() {
    document.removeEventListener('keydown', onKey);
    if (box.parentNode) box.parentNode.removeChild(box);
  }
  document.addEventListener('keydown', onKey);
}

function siteNode(e) {
  var box = el('div', 'site');
  box.appendChild(el('b', null, esc(e.slug || 'страница')));
  var a = el('a', null, esc(e.url || ''));
  if (safeUrl(e.url)) { a.href = safeUrl(e.url); }
  a.target = '_blank'; a.rel = 'noopener';
  box.appendChild(a);
  return box;
}

var _noteT = null;
function note(t) {
  var h = $('hint');
  if (!h) return;
  h.textContent = t;
  if (_noteT) clearTimeout(_noteT);
  _noteT = setTimeout(function () { h.textContent = ''; _noteT = null; }, 4000);
}
function updateSend() {
  var busy = !!(S.live && S.live[S.cid]);
  var can = !!(($('input').value || '').trim() || S.files.length);
  $('send').disabled = busy || !can;
  var row = document.querySelector('.crow');
  if (row) row.setAttribute('data-busy', busy ? '1' : '0');
}

function stopTurn() {
  if (!S.cid) return;
  if (!(S.live && S.live[S.cid])) return;
  fetch('/api/chats/' + S.cid + '/stop', { method: 'POST' }).catch(function () {});
  note('останавливаю');
}
function autoSize() { var t = $('input'); t.style.height = 'auto'; t.style.height = Math.min(t.scrollHeight, 200) + 'px'; }

function hexToRgb(h) {
  var m = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(h || '');
  return m ? [parseInt(m[1], 16), parseInt(m[2], 16), parseInt(m[3], 16)] : [255, 46, 154];
}

function drawShape(ctx, d, shape, colstr) {
  var r = d.r, x = d.x, y = d.y;
  ctx.fillStyle = colstr;
  ctx.strokeStyle = colstr;
  if (shape === 'square') {
    ctx.fillRect(x - r, y - r, r * 2, r * 2);
  } else if (shape === 'dash') {
    ctx.save();
    ctx.translate(x, y);
    ctx.rotate(d.tw);
    ctx.fillRect(-r * 2.2, -r * .45, r * 4.4, r * .9);
    ctx.restore();
  } else if (shape === 'cross') {
    ctx.lineWidth = Math.max(1, r * .75);
    ctx.beginPath();
    ctx.moveTo(x - r * 1.6, y - r * 1.6); ctx.lineTo(x + r * 1.6, y + r * 1.6);
    ctx.moveTo(x + r * 1.6, y - r * 1.6); ctx.lineTo(x - r * 1.6, y + r * 1.6);
    ctx.stroke();
  } else if (shape === 'ring') {
    ctx.lineWidth = Math.max(1, r * .7);
    ctx.beginPath();
    ctx.arc(x, y, r * 1.5, 0, 6.283);
    ctx.stroke();
  } else if (shape === 'heart') {
    var s = r * 1.9;
    ctx.save();
    ctx.translate(x, y);
    ctx.beginPath();
    ctx.moveTo(0, s * .72);
    ctx.bezierCurveTo(-s * 1.25, -s * .35, -s * .5, -s * 1.15, 0, -s * .38);
    ctx.bezierCurveTo(s * .5, -s * 1.15, s * 1.25, -s * .35, 0, s * .72);
    ctx.closePath();
    ctx.fill();
    ctx.restore();
  } else if (shape === 'star') {
    ctx.save();
    ctx.translate(x, y);
    ctx.rotate(d.tw);
    ctx.beginPath();
    for (var i = 0; i < 8; i++) {
      var ang = i * Math.PI / 4;
      var rad = (i % 2 === 0) ? r * 2.1 : r * .75;
      var px = Math.cos(ang) * rad, py = Math.sin(ang) * rad;
      if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
    }
    ctx.closePath();
    ctx.fill();
    ctx.restore();
  } else {
    ctx.beginPath();
    ctx.arc(x, y, r, 0, 6.283);
    ctx.fill();
  }
}

function startParticles() {
  var cv = $('particles');
  if (!cv) return;
  if (window.__stopParticles) { window.__stopParticles(); window.__stopParticles = null; }
  var T = (window.aiTheme ? aiTheme() : { dots: true, dotsN: 34, fade: true, ac: '#ff2e9a', dotsC: '' });
  var ctx = cv.getContext('2d');
  var dpr = Math.min(window.devicePixelRatio || 1, 2);
  var w = 0, h = 0, ps = [], alive = true;
  var N = Math.max(0, parseInt(T.dotsN, 10) || 0);
  var fade = T.fade !== false;
  var col = hexToRgb(T.dotsC || T.ac);

  function size() { w = cv.width = Math.floor(innerWidth * dpr); h = cv.height = Math.floor(innerHeight * dpr); }
  function spawn() {
    ps = [];
    for (var i = 0; i < N; i++) {
      var sc = Math.max(.2, (parseInt(T.dotsSize, 10) || 100) / 100);
      ps.push({ x: Math.random() * w, y: Math.random() * h,
        vx: (Math.random() - .5) * .16 * dpr, vy: (Math.random() - .5) * .16 * dpr,
        r: (Math.random() * 1.5 + .7) * dpr * sc, a: Math.random() * .35 + .22,
        tw: Math.random() * 6.283, ts: .008 + Math.random() * .012 });
    }
  }
  function clear() { ctx.clearRect(0, 0, w, h); }
  size(); spawn();
  var onResize = function () { size(); spawn(); };
  addEventListener('resize', onResize, { passive: true });

  window.__stopParticles = function () {
    alive = false;
    removeEventListener('resize', onResize);
    clear();
  };
  window.__particlesNeedRestart = function () { startParticles(); };

  if (!T.dots || !N || window.matchMedia('(prefers-reduced-motion: reduce)').matches) { clear(); return; }

  (function tick() {
    if (!alive) return;
    clear();
    for (var i = 0; i < ps.length; i++) {
      var d = ps[i];
      d.x += d.vx; d.y += d.vy; d.tw += d.ts;
      if (d.x < -12) d.x = w + 12; if (d.x > w + 12) d.x = -12;
      if (d.y < -12) d.y = h + 12; if (d.y > h + 12) d.y = -12;
      var k = fade ? (.65 + .35 * Math.sin(d.tw)) : 1;
      var op = Math.max(0, Math.min(1, (parseInt(T.dotsOp, 10) || 100) / 100));
      var colstr = 'rgba(' + col[0] + ',' + col[1] + ',' + col[2] + ',' + (d.a * k * op).toFixed(3) + ')';
      drawShape(ctx, d, T.dotsShape, colstr);
    }
    requestAnimationFrame(tick);
  })();
}

function initSettings() {
  var sheet = $('sheet');
  if (!sheet) return;
  function close() { sheet.classList.remove('on'); }
  // все секции выбора закрыты при каждом открытии настроек
  var providerModels = { ordinary: [], cvc: [], cline: [], clineFree: [] };
  var providerTargets = { ordinary: 'models', cvc: 'models-cvc', cline: 'models-cline', clineFree: 'models-cline-free' };
  function modelButton(m) {
    var b = el('button', 'm' + (m.id === ((window.aiTheme ? aiTheme().model : '') || '') ? ' on' : '') + (m.rec ? ' rec' : ''));
    var pr = m.price ? '<em class="pr">' + esc(m.price) + '</em>' : (m.mult ? '<em class="pr">×' + m.mult + '</em>' : '');
    b.innerHTML = '<i></i><span class="t"><b>' + esc(m.name || m.id) + (m.rec ? '<em class="rc">рекомендуется</em>' : '') + pr + '</b><small>' + esc(m.note || '') + '</small></span>';
    b.onclick = function () {
      aiThemeSet('model', m.id);
      fetch('/api/me/model', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ model: m.id }) }).catch(function () {});
      Array.prototype.forEach.call(document.querySelectorAll('#models .m, #models-exp .m, #models-free .m, #models-cvc .m, #models-cline .m, #models-cline-free .m'), function (x) { x.classList.remove('on'); });
      b.classList.add('on');
      note('модель: ' + (m.name || m.id));
      accLabels();
    };
    return b;
  }
  function renderProvider(kind) {
    var target = $(providerTargets[kind]);
    if (!target || target.childElementCount) return;
    providerModels[kind].forEach(function (m) { target.appendChild(modelButton(m)); });
    if (kind === 'cline') {
      var freeTarget = $(providerTargets.clineFree);
      if (freeTarget && !freeTarget.childElementCount) providerModels.clineFree.forEach(function (m) { freeTarget.appendChild(modelButton(m)); });
    }
    if (kind === 'ordinary') {
      var auto = el('button', 'm' + ((window.aiTheme ? aiTheme().model : '') ? '' : ' on'));
      auto.innerHTML = '<i></i><span class="t"><b>как в режиме</b><small>модель берётся из мощности агента</small></span>';
      auto.onclick = function () {
        aiThemeSet('model', '');
        fetch('/api/me/model', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ model: '' }) }).catch(function () {});
        Array.prototype.forEach.call(document.querySelectorAll('#models .m, #models-cvc .m, #models-cline .m, #models-cline-free .m'), function (x) { x.classList.remove('on'); });
        auto.classList.add('on');
        note('модель от режима');
        accLabels();
      };
      target.appendChild(auto);
    }
  }
  var modelSections = [['acc-model', 'acc-model-body'], ['acc-ordinary', 'acc-ordinary-body'], ['acc-cvc', 'acc-cvc-body'], ['acc-cline', 'acc-cline-body']];
  var providerKinds = { 'acc-ordinary': 'ordinary', 'acc-cvc': 'cvc', 'acc-cline': 'cline' };
  function resetSections() {
    modelSections.forEach(function (p) {
      var head = $(p[0]), body = $(p[1]);
      if (!head || !body) return;
      body.hidden = true;
      body.style.display = 'none';
      head.classList.remove('on');
      head.setAttribute('aria-expanded', 'false');
    });
    Object.keys(providerTargets).forEach(function (kind) {
      var target = $(providerTargets[kind]);
      if (target) target.innerHTML = '';
    });
  }
  modelSections.forEach(function (p) {
    var head = $(p[0]), body = $(p[1]);
    if (!head || !body) return;
    head.onclick = function () {
      var kind = providerKinds[p[0]];
      if (kind) renderProvider(kind);
      var open = body.hidden || body.style.display === 'none';
      body.hidden = !open;
      body.style.display = open ? '' : 'none';
      head.classList.toggle('on', open);
      head.setAttribute('aria-expanded', open ? 'true' : 'false');
      icons();
    };
  });
  resetSections();
  $('settings').onclick = function () {
    var open = !sheet.classList.contains('on');
    if (open) resetSections();
    sheet.classList.toggle('on', open);
    if (open) {
      icons();
      if (window.aiThemeApply) aiThemeApply();
    }
  };
  $('close-set').onclick = close;
  sheet.addEventListener('click', function (e) { if (e.target === sheet) close(); });

  function bind(id, key, disp) {
    var e2 = $(id); if (!e2) return;
    e2.addEventListener('input', function () {
      var v = parseInt(e2.value, 10);
      var out = $(id + '-v'); if (out) out.textContent = disp ? disp(v) : v;
      aiThemeSet(key, v);
    });
  }
  bind('fs', 'fs');
  bind('lh', 'lh', function (v) { return (v / 10).toFixed(1); });
  bind('dens', 'dens');
  bind('dots-n', 'dotsN');
  bind('dots-a', 'dotsA');
  bind('wall-dim', 'wallDim');

  [['fx-dots', 'dots'], ['fx-fade', 'fade'], ['fx-sel', 'sel']].forEach(function (p) {
    var e2 = $(p[0]); if (!e2) return;
    e2.addEventListener('change', function () { aiThemeSet(p[1], e2.checked); });
  });

  [['custom-ac', 'ac'], ['sel-color', 'selColor'], ['dots-color', 'dotsC'],
   ['bg-chat', 'bgChat'], ['bg-panel', 'bgPanel'], ['bg-field', 'bgField']].forEach(function (p) {
    var e2 = $(p[0]); if (!e2) return;
    e2.addEventListener('input', function () { aiThemeSet(p[1], e2.value); });
  });

  if ($('reset-ac')) $('reset-ac').onclick = function () { aiThemeSet('ac', '#ff2e9a'); };
  if ($('sel-auto')) $('sel-auto').onclick = function () { aiThemeSet('selColor', ''); };
  if ($('dots-auto')) $('dots-auto').onclick = function () { aiThemeSet('dotsC', ''); };
  var sh = $('dots-shape');
  if (sh) sh.addEventListener('change', function () { aiThemeSet('dotsShape', sh.value); });
  var si = $('dots-size');
  if (si) si.addEventListener('input', function () { aiThemeSet('dotsSize', si.value); });
  var op = $('dots-op');
  if (op) op.addEventListener('input', function () { aiThemeSet('dotsOp', op.value); });
  Array.prototype.forEach.call(document.querySelectorAll('#modes .mode'), function (b) {
    b.onclick = function () { setMode(b.dataset.m); };
  });
  jget('/api/models').then(function (d) {
    var box = $('models');
    if (!box) return;
    box.innerHTML = '';
    var names = {};
    (d.models || []).forEach(function (m) { names[m.id] = m.name || m.id; });
    window.__modelName = names;
    var modes = d.modes || {};
    Array.prototype.forEach.call(document.querySelectorAll('#modes .mode'), function (b) {
      var m = modes[b.dataset.m];
      if (!m) return;
      var t = b.querySelector('b'), s = b.querySelector('span');
      if (t && m.label) t.textContent = m.label;
      if (s && m.hint) s.textContent = m.hint;
    });
    (d.models || []).forEach(function (m) {
      var kind = m.provider === 'cvc' ? 'cvc' : m.provider === 'cline' ? (m.tier === 'cline-free' ? 'clineFree' : 'cline') : 'ordinary';
      providerModels[kind].push(m);
    });
    var ordinaryN = providerModels.ordinary.length;
    var cvcN = providerModels.cvc.length;
    var clineN = providerModels.cline.length;
    var clineFreeN = providerModels.clineFree.length;
    var ordinaryWrap = $('ordinarywrap');
    if (ordinaryWrap && ordinaryN) {
      ordinaryWrap.hidden = false;
      var oc = $('acc-ordinary-cur');
      if (oc) oc.textContent = ordinaryN + ' моделей';
    }
    var cvcWrap = $('cvcwrap');
    if (cvcWrap && cvcN) {
      cvcWrap.hidden = false;
      var cc = $('acc-cvc-cur');
      if (cc) cc.textContent = cvcN + ' моделей';
    }
    var clineWrap = $('clinewrap');
    if (clineWrap && (clineN || clineFreeN)) {
      clineWrap.hidden = false;
      var lc = $('acc-cline-cur');
      if (lc) lc.textContent = (clineN + clineFreeN) + ' моделей';
    }
    resetSections();
    accLabels();
  }).catch(function () {});
  var mb = $('modebadge');
  if (mb) mb.onclick = function () {
    var order = ['ultra', 'low', 'mid', 'max'];
    var cur = (window.aiTheme ? aiTheme().mode : 'max');
    setMode(order[(order.indexOf(cur) + 1) % order.length]);
  };
  if ($('bg-reset')) $('bg-reset').onclick = function () {
    aiThemeSet('bgChat', '#0a0a0c'); aiThemeSet('bgPanel', '#0e0e13'); aiThemeSet('bgField', '#101015');
  };

  var wf = $('wall-file');
  if (wf) wf.addEventListener('change', function (e) {
    var f = e.target.files && e.target.files[0];
    if (!f) return;
    if (f.size > 4 * 1024 * 1024) { alert('картинка больше 4мб, возьми поменьше'); e.target.value = ''; return; }
    var rd = new FileReader();
    rd.onload = function () { aiThemeSet('wall', rd.result); };
    rd.readAsDataURL(f);
    e.target.value = '';
  });
  if ($('wall-clear')) $('wall-clear').onclick = function () { aiThemeSet('wall', ''); };
  if ($('reset-all')) $('reset-all').onclick = function () { aiThemeReset(); };
}

function fmtTok(n) {
  n = n || 0;
  if (n >= 1e6) return (n / 1e6).toFixed(1) + 'м';
  if (n >= 1e3) return (n / 1e3).toFixed(0) + 'к';
  return String(n);
}

function initAdmin() {
  var adm = $('adm');
  if (!adm) return;
  function close() { adm.classList.remove('on'); }

  async function loadOv() {
    var d = await jget('/api/admin/overview');
    var st = d.stats || {}, disk = d.disk || {}, mem = d.mem_mb || {};
    var w = disk.percent > 85 ? ' warn' : '';
    $('adm-ov').innerHTML =
      '<div class="c' + w + '"><b>' + fmtTok(st.tokens) + '</b><small>токенов</small></div>' +
      '<div class="c"><b>' + (st.messages || 0) + '</b><small>сообщений</small></div>' +
      '<div class="c"><b>' + (st.users || 0) + '</b><small>аккаунтов</small></div>' +
      '<div class="c' + w + '"><b>' + disk.free_gb + 'г</b><small>свободно, занято ' + disk.percent + '%</small></div>' +
      '<div class="c"><b>' + (mem.used || 0) + '/' + (mem.total || 0) + '</b><small>память, мб</small></div>' +
      '<div class="c"><b>' + (d.load || []).join(' ') + '</b><small>нагрузка</small></div>' +
      '<div class="c"><b>' + ((d.services || {})['ai-agent'] || '?') + '</b><small>агент</small></div>' +
      '<div class="c"><b>' + ((d.services || {}).nginx || '?') + '</b><small>nginx</small></div>';
  }

  async function loadUsers() {
    var d = await jget('/api/admin/users');
    var box = $('adm-users');
    box.innerHTML = '';
    (d.users || []).forEach(function (u) {
      var n = el('div', 'user');
      n.appendChild(el('div', 'who',
        '<div class="lg">' + esc(u.pname || u.login) + (u.is_owner ? ' <span class="tagd">владелец</span>' : '') + '</div>' +
        '<div class="mt">' + esc(u.login) + ' · чатов ' + (u.chats || 0) + '</div>' +
        '<div class="ustat"><span>сообщений ' + (u.total_msgs || 0) + '</span><span>токенов ' + fmtTok(u.tokens) + '</span></div>'));
      var acts = el('div', 'acts');
      var pw = el('button', null, 'пароль');
      pw.onclick = async function () {
        var np = prompt('новый пароль для ' + u.login + ' (минимум 6 символов)');
        if (!np) return;
        var r = await fetch('/api/admin/users/' + u.id + '/password', {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ password: np })
        });
        var j = await r.json().catch(function () { return {}; });
        alert(r.ok && !j.error ? 'пароль сменён' : (j.error || ('сервер ответил ' + r.status)));
      };
      acts.appendChild(pw);
      if (u.id !== (S.me && S.me.id) && !u.disabled) {
        var go = el('button', null, 'зайти');
        go.onclick = async function () {
          var r = await fetch('/api/admin/switch/' + u.id, { method: 'POST' });
          var j = await r.json().catch(function () { return {}; });
          if (!r.ok || j.error) { alert(j.error || ('сервер ответил ' + r.status)); return; }
          location.href = '/';
        };
        acts.appendChild(go);
      }
      if (!u.is_owner) {
        var del = el('button', 'dz', 'удалить');
        del.onclick = async function () {
          if (!confirm('удалить ' + u.login + ' и все его чаты?')) return;
          var r = await fetch('/api/admin/users/' + u.id, { method: 'DELETE' });
          var j = await r.json().catch(function () { return {}; });
          if (!r.ok || j.error) { alert(j.error || ('сервер ответил ' + r.status)); return; }
          loadUsers(); loadOv();
        };
        acts.appendChild(del);
      }
      n.appendChild(acts);
      box.appendChild(n);
    });
    if (!(d.users || []).length) box.innerHTML = '<div class="mt">пока только ты</div>';
  }

  $('admin').onclick = function () { adm.classList.add('on'); icons(); loadOv().catch(function () {}); loadUsers().catch(function () {}); };
  $('close-adm').onclick = close;
  adm.addEventListener('click', function (e) { if (e.target === adm) close(); });

  if ($('nu-add')) $('nu-add').onclick = async function () {
    var bad = $('nu-bad'); bad.textContent = '';
    var body = { login: $('nu-login').value.trim(), password: $('nu-pass').value, pname: $('nu-name').value.trim() };
    if (!body.login || !body.password) { bad.textContent = 'логин и пароль обязательны'; return; }
    var r = await fetch('/api/admin/users', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
    });
    var j = await r.json().catch(function () { return {}; });
    if (!r.ok || j.error) { bad.style.color = ''; bad.textContent = j.error || ('сервер ответил ' + r.status); return; }
    bad.style.color = 'var(--ok)';
    bad.textContent = 'аккаунт создан';
    $('nu-login').value = ''; $('nu-pass').value = ''; $('nu-name').value = '';
    loadUsers(); loadOv();
  };
}

document.addEventListener('DOMContentLoaded', function () {
  icons();
  var _crow = document.querySelector('.crow');
  if (_crow) _crow.setAttribute('data-busy', '0');
  initSettings();
  initAdmin();
  startParticles();

  jget('/api/me').then(function (me) {
    S.me = me;
    if (me.name) { var w = $('who'); if (w) w.textContent = me.name; }
    if (me.impersonated) {
      var box = $('imp');
      if (box) {
        box.hidden = false;
        var t = $('imp-t');
        if (t) t.textContent = 'вы как ' + (me.name || me.user) + ' · вернуться к ' + (me.back || 'себе');
      }
    }
    if (me.mode && window.aiThemeSet) aiThemeSet('mode', me.mode);
    if (window.aiThemeSet && typeof me.model === 'string') aiThemeSet('model', me.model);
    accLabels();
  }).catch(function () {});

  $('new').onclick = newChat;
  $('send').onclick = send;
  if ($('stop')) $('stop').onclick = stopTurn;
  (function initSidebar() {
    var app = $('app'), side = $('sidebar'), toggle = $('sidebar-toggle'), opener = $('burger');
    var main = app.querySelector('.main'), chats = $('chats'), del = $('delchat');
    var mobile = window.matchMedia('(max-width:760px)');
    var collapsed = false;
    try { collapsed = localStorage.getItem('ai_sidebar_collapsed') === '1'; } catch (_) {}
    function sync() {
      var drawer = mobile.matches && app.classList.contains('nav');
      var rail = !mobile.matches && collapsed;
      var hidden = mobile.matches && !drawer;
      main.inert = drawer;
      side.inert = hidden;
      if (hidden && side.contains(document.activeElement)) opener.focus();
      if (!mobile.matches && document.activeElement === opener) toggle.focus();
      if (rail && (chats.contains(document.activeElement) || document.activeElement === del)) toggle.focus();
      if (drawer && !side.contains(document.activeElement) && !document.querySelector('.sheet.on')) toggle.focus();
      if (app.classList.contains('side-collapsed') !== rail) app.classList.toggle('side-collapsed', rail);
      chats.inert = rail;
      side.setAttribute('aria-hidden', String(hidden));
      toggle.setAttribute('aria-expanded', String(mobile.matches ? drawer : !rail));
      opener.setAttribute('aria-expanded', String(drawer));
      var label = mobile.matches ? 'закрыть панель' : rail ? 'развернуть панель' : 'свернуть панель';
      toggle.setAttribute('aria-label', label);
      toggle.title = label + (mobile.matches ? '' : ' · alt+b');
    }
    function flip() {
      if (mobile.matches) app.classList.toggle('nav');
      else {
        collapsed = !collapsed;
        try { localStorage.setItem('ai_sidebar_collapsed', collapsed ? '1' : '0'); } catch (_) {}
      }
      sync();
    }
    toggle.onclick = flip;
    opener.onclick = flip;
    $('new').onclick = function () { newChat(); sync(); $('input').focus(); };
    mobile.addEventListener('change', function () { app.classList.remove('nav'); sync(); });
    new MutationObserver(sync).observe(app, {attributes:true, attributeFilter:['class']});
    document.addEventListener('keydown', function (e) {
      if (e.altKey && !e.ctrlKey && !e.metaKey && !e.shiftKey && e.code === 'KeyB' && !e.repeat && !e.isComposing) {
        if (document.querySelector('.sheet.on, dialog[open]')) return;
        e.preventDefault(); flip();
      }
      if (e.key === 'Escape' && mobile.matches && app.classList.contains('nav') && !document.querySelector('.sheet.on, dialog[open]')) {
        app.classList.remove('nav'); sync(); opener.focus();
      }
    });
    sync();
  })();
  $('delchat').onclick = async function () {
    if (!S.cid) return;
    var r = await fetch('/api/chats/' + S.cid, { method: 'DELETE' });
    if (!r.ok) { note('не удалилось'); return; }
    S.cid = 0; reset(); await loadChats();
  };
  $('logout').onclick = async function () { await fetch('/api/logout', { method: 'POST' }); location.href = '/'; };
  if ($('imp-back')) $('imp-back').onclick = async function () {
    await fetch('/api/admin/back', { method: 'POST' });
    location.href = '/';
  };
  var scrim = $('scrim');
  if (scrim) scrim.addEventListener('click', function () { $('app').classList.remove('nav'); });

  var ta = $('input');
  ta.addEventListener('input', function () { autoSize(); updateSend(); });
  ta.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey && !e.ctrlKey && !e.metaKey) { e.preventDefault(); send(); }
  });
  ta.addEventListener('paste', function (e) {
    var items = (e.clipboardData && e.clipboardData.files) || [];
    if (items.length) { e.preventDefault(); upload(Array.prototype.slice.call(items)); }
  });
  document.addEventListener('keydown', function (e) {
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    var a = document.activeElement;
    if (a && (a.closest('button,a,input,textarea,select,[role="button"]') || a.isContentEditable)) return;
    if ($('app').classList.contains('nav')) return;
    if ($('sheet') && $('sheet').classList.contains('on')) return;
    if ($('adm') && $('adm').classList.contains('on')) return;
    if (e.key === 'Escape') { $('app').classList.remove('nav'); return; }
    if (e.key === 'Enter') { e.preventDefault(); send(); return; }
    if (e.key === 'Backspace') { e.preventDefault(); ta.focus(); ta.value = ta.value.slice(0, -1); autoSize(); updateSend(); return; }
    if (e.key.length === 1) { e.preventDefault(); ta.focus(); ta.value += e.key; autoSize(); updateSend(); }
  });

  var f = $('file');
  if (f) f.addEventListener('change', function (e) { upload(Array.prototype.slice.call(e.target.files)); e.target.value = ''; });

  var depth = 0;
  window.addEventListener('dragenter', function (e) { e.preventDefault(); depth++; if ($('drop')) $('drop').classList.add('on'); });
  window.addEventListener('dragover', function (e) { e.preventDefault(); });
  window.addEventListener('dragleave', function () { depth--; if (depth <= 0) { depth = 0; if ($('drop')) $('drop').classList.remove('on'); } });
  window.addEventListener('drop', function (e) {
    e.preventDefault(); depth = 0; if ($('drop')) $('drop').classList.remove('on');
    if (e.dataTransfer && e.dataTransfer.files.length) upload(Array.prototype.slice.call(e.dataTransfer.files));
  });

  loadChats().then(function () {
    jget('/api/turns').then(function (t) {
      var cid = (t.cids || [])[0];
      if (cid && (!S.cid || S.cid === cid)) openChat(cid).catch(function () {});
    }).catch(function () {});
  }).catch(function () {});

  if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(function () {});
});
