(function () {
  if (window.__bsmScan) { return; }
  var st = window.__bsm = window.__bsm || {
    phrase: "", phraseAt: 0, resetAt: 0, resetText: "", vol: null
  };

  var PHRASES = [
    /(已|当前|今日|本日)[^\n。]{0,8}(达|用尽|耗尽)[^\n。]{0,8}(上限|限额)/,
    /(上限|限额)[^\n。]{0,4}(已|已经)?[^\n。]{0,4}(用尽|耗尽|达到)/,
    /(对话|发送|消息)[^\n。]{0,6}(次数)[^\n。]{0,8}(上限|用完|用尽)/,
    /reached\s+(your\s+|the\s+)?(?:daily\s+|message\s+|messages\s+|usage\s+|chat\s+)*(limit|quota)/i,
    /(daily|message|usage|chat)\s+(message\s+|messages\s+)?(limit|quota)\s+(reached|exceeded|is reached)/i,
    /limit\s+of\s+(messages|requests|chats)/i,
    /too\s+many\s+(messages|requests|chats)/i,
    /rate\s+limit\s+exceeded/i,
    /limit\s+(reached|exceeded)/i,
    /(лимит|квота)[^\n.]{0,25}(исчерпан|достигнут|превышен)/i,
    /(превышен|достигнут)[^\n.]{0,25}(лимит|квот)/i,
    /(сообщений|запросов)[^\n.]{0,20}(слишком много|больше)/i
  ];

  function findReset(txt) {
    if (!txt) { return null; }
    var now = Date.now();
    var keys = /(сброс|обнов|восстан|возобн|доступн|reset|renew|refresh|restore|available|重置|恢复|刷新)/i;
    var limitish = /(лимит|квот|limit|quota|上限|限额)/i;
    var reAbs = /(\d{1,2})[:：](\d{2})/;
    var reRelRu = /через\s+(\d+)\s*(минут|мин|час|ч|день|дня|дней)/i;
    var reRelEn = /\bin\s+(\d+)\s*(minute|minutes|min|hour|hours|hr|h|day|days)\b/i;
    var reRelZh = /(\d+)\s*(分钟|小时|天)\s*后/;
    var lines = String(txt).split("\n");
    var start = Math.max(0, lines.length - 90);
    for (var i = start; i < lines.length; i++) {
      var line = lines[i].trim();
      if (!line || line.length > 220) { continue; }
      if (!keys.test(line)) { continue; }
      var hasTime = reAbs.test(line) || reRelRu.test(line) || reRelEn.test(line) || reRelZh.test(line);
      if (!hasTime) { continue; }
      if (!limitish.test(line) && !reRelRu.test(line) && !reRelEn.test(line) && !reRelZh.test(line)) {
        continue;
      }
      var m;
      if ((m = line.match(reRelZh))) {
        var nz = parseInt(m[1], 10);
        var uz = m[2];
        var msz = nz * (uz === "分钟" ? 60000 : (uz === "小时" ? 3600000 : 86400000));
        return { at: now + msz, text: line };
      }
      if ((m = line.match(reRelRu))) {
        var nr = parseInt(m[1], 10);
        var ur = m[2].toLowerCase();
        var msr = /мин/.test(ur) ? 60000 : ((ur === "час" || ur === "ч") ? 3600000 : 86400000);
        return { at: now + nr * msr, text: line };
      }
      if ((m = line.match(reRelEn))) {
        var ne = parseInt(m[1], 10);
        var ue = m[2].toLowerCase();
        var mse = /^h$|hour|hr/.test(ue) ? 3600000 : (/day/.test(ue) ? 86400000 : 60000);
        return { at: now + ne * mse, text: line };
      }
      if ((m = line.match(reAbs))) {
        var hh = parseInt(m[1], 10);
        var mm = parseInt(m[2], 10);
        var after = line.slice(m.index + m[0].length, m.index + m[0].length + 4).toLowerCase();
        if (/^\s*pm/.test(after) && hh < 12) { hh += 12; }
        if (/^\s*am/.test(after) && hh === 12) { hh = 0; }
        if (hh < 24 && mm < 60) {
          var dt = new Date();
          dt.setHours(hh, mm, 0, 0);
          if (dt.getTime() < now - 60000) { dt.setDate(dt.getDate() + 1); }
          return { at: dt.getTime(), text: line };
        }
      }
    }
    return null;
  }

  function scanText(txt) {
    if (!txt) { return false; }
    var lines = String(txt).split("\n");
    var found = false;
    for (var li = 0; li < lines.length && !found; li++) {
      var line = lines[li].trim();
      if (!line || line.length > 220) { continue; }
      for (var i = 0; i < PHRASES.length; i++) {
        var m = line.match(PHRASES[i]);
        if (m) {
          var hit = String(m[0]).replace(/\s+/g, " ").slice(0, 120);
          if (hit !== st.phrase) { st.phraseAt = Date.now(); }
          st.phrase = hit;
          found = true;
          break;
        }
      }
    }
    if (found || (st.phrase && Date.now() - st.phraseAt < 600000)) {
      var reset = findReset(txt);
      if (reset && reset.at > Date.now() - 60000 && reset.at < Date.now() + 8 * 86400000) {
        st.resetAt = reset.at;
        st.resetText = String(reset.text || "").slice(0, 200);
      }
    }
    return found;
  }

  try {
    var obs = new MutationObserver(function (muts) {
      for (var i = 0; i < muts.length; i++) {
        var nodes = muts[i].addedNodes || [];
        for (var j = 0; j < nodes.length; j++) {
          var n = nodes[j];
          if (n && n.nodeType === 1) {
            if (scanText((n.textContent || "").slice(0, 4000))) { return; }
          }
        }
      }
    });
    obs.observe(document.documentElement || document, { childList: true, subtree: true });
  } catch (e) {}

  function volume() {
    if (st.vol && Date.now() - st.vol.at < 4000) { return st.vol.val; }
    var chars = 0;
    var messages = 0;
    var items = {};
    var nodes = document.querySelectorAll(".ds-message");
    var i;
    var n;
    var t;
    for (i = 0; i < nodes.length; i++) {
      n = nodes[i];
      var parent = n.parentElement;
      if (parent && parent.closest && parent.closest(".ds-message")) { continue; }
      t = n.innerText || "";
      if (t.trim().length < 2) { continue; }
      chars += t.length;
      messages += 1;
      // The chat is a virtual list: only a few messages live in the DOM and
      // the window slides while the conversation grows. Remember every row by
      // its stable key so the total keeps growing instead of freezing.
      var row = n.closest ? n.closest("[data-virtual-list-item-key]") : null;
      var rowKey = row ? row.getAttribute("data-virtual-list-item-key") : "";
      if (rowKey) { items[rowKey] = (items[rowKey] || 0) + t.length; }
    }
    if (!messages) {
      nodes = document.querySelectorAll('[data-message-author-role]');
      for (i = 0; i < nodes.length; i++) {
        n = nodes[i];
        var up = n.parentElement;
        if (up && up.closest && up.closest('[data-message-author-role]')) { continue; }
        t = n.innerText || "";
        if (t.trim().length < 2) { continue; }
        chars += t.length;
        messages += 1;
      }
    }
    var val = {
      chars: chars,
      messages: messages,
      tokens: Math.round(chars / 2.5),
      measured: messages > 0,
      items: items
    };
    st.vol = { at: Date.now(), val: val };
    return val;
  }

  function chatKey() {
    try {
      var path = location.pathname || "";
      var m = path.match(/\/a\/chat\/s\/([^\/?#]+)/);
      if (m) { return m[1]; }
      m = path.match(/\/chat\/([^\/?#]+)/);
      if (m && m[1] !== "s") { return m[1]; }
    } catch (e) {}
    return "";
  }

  window.__bsmScan = function () {
    var body = (document.body && document.body.innerText) || "";
    try { scanText(body.slice(-4000)); } catch (e) {}
    var vol = { chars: 0, messages: 0, tokens: 0, measured: false };
    try { vol = volume(); } catch (e) {}
    return {
      url: location.href,
      chat: chatKey(),
      chars: vol.chars,
      tokens: vol.tokens,
      messages: vol.messages,
      items: vol.items || {},
      measured: !!vol.measured,
      phrase: st.phrase,
      phraseAt: st.phraseAt,
      resetAt: st.resetAt,
      resetText: st.resetText
    };
  };
})();
