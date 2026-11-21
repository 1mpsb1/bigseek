from __future__ import annotations

import json
import time

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from .prompts import SUMMARY_PLACEHOLDER

# ---------------------------------------------------------------------------
# JS driver injected into a page on demand. Defines window.__bs with helpers:
#   __bs.hasComposer()      -> bool
#   __bs.setText(text)      -> bool
#   __bs.pressEnter()       -> bool
#   __bs.clickSend()        -> {clicked, how}
#   __bs.composerText()     -> str
#   __bs.state()            -> {len, tail, stop, url, composer}
#   __bs.extract(m, end, anchor) -> {found, text}
# It is idempotent, so it can be prepended to every call.
# ---------------------------------------------------------------------------
DRIVER_JS = r"""
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
      // DeepSeek paints the send arrow as a filled primary circle; the
      // neighbouring search / deep-think toggles are tertiary buttons.
      var cls = String(target.className || "").toLowerCase();
      if (/primary|filled|accent/.test(cls)) { score += 25; }
      var cy = r.top + r.height / 2;
      // Controls may sit inside the composer box or on the toolbar row just
      // below it (DeepSeek puts the send arrow under the textarea).
      var inBand = cy > er.top - 24 && cy < er.bottom + 80;
      // The send control sits inside / right of the composer, never far left.
      var onRight = r.left > er.left + er.width * 0.45;
      if (inBand) { score += 20; }
      if (onRight) { score += 15; }
      if (score > 0 && (hinted || (inBand && onRight))) {
        candidates.push({ el: target, score: score });
      }
    });
    candidates.sort(function (a, b) {
      if (b.score !== a.score) { return b.score - a.score; }
      // Rightmost wins: the send control is the last icon in the row.
      return b.el.getBoundingClientRect().left - a.el.getBoundingClientRect().left;
    });
    if (candidates.length) {
      try { candidates[0].el.click(); return { clicked: true, how: "button" }; } catch (e) {}
    }
    return { clicked: false, how: "no-button" };
  };

  function assistantNodes() {
    // DeepSeek marks the answer body explicitly; other chat UIs use role tags.
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

  function markerRegex(word) {
    return new RegExp("=+\\s*" + word + "\\s*=+", "gi");
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

    // The model forgot ===КОНСПЕКТ=== but still closed the block: everything
    // before the last ===КОНЕЦ=== is the summary.
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

    // No markers at all: salvage the section under a heading.
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

    // The assistant bubble is the only trustworthy source: the same markers
    // are also quoted inside the compaction prompt shown in the chat.
    try {
      var nodes = assistantNodes();
      if (nodes.length) {
        var reply = clean(nodes[nodes.length - 1].innerText || "");
        var fromReply = fromMarkers(reply, startWord, endWord);
        if (fromReply) { return { found: true, text: fromReply }; }
        // A bubble was found but it is not a summary (probably a normal
        // answer): never fall back to the page text, it may contain the prompt.
        return { found: false, text: "" };
      }
    } catch (e) {}

    var raw = document.body ? (document.body.innerText || "") : "";
    if (!raw) { return { found: false, text: "" }; }
    var text = clean(raw);

    // Everything before the end of the sent prompt is ignored: otherwise the
    // markers quoted inside the prompt itself could be mistaken for the reply.
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
"""

COMPOSER_TIMEOUT_MS = 45000
REPLY_TIMEOUT_S = 300.0
SEND_CHECK_MS = 1400


def _js(value: str) -> str:
    """A safely quoted JS string literal."""
    return json.dumps(value, ensure_ascii=False)


class AutoTransfer(QObject):
    """Sends the compaction prompt, waits for the reply, extracts the summary
    and sends it to the target session - all without manual copy/paste."""

    progress = pyqtSignal(str)
    finished = pyqtSignal(bool, str, dict)

    def __init__(
        self,
        window,
        source_sid: str,
        target_sid: str,
        compact_text: str,
        resume_template: str,
        mark_source: bool = True,
        parent=None,
    ):
        super().__init__(parent)
        self.window = window
        self.source_sid = source_sid
        self.target_sid = target_sid
        self.compact_text = compact_text
        self.resume_template = resume_template
        self.mark_source = mark_source

        self._cancelled = False
        self._done = False
        self._summary = ""
        self._baseline = 0
        self._reply_started = 0.0
        self._last_sig = None
        self._stable_since = None
        self._ticks = 0
        self._send_baseline = 0
        self._send_len = 0
        self._send_label = ""
        self._prev_reply_len = 0
        self._prev_reply_tail = ""
        self._extract_retries = 0
        self._deadline = 0.0

        self._source_name = self._name_of(source_sid)
        self._target_name = self._name_of(target_sid)

    # ------------------------------------------------------------- helpers
    def _name_of(self, sid: str) -> str:
        try:
            session = self.window.store.get(sid)
            return session.name if session else sid
        except Exception:
            return sid

    def _page(self, sid: str):
        try:
            view = self.window._ensure_runtime(sid)
        except Exception:
            return None
        return view.page() if view is not None else None

    def _emit(self, text: str) -> None:
        if not self._done and not self._cancelled:
            self.progress.emit(text)

    def _after(self, ms: int, fn) -> None:
        def wrapped() -> None:
            if not self._cancelled and not self._done:
                fn()

        QTimer.singleShot(ms, wrapped)

    def _fail(self, message: str) -> None:
        if self._done or self._cancelled:
            return
        self._done = True
        self.finished.emit(False, message, {"summary": self._summary})

    def _succeed(self) -> None:
        if self._done or self._cancelled:
            return
        self._done = True
        resume = self.resume_template
        if self._summary:
            resume = resume.replace(SUMMARY_PLACEHOLDER, self._summary)
        self.finished.emit(
            True,
            f"Контекст перенесён в «{self._target_name}».",
            {
                "summary": self._summary,
                "target_sid": self.target_sid,
                "resume_text": resume,
            },
        )

    def cancel(self) -> None:
        if self._done:
            return
        self._cancelled = True
        self._done = True
        self.finished.emit(False, "Перенос отменён.", {"summary": self._summary})

    # ---------------------------------------------------------------- flow
    def start(self) -> None:
        if self._done or self._cancelled:
            return
        self._emit(f"Открываю сессию «{self._source_name}»…")
        try:
            self.window.activate_session(self.source_sid)
        except Exception:
            pass
        self._wait_composer(self.source_sid, self._source_ready)

    def _wait_composer(self, sid: str, then) -> None:
        if self._done or self._cancelled:
            return
        page = self._page(sid)
        if page is None:
            return self._fail("Не удалось открыть сессию.")
        started = time.time()

        def check(ready) -> None:
            if self._done or self._cancelled:
                return
            if ready:
                then()
                return
            if (time.time() - started) * 1000 > COMPOSER_TIMEOUT_MS:
                self._page_url(sid, self._composer_missing)
                return
            self._after(600, lambda: self._wait_composer(sid, then))

        page.runJavaScript(
            DRIVER_JS + "; window.__bs ? window.__bs.hasComposer() : false", check
        )

    def _page_url(self, sid: str, then) -> None:
        page = self._page(sid)
        if page is None:
            return self._fail("Не удалось открыть сессию.")

        def got(url) -> None:
            then(str(url or ""))

        page.runJavaScript("location.href", got)

    def _composer_missing(self, url: str) -> None:
        if "/sign_in" in url or "/login" in url:
            self._fail(
                f"В сессии «{self._source_name}» открыта страница входа. "
                "Войдите в аккаунт и повторите перенос."
            )
        else:
            self._fail(
                f"Не нашёл поле ввода в сессии «{self._source_name}». "
                "Убедитесь, что открыт чат, а не страница входа или ошибки."
            )

    # --------------------------------------------------- step 1: compaction
    def _source_ready(self) -> None:
        self._emit("Считаю текущий объём диалога…")
        page = self._page(self.source_sid)
        if page is None:
            return self._fail("Сессия закрыта.")

        def got(state) -> None:
            if isinstance(state, dict):
                self._baseline = int(state.get("len") or 0)
                self._prev_reply_len = int(state.get("replyLen") or 0)
                self._prev_reply_tail = str(state.get("replyTail") or "")
            self._send_compact()

        page.runJavaScript(DRIVER_JS + "; window.__bs.state()", got)

    def _send_compact(self) -> None:
        self._emit(f"Отправляю промт сжатия в «{self._source_name}»…")
        self._send_text(self.source_sid, self.compact_text, self._wait_reply)

    # ------------------------------------------------------ generic sending
    def _send_text(self, sid: str, text: str, on_sent) -> None:
        page = self._page(sid)
        if page is None:
            return self._fail("Сессия закрыта.")

        self._send_baseline = 0
        self._send_len = len(text)

        def got_state(state) -> None:
            if isinstance(state, dict):
                self._send_baseline = int(state.get("len") or 0)

            def injected(ok) -> None:
                if not ok:
                    return self._fail("Не удалось вставить текст в поле ввода.")
                self._after(350, lambda: self._enter_first(page, text, sid, 0, on_sent))

            page.runJavaScript(DRIVER_JS + f"; window.__bs.setText({_js(text)})", injected)

        page.runJavaScript(DRIVER_JS + "; window.__bs.state()", got_state)

    def _enter_first(self, page, text: str, sid: str, attempt: int, on_sent) -> None:
        # Enter is the least invasive way to submit in chat UIs.
        page.runJavaScript(DRIVER_JS + "; window.__bs.pressEnter()", lambda _r: None)
        self._after(SEND_CHECK_MS, lambda: self._verify_sent(page, text, sid, attempt, on_sent))

    def _verify_sent(self, page, text: str, sid: str, attempt: int, on_sent) -> None:
        if self._done or self._cancelled:
            return

        def got(state) -> None:
            if self._done or self._cancelled:
                return
            composer = str((state or {}).get("composer") or "") if isinstance(state, dict) else ""
            length = int((state or {}).get("len") or 0) if isinstance(state, dict) else 0
            grew = length >= self._send_baseline + min(len(text), 120)
            if (not composer.strip()) or grew:
                on_sent()
                return
            if attempt == 0:
                # Enter did not submit - try clicking the send control.
                page.runJavaScript(DRIVER_JS + "; window.__bs.clickSend()", lambda _r: None)
                self._after(SEND_CHECK_MS, lambda: self._verify_sent(page, text, sid, 1, on_sent))
                return
            self._fail(
                "Не удалось отправить сообщение: поле ввода не очистилось. "
                "Отправьте промт вручную — он уже скопирован в буфер обмена."
            )

        page.runJavaScript(DRIVER_JS + "; window.__bs.state()", got)

    # ------------------------------------------------------- step 2: reply
    def _wait_reply(self) -> None:
        self._emit("Ассистент готовит конспект…")
        self._reply_started = time.time()
        self._deadline = self._reply_started + REPLY_TIMEOUT_S
        self._last_sig = None
        self._stable_since = None
        self._ticks = 0
        self._poll_reply()

    def _poll_reply(self) -> None:
        if self._done or self._cancelled:
            return
        page = self._page(self.source_sid)
        if page is None:
            return self._fail("Сессия закрыта.")
        page.runJavaScript(
            DRIVER_JS + "; window.__bs ? window.__bs.state() : null", self._on_reply
        )

    def _on_reply(self, state) -> None:
        if self._done or self._cancelled:
            return
        now = time.time()
        elapsed = now - self._reply_started
        if not isinstance(state, dict):
            if elapsed > 15:
                return self._fail("Страница перестала отвечать — не удалось дождаться ответа.")
            return self._after(800, self._poll_reply)

        length = int(state.get("len") or 0)
        rlen = int(state.get("replyLen") or 0)
        rtail = str(state.get("replyTail") or "")
        rend = bool(state.get("replyEnd"))
        stop = bool(state.get("stop"))

        # The newest assistant message may be the one from before the transfer.
        is_new = rlen > 0 and (
            rlen != self._prev_reply_len or rtail != self._prev_reply_tail
        )

        if rlen > 0:
            sig = (rlen, rtail[-120:])
        else:
            sig = (length, str(state.get("tail") or "")[-80:])
        if sig != self._last_sig:
            self._last_sig = sig
            self._stable_since = now

        quiet = (now - self._stable_since) if self._stable_since else 0.0

        if rlen > 0:
            # Wait for the assistant bubble to stop growing. An explicit
            # ===КОНЕЦ=== marker is the strongest "I am done" signal.
            needed_quiet = 1.2 if rend else 3.0
            ready = (
                is_new
                and rlen >= 80
                and quiet >= needed_quiet
                and elapsed >= 2.5
                and (rend or not stop)
            )
        else:
            # Unknown chat UI: fall back to page growth, but keep the bar low
            # so a virtualised history cannot stall the wait forever.
            needed = self._baseline + min(self._send_len, 1200) + 150
            ready = (
                length >= needed
                and quiet >= 2.5
                and not stop
                and elapsed >= 5.0
            )

        if ready:
            return self._extract()
        if self._deadline and now >= self._deadline:
            return self._extract(timed_out=True)

        self._ticks += 1
        if self._ticks % 8 == 0:
            self._emit(f"Жду ответа ассистента… {int(elapsed)} с")
        self._after(700, self._poll_reply)

    # ---------------------------------------------------- step 3: extraction
    def _extract(self, timed_out: bool = False) -> None:
        self._emit("Извлекаю конспект из ответа…")
        page = self._page(self.source_sid)
        if page is None:
            return self._fail("Сессия закрыта.")

        def got(result) -> None:
            if self._done or self._cancelled:
                return
            text = ""
            found = False
            if isinstance(result, dict):
                found = bool(result.get("found"))
                text = str(result.get("text") or "")
            if not found or len(text) < 80:
                if timed_out:
                    return self._fail(
                        "Ассистент не ответил за отведённое время. "
                        "Промт сжатия уже отправлен — дождитесь ответа и повторите перенос."
                    )
                if self._extract_retries < 2:
                    self._extract_retries += 1
                    self._emit("Конспект пока не виден — жду ещё немного…")
                    self._wait_reply()
                    self._deadline = time.time() + 45
                    return
                return self._fail(
                    "В ответе не нашёлся блок конспекта (маркеры ===КОНСПЕКТ=== … ===КОНЕЦ===). "
                    "Промты скопированы в буфер обмена — можно перенести вручную."
                )
            self._summary = text
            self._emit("Конспект получен. Переключаюсь на целевую сессию…")
            try:
                self.window.activate_session(self.target_sid)
            except Exception:
                pass
            self._wait_composer(self.target_sid, self._send_resume)

        anchor = ""
        for line in reversed(self.compact_text.strip().splitlines()):
            if line.strip():
                anchor = line.strip()[-160:]
                break

        page.runJavaScript(
            DRIVER_JS
            + "; window.__bs.extract('КОНСПЕКТ', 'КОНЕЦ', " + _js(anchor) + ")",
            got,
        )

    # ------------------------------------------------------ step 4: resume
    def _send_resume(self) -> None:
        resume = self.resume_template.replace(SUMMARY_PLACEHOLDER, self._summary)
        self._emit(f"Отправляю конспект в «{self._target_name}»…")
        self._send_text(self.target_sid, resume, self._succeed)
