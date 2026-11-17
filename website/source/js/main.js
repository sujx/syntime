(function () {
  'use strict';
  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* 滚动入场：只加 .in，时长与位移归 main.css 的 .io 过渡；脚本不持样式也不持文案 */
  var ioEls = document.querySelectorAll('.io');
  if (reduce || !('IntersectionObserver' in window)) {
    ioEls.forEach(function (el) { el.classList.add('in'); });
  } else {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (!e.isIntersecting) return;
        e.target.classList.add('in');
        io.unobserve(e.target);
      });
    }, { threshold: 0.12, rootMargin: '0px 0px -40px 0px' });
    ioEls.forEach(function (el) { io.observe(el); });
  }

  /* 界面速览：切面板与图注（文字全在 HTML 里，脚本不持文案） */
  var seg = document.getElementById('seg-shot');
  if (seg) {
    seg.addEventListener('click', function (e) {
      var b = e.target.closest('button[data-shot]');
      if (!b || b.classList.contains('on')) return;
      seg.querySelectorAll('button').forEach(function (x) {
        var on = x === b;
        x.classList.toggle('on', on);
        x.setAttribute('aria-selected', on);
      });
      var i = b.getAttribute('data-shot');
      document.querySelectorAll('.shot-panel').forEach(function (p) {
        p.hidden = p.getAttribute('data-shot') !== i;
      });
    });
    seg.addEventListener('keydown', function (e) {
      if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
      var bs = [].slice.call(seg.querySelectorAll('button'));
      var n = bs.indexOf(document.activeElement);
      if (n < 0) return;
      var t = bs[(n + (e.key === 'ArrowRight' ? 1 : bs.length - 1)) % bs.length];
      t.focus(); t.click(); e.preventDefault();
    });
  }

  /* 代码复制：clipboard API + execCommand 兜底；失败只静默，不改文案也不报完成 */
  function done(btn) {
    btn.textContent = btn.getAttribute('data-label-done');
    btn.classList.add('ok');
    setTimeout(function () {
      btn.textContent = btn.dataset.origLabel;
      btn.classList.remove('ok');
    }, 1600);
  }
  document.querySelectorAll('.copy-btn').forEach(function (btn) {
    btn.dataset.origLabel = btn.textContent;
    btn.addEventListener('click', function () {
      var pre = document.getElementById(btn.getAttribute('data-copy'));
      if (!pre) return;
      var text = pre.innerText;
      if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(text).then(function () { done(btn); });
      } else {
        var ta = document.createElement('textarea');
        ta.value = text;
        ta.setAttribute('readonly', '');
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        try { document.execCommand('copy'); done(btn); } catch (err) { /* 静默：不谎称已复制 */ }
        document.body.removeChild(ta);
      }
    });
  });

  /* 横幅关闭：仅本次会话（§2 段 1），不写 localStorage */
  var banner = document.querySelector('.alpha');
  if (banner) {
    try { if (sessionStorage.getItem('syntime.alpha.dismissed') === '1') banner.hidden = true; }
    catch (err) { /* 隐私模式下 sessionStorage 会抛：留着横幅比谎称已关闭好 */ }
    var x = banner.querySelector('[data-dismiss-alpha]');
    if (x) x.addEventListener('click', function () {
      banner.hidden = true;
      try { sessionStorage.setItem('syntime.alpha.dismissed', '1'); } catch (err) { /* 同上 */ }
    });
  }
})();
