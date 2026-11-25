(function () {
  if (window.__bs) { return; }
  var BS = window.__bs = {};

  function visible(el) {
    if (!el || !el.getBoundingClientRect) { return false; }
    var r = el.getBoundingClientRect();
    if (r.width < 24 || r.height < 10) { return false; }
    var cs = window.getComputedStyle(el);
    return cs.display !== "none" && cs.visibility !== "hidden" && cs.opacity !== "0";
  }

  function composer() {
    var areas = [];
    document.querySelectorAll("textarea").forEach(function (t) {
      if (visible(t) && !t.disabled && !t.readOnly) { areas.push(t); }
    });
    areas.sort(function (a, b) {
      var ap = /сообщ|message|отправ|send|спрос|ask|deepseek/i.test(a.placeholder || "") ? 1 : 0;
      var bp = /сообщ|message|отправ|send|спрос|ask|deepseek/i.test(b.placeholder || "") ? 1 : 0;
      if (ap !== bp) { return bp - ap; }
      return b.getBoundingClientRect().top - a.getBoundingClientRect().top;
    });
    if (areas.length) { return areas[0]; }
    var eds = [];
    document.querySelectorAll('[contenteditable="true"]').forEach(function (e) {
      if (visible(e)) { eds.push(e); }
    });
    eds.sort(function (a, b) { return b.getBoundingClientRect().top - a.getBoundingClientRect().top; });
    return eds[0] || null;
  }

  function composerText() {
    var el = composer();
    if (!el) { return ""; }
    return String(el.tagName === "TEXTAREA" ? el.value : (el.innerText || ""));
  }

  BS.composer = composer;
  BS.hasComposer = function () { return !!composer(); };
  BS.composerText = composerText;

  BS.setText = function (text) {
    var el = composer();
    if (!el) { return false; }
    try { el.focus(); } catch (e) {}
    if (el.tagName === "TEXTAREA") {
      var proto = Object.getPrototypeOf(el);
      var desc = Object.getOwnPropertyDescriptor(proto, "value");
      if (desc && desc.set) { desc.set.call(el, text); } else { el.value = text; }
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
    } else {
      var sel = window.getSelection();
      var range = document.createRange();
      range.selectNodeContents(el);
      sel.removeAllRanges();
      sel.addRange(range);
      var ok = false;
      try { ok = document.execCommand("insertText", false, text); } catch (e) {}
      if (!ok) {
        el.textContent = text;
        try {
          el.dispatchEvent(new InputEvent("input", {
            bubbles: true, inputType: "insertText", data: text
          }));
        } catch (e) {
          el.dispatchEvent(new Event("input", { bubbles: true }));
        }
      }
    }
    return true;
  };

  BS.pressEnter = function () {
    var el = composer();
    if (!el) { return false; }
    try {
      el.focus();
      ["keydown", "keypress", "keyup"].forEach(function (type) {
        el.dispatchEvent(new KeyboardEvent(type, {
          key: "Enter", code: "Enter", keyCode: 13, which: 13,
          bubbles: true, cancelable: true
        }));
      });
      return true;
    } catch (e) { return false; }
  };

  function labelOf(el) {
    return [
      el.getAttribute("aria-label") || "",
      el.getAttribute("title") || "",
      el.getAttribute("data-testid") || "",
      String(el.className || ""),
      el.innerText || ""
    ].join(" ").toLowerCase();
  }

  var SEND_HINT = /send|отправ|submit|发送/;
  var SEND_NEG = /attach|upload|plus|file|файл|скреп|mic|voice|голос|audio|deep\s?think|think|reason|search|поиск|研究|思考/;

  BS.clickSend = function () {
    var el = composer();
    if (!el) { return { clicked: false, how: "no-composer" }; }
    var er = el.getBoundingClientRect();
    var candidates = [];
    document.querySelectorAll('button, [role="button"], [class*="button"], svg').forEach(function (node) {
      var target = node.closest('button, [role="button"]') || node;
      if (!visible(target)) { return; }
      if (target.disabled || target.getAttribute("aria-disabled") === "true") { return; }
      var r = target.getBoundingClientRect();
      if (r.width > 260 || r.height > 120) { return; }
      var label = labelOf(target);
      var score = 0;
      var hinted = SEND_HINT.test(label);
      if (hinted) { score += 100; }
      if (SEND_NEG.test(label)) { score -= 120; }
      var cls = String(target.className || "").toLowerCase();
      if (/primary|filled|accent/.test(cls)) { score += 25; }
      var cy = r.top + r.height / 2;
      var inBand = cy > er.top - 24 && cy < er.bottom + 80;
      var onRight = r.left > er.left + er.width * 0.45;
      if (inBand) { score += 20; }
      if (onRight) { score += 15; }
      if (score > 0 && (hinted || (inBand && onRight))) {
        candidates.push({ el: target, score: score });
      }
    });
    candidates.sort(function (a, b) {
      if (b.score !== a.score) { return b.score - a.score; }
      return b.el.getBoundingClientRect().left - a.el.getBoundingClientRect().left;
    });
    if (candidates.length) {
      try { candidates[0].el.click(); return { clicked: true, how: "button" }; } catch (e) {}
    }
    return { clicked: false, how: "no-button" };
  };

  function assistantNodes() {
    var nodes = document.querySelectorAll(".ds-assistant-message-main-content");
    if (!nodes.length) {
      nodes = document.querySelectorAll(
        '[class*="assistant-message"], [data-message-author-role="assistant"], [data-role="assistant"]'
      );
    }
    var out = [];
    nodes.forEach(function (n) {
      var r = n.getBoundingClientRect();
      if (r.width < 120 || r.height < 8) { return; }
      var cs = window.getComputedStyle(n);
      if (cs.display === "none" || cs.visibility === "hidden") { return; }
      out.push(n);
    });
    return out;
  }

  function markerRegex(word) {
    return new RegExp("=+\\s*" + word + "\\s*=+", "gi");
  }

  function replyInfo() {
    var info = { len: 0, tail: "", end: false };
    try {
      var nodes = assistantNodes();
      if (!nodes.length) { return info; }
      var text = nodes[nodes.length - 1].innerText || "";
      info.len = text.length;
      info.tail = text.slice(-200);
      info.end = markerRegex("КОНЕЦ").test(text);
    } catch (e) {}
    return info;
  }

  BS.state = function () {
    var text = document.body ? (document.body.innerText || "") : "";
    var stop = false;
    document.querySelectorAll('button, [role="button"], [aria-label], [title]').forEach(function (b) {
      var label = ((b.getAttribute("aria-label") || "") + " " + (b.getAttribute("title") || "")).toLowerCase();
      if (/stop|останов|стоп|中止|停止/.test(label) && visible(b)) { stop = true; }
    });
    var composerValue = "";
    try { composerValue = composerText(); } catch (e) {}
    var reply = replyInfo();
    return {
      len: text.length,
      tail: text.slice(-200),
      stop: stop,
      url: location.href,
      composer: composerValue,
      replyLen: reply.len,
      replyTail: reply.tail,
      replyEnd: reply.end
    };
  };

  function clean(text) {
    return String(text || "")
      .replace(/\u200b/g, "")
      .replace(/[*_`]+/g, "")
      .replace(/\r/g, "");
  }

  function tidy(body) {
    body = String(body || "")
      .replace(/^[\s:：\-–—"']+/, "")
      .replace(/\s+$/, "");
    var junk = /^(копировать|copy|повторить|regenerate|поделиться|share|продолжить|continue|стоп|stop)$/i;
    var lines = body.split("\n");
    while (lines.length && junk.test(lines[lines.length - 1].trim())) { lines.pop(); }
    return lines.join("\n").trim();
  }

  function stripLead(body) {
    var lines = String(body || "").split("\n");
    while (lines.length) {
      var l = lines[0].trim();
      if (!l) { lines.shift(); continue; }
      if (/^(готово|вот|ниже|конечно)[.!:—–-]?(\s|$)/i.test(l)) { lines.shift(); continue; }
      if (/^конспект(\s+для\s+новой\s+сессии)?\s*[:：—–-]?$/i.test(l)) { lines.shift(); continue; }
      break;
    }
    return tidy(lines.join("\n"));
  }

  function fromMarkers(text, startWord, endWord) {
    var body = "";
    var last = null;
    var m;
    var startRe = markerRegex(startWord);
    while ((m = startRe.exec(text)) !== null) {
      last = { at: m.index, len: m[0].length };
      if (startRe.lastIndex === m.index) { startRe.lastIndex += 1; }
    }
    if (last) {
      body = text.slice(last.at + last.len);
      var em = markerRegex(endWord).exec(body);
      if (em) { body = body.slice(0, em.index); }
      body = tidy(body);
      if (body.length > 40) { return body; }
    }

    var lastEnd = null;
    var endAll = markerRegex(endWord);
    while ((m = endAll.exec(text)) !== null) {
      lastEnd = { at: m.index };
      if (endAll.lastIndex === m.index) { endAll.lastIndex += 1; }
    }
    if (lastEnd) {
      body = stripLead(tidy(text.slice(0, lastEnd.at)));
      if (body.length > 80) { return body; }
    }

    var heads = [
      "КОНСПЕКТ ДЛЯ НОВОЙ СЕССИИ",
      "КОНСПЕКТ РАБОТЫ",
      "КОНСПЕКТ",
      "СВОДКА",
      "SUMMARY"
    ];
    var upper = text.toUpperCase();
    var best = -1;
    var bestLen = 0;
    for (var h = 0; h < heads.length; h++) {
      var p = upper.lastIndexOf(heads[h]);
      if (p > best) { best = p; bestLen = heads[h].length; }
    }
    if (best !== -1) {
      body = stripLead(tidy(text.slice(best + bestLen)));
      if (body.length > 80) { return body; }
    }
    return "";
  }

  BS.extract = function (marker, endMarker, anchor) {
    var startWord = marker || "КОНСПЕКТ";
    var endWord = endMarker || "КОНЕЦ";

    try {
      var nodes = assistantNodes();
      if (nodes.length) {
        var reply = clean(nodes[nodes.length - 1].innerText || "");
        var fromReply = fromMarkers(reply, startWord, endWord);
        if (fromReply) { return { found: true, text: fromReply }; }
        return { found: false, text: "" };
      }
    } catch (e) {}

    var raw = document.body ? (document.body.innerText || "") : "";
    if (!raw) { return { found: false, text: "" }; }
    var text = clean(raw);

    var tail = text;
    if (anchor) {
      var a = clean(String(anchor));
      var ai = a ? text.lastIndexOf(a) : -1;
      if (ai !== -1) { tail = text.slice(ai + a.length); }
    }

    var promptJunk = /(сюда\s*[—–-]\s*конспект|требования к формату|начинай ответ сразу)/i;
    var recovered = fromMarkers(tail, startWord, endWord);
    if (recovered && !promptJunk.test(recovered)) {
      return { found: true, text: recovered };
    }
    return { found: false, text: "" };
  };
})();
