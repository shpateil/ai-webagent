(function () {
  var KEY = 'ai_theme_v2';

  var DEF = {
    ac: '#ff2e9a',
    bgChat: '#0a0a0c',
    bgPanel: '#0e0e13',
    bgField: '#101015',
    wall: '',
    wallDim: 55,
    dots: true,
    dotsN: 34,
    dotsShape: 'circle',   /* circle | square | dash | cross | ring */
    dotsA: 85,
    dotsSize: 100,
    dotsOp: 100,
    fade: true,
    fs: 14,
    lh: 16,
    dens: 100,
    sel: true,
    selColor: '',
    mode: 'max',
    model: '',
    dotsSize: 100,
    dotsOp: 100,
    dotsShape: 'circle',
    dotsC: ''
  };

  var PRESETS = ['#ff2e9a', '#ff1f8f', '#e91e63', '#ff4d6d', '#c026d3', '#8b5cf6', '#3b82f6',
                 '#06b6d4', '#10b981', '#22c55e', '#eab308', '#f97316', '#ef4444', '#f43f5e',
                 '#94a3b8', '#f2f2f4'];

  function rgb(h) {
    var m = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(h || '');
    return m ? [parseInt(m[1], 16), parseInt(m[2], 16), parseInt(m[3], 16)] : [255, 46, 154];
  }
  function rgba(h, a) { var c = rgb(h); return 'rgba(' + c[0] + ',' + c[1] + ',' + c[2] + ',' + a + ')'; }
  function mix(h, target, k) {
    var a = rgb(h), b = rgb(target);
    return 'rgb(' + a.map(function (v, i) { return Math.round(v * (1 - k) + b[i] * k); }).join(',') + ')';
  }

  var T = {};
  Object.keys(DEF).forEach(function (k) { T[k] = DEF[k]; });
  try {
    var saved = JSON.parse(localStorage.getItem(KEY) || '{}');
    Object.keys(DEF).forEach(function (k) { if (saved[k] !== undefined) T[k] = saved[k]; });
  } catch (e) {}
  function save() { try { localStorage.setItem(KEY, JSON.stringify(T)); } catch (e) {} }

  function vars() {
    var o = {
      '--ac': T.ac,
      '--ac-line': rgba(T.ac, .42),
      '--ac-soft': rgba(T.ac, .10),
      '--bg': T.bgChat,
      '--p': T.bgPanel,
      '--p2': T.bgField,
      '--sel': T.sel ? (T.selColor || T.ac) : 'transparent',
      '--ui-fs': T.fs + 'px',
      '--ui-lh': (T.lh / 10).toFixed(2),
      '--ui-dens': (T.dens / 100).toFixed(2),
      '--wall-op': T.wall ? '1' : '0',
      '--wall-dim': (T.wallDim / 100).toFixed(2),
      '--dots-op': T.dots ? (T.dotsA / 100).toFixed(2) : '0'
    };
    var w = !!T.wall;
    o['--side-bg'] = w ? rgba(T.bgPanel, .86) : T.bgPanel;
    o['--box-bg'] = w ? rgba(T.bgField, .82) : T.bgField;
    o['--bubble-bg'] = w ? rgba(T.bgField, .88) : T.bgField;
    o['--code-bg'] = T.bgField;
    return o;
  }

  function apply() {
    if (!document.documentElement) return;
    var v = vars();
    var targets = [document.documentElement];
    if (document.body) targets.push(document.body);
    targets.forEach(function (el) {
      Object.keys(v).forEach(function (k) { el.style.setProperty(k, v[k]); });
    });

    var wall = document.getElementById('wall');
    if (wall) {
      wall.style.backgroundImage = T.wall ? 'url("' + T.wall + '")' : 'none';
      wall.style.backgroundColor = T.wall ? 'transparent' : T.bgChat;
    }
    var cv = document.getElementById('particles');
    if (cv) cv.style.display = T.dots ? '' : 'none';

    var q = function (id) { return document.getElementById(id); };
    if (q('fs')) { q('fs').value = T.fs; q('fs-v').textContent = T.fs; }
    if (q('lh')) { q('lh').value = T.lh; q('lh-v').textContent = (T.lh / 10).toFixed(1); }
    if (q('dens')) { q('dens').value = T.dens; q('dens-v').textContent = T.dens; }
    if (q('dots-n')) { q('dots-n').value = T.dotsN; q('dots-n-v').textContent = T.dotsN; }
    if (q('dots-shape')) q('dots-shape').value = T.dotsShape;
    var MODE_LABEL = { ultra: 'ультра лоу', low: 'лоу', mid: 'медиум', max: 'макс' };
    Array.prototype.forEach.call(document.querySelectorAll('#modes .mode'), function (b) {
      b.classList.toggle('on', b.dataset.m === T.mode);
    });
    var mb = q('modebadge');
    if (mb) mb.textContent = MODE_LABEL[T.mode] || T.mode;
    window.__modeLabel = MODE_LABEL;
    if (q('dots-a')) { q('dots-a').value = T.dotsA; q('dots-a-v').textContent = T.dotsA; }
    if (q('dots-size')) { q('dots-size').value = T.dotsSize; q('dots-size-v').textContent = T.dotsSize; }
    if (q('dots-op')) { q('dots-op').value = T.dotsOp; q('dots-op-v').textContent = T.dotsOp; }
    if (q('wall-dim')) { q('wall-dim').value = T.wallDim; q('wall-dim-v').textContent = T.wallDim; }
    if (q('fx-dots')) q('fx-dots').checked = T.dots;
    if (q('fx-fade')) q('fx-fade').checked = T.fade;
    if (q('fx-sel')) q('fx-sel').checked = T.sel;
    if (q('sel-color')) q('sel-color').value = T.selColor || T.ac;
    if (q('sel-label')) q('sel-label').textContent = T.selColor ? 'свой цвет' : 'как акцент';
    if (q('custom-ac')) q('custom-ac').value = T.ac;
    if (q('dots-color')) q('dots-color').value = T.dotsC || T.ac;
    if (q('bg-chat')) q('bg-chat').value = T.bgChat;
    if (q('bg-panel')) q('bg-panel').value = T.bgPanel;
    if (q('bg-field')) q('bg-field').value = T.bgField;
    if (q('wall-name')) q('wall-name').textContent = T.wall ? 'картинка стоит' : 'выбрать картинку';
    var sw = q('swatches');
    if (sw && !sw.children.length) {
      PRESETS.forEach(function (c) {
        var d = document.createElement('div');
        d.className = 'swatch';
        d.style.background = c;
        d.dataset.c = c;
        d.onclick = function () { set('ac', c); };
        sw.appendChild(d);
      });
    }
    if (sw) Array.prototype.forEach.call(sw.children, function (d) {
      d.classList.toggle('on', (d.dataset.c || '').toLowerCase() === (T.ac || '').toLowerCase());
    });

    window.__aiTheme = T;
    window.__aiThemeReady = true;
  }

  function set(k, v) {
    T[k] = v;
    save();
    apply();
    if (window.__particlesNeedRestart) window.__particlesNeedRestart();
  }

  window.aiTheme = function () { return T; };
  window.aiThemeSet = set;
  window.aiThemeReset = function () {
    T = {}; Object.keys(DEF).forEach(function (k) { T[k] = DEF[k]; });
    save(); apply();
    if (window.__particlesNeedRestart) window.__particlesNeedRestart();
  };
  window.aiThemeApply = apply;

  apply();
  document.addEventListener('DOMContentLoaded', apply);
  window.addEventListener('load', apply);
  window.addEventListener('pageshow', apply);
})();
