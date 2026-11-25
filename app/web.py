from __future__ import annotations

import re
import shutil
import time
from pathlib import Path

from PyQt6.QtCore import QObject, QUrl, pyqtSignal
from PyQt6.QtWebEngineCore import (
    QWebEnginePage,
    QWebEngineProfile,
    QWebEngineScript,
    QWebEngineSettings,
    QWebEngineUrlRequestInterceptor,
)
from PyQt6.QtWebEngineWidgets import QWebEngineView

from .config import Settings

# ---------------------------------------------------------------------------
# Injected into every page of every profile (main world, at document creation).
# It counts outgoing chat requests, catches transient "limit reached" toasts
# and reports everything back through window.__dsmScan().
# ---------------------------------------------------------------------------
MONITOR_JS = r"""
(function () {
  // Google OAuth refuses sign-in when the UA claims Chrome but client hints
  // only advertise "Chromium". Present a consistent Chrome identity.
  try {
    if (navigator.userAgentData) {
      var brands = [
        { brand: "Google Chrome", version: "140" },
        { brand: "Chromium", version: "140" },
        { brand: "Not=A?Brand", version: "24" }
      ];
      var original = navigator.userAgentData;
      var fake = {
        brands: brands,
        mobile: false,
        platform: "Windows",
        getHighEntropyValues: function (hints) {
          return original.getHighEntropyValues(hints).then(function (v) {
            v.brands = brands.slice();
            v.fullVersionList = brands.map(function (b) {
              return { brand: b.brand, version: b.version + ".0.0.0" };
            });
            v.uaFullVersion = "140.0.0.0";
            v.platform = "Windows";
            v.platformVersion = "19.0.0.0";
            v.architecture = "x86";
            v.bitness = "64";
            v.model = "";
            v.wow64 = false;
            return v;
          });
        },
        toJSON: function () {
          return { brands: brands.slice(), mobile: false, platform: "Windows" };
        }
      };
      Object.defineProperty(navigator, "userAgentData", {
        get: function () { return fake; },
        configurable: true
      });
    }
  } catch (e) {}

  if (window.__dsm) { return; }
  var st = window.__dsm = {
    sentApi: 0,
    sentKey: 0,
    lastSendAt: 0,
    lastStatus: 0,
    last429At: 0,
    lastError: "",
    lastErrorAt: 0,
    phrase: "",
    phraseAt: 0,
    resetAt: 0,
    resetText: ""
  };

  var CHAT_RE = /\/api\/[^?#]*\/(completion|regenerate|continue|edit|branch)/i;
  function isChat(u) { return typeof u === "string" && CHAT_RE.test(u); }

  var origFetch = window.fetch;
  if (origFetch) {
    window.fetch = function (input, init) {
      var url = "", method = "GET";
      try {
        url = typeof input === "string" ? input : ((input && input.url) || "");
        method = (init && init.method) || (input && input.method) || "GET";
      } catch (e) {}
      var chat = isChat(url);
      if (chat && String(method).toUpperCase() === "POST") {
        st.sentApi += 1;
        st.lastSendAt = Date.now();
      }
      var p = origFetch.apply(this, arguments);
      if (chat) {
        try {
          p.then(function (r) {
            st.lastStatus = r.status;
            if (r.status === 429) { st.last429At = Date.now(); }
            if (!r.ok) {
              try {
                r.clone().text().then(function (t) {
                  st.lastError = String(t || "").slice(0, 500);
                  st.lastErrorAt = Date.now();
                }).catch(function () {});
              } catch (e) {}
            }
          }).catch(function (e) {
            st.lastError = String((e && e.message) || e).slice(0, 200);
            st.lastErrorAt = Date.now();
          });
        } catch (e) {}
      }
      return p;
    };
  }

  var origOpen = XMLHttpRequest.prototype.open;
  var origSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (method, url) {
    try { this.__dsmInfo = { url: String(url || ""), method: String(method || "GET") }; } catch (e) {}
    return origOpen.apply(this, arguments);
  };
  XMLHttpRequest.prototype.send = function () {
    var info = this.__dsmInfo || {};
    if (isChat(info.url) && String(info.method).toUpperCase() === "POST") {
      st.sentApi += 1;
      st.lastSendAt = Date.now();
    }
    var xhr = this;
    try {
      xhr.addEventListener("loadend", function () {
        if (!isChat(info.url)) { return; }
        st.lastStatus = xhr.status;
        if (xhr.status === 429) { st.last429At = Date.now(); }
        if (xhr.status >= 400) {
          try {
            st.lastError = String(xhr.responseText || "").slice(0, 500);
            st.lastErrorAt = Date.now();
          } catch (e) {}
        }
      });
    } catch (e) {}
    return origSend.apply(this, arguments);
  };

  document.addEventListener("keydown", function (e) {
    if (e.key !== "Enter" || e.shiftKey || e.isComposing) { return; }
    var el = e.target;
    if (!el) { return; }
    var tag = (el.tagName || "").toLowerCase();
    if (tag === "textarea" || el.isContentEditable) {
      st.sentKey += 1;
      st.lastSendAt = Date.now();
    }
  }, true);

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
    // Reads phrases like "Сброс в 03:00", "resets in 2 hours", "3 小时后重置".
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
        var nz = parseInt(m[1], 10), uz = m[2];
        var msz = nz * (uz === "分钟" ? 60000 : (uz === "小时" ? 3600000 : 86400000));
        return { at: now + msz, text: line };
      }
      if ((m = line.match(reRelRu))) {
        var nr = parseInt(m[1], 10), ur = m[2].toLowerCase();
        var msr = /мин/.test(ur) ? 60000 : ((ur === "час" || ur === "ч") ? 3600000 : 86400000);
        return { at: now + nr * msr, text: line };
      }
      if ((m = line.match(reRelEn))) {
        var ne = parseInt(m[1], 10), ue = m[2].toLowerCase();
        var mse = /^h$|hour|hr/.test(ue) ? 3600000 : (/day/.test(ue) ? 86400000 : 60000);
        return { at: now + ne * mse, text: line };
      }
      if ((m = line.match(reAbs))) {
        var hh = parseInt(m[1], 10), mm = parseInt(m[2], 10);
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
    // Match only short single lines: long chat messages may mention limits
    // without being an actual quota notice.
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
    // Reset time may appear in the same notice or a nearby banner.
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
    if (st.vol && Date.now() - st.vol.at < 3000) { return st.vol.val; }
    var chars = 0, messages = 0, items = {};
    var nodes = document.querySelectorAll(".ds-message");
    var i, n, t;
    for (i = 0; i < nodes.length; i++) {
      n = nodes[i];
      var parent = n.parentElement;
      if (parent && parent.closest && parent.closest(".ds-message")) { continue; }
      t = n.innerText || "";
      if (t.trim().length < 2) { continue; }
      chars += t.length;
      messages += 1;
      // The chat is a virtual list: only a few messages live in the DOM and
      // the visible window slides as the conversation grows. Remember every
      // row by its stable key, otherwise the total freezes as soon as the
      // window moves and small messages look uncounted.
      var row = n.closest ? n.closest("[data-virtual-list-item-key]") : null;
      var rowKey = row ? row.getAttribute("data-virtual-list-item-key") : "";
      if (rowKey) { items[rowKey] = (items[rowKey] || 0) + t.length; }
    }
    if (!messages) {
      // Some builds only tag the message roots with a role attribute.
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
    // Deliberately no ".ds-markdown" or document.body fallback: those count
    // partial blocks or the whole UI and made the counter jump (60K -> 30K)
    // while the page was still settling. Without message nodes we report
    // "not measured" and keep the previous value.
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

  window.__dsmScan = function () {
    var body = (document.body && document.body.innerText) || "";
    try { scanText(body.slice(-2000)); } catch (e) {}
    var vol = { chars: 0, messages: 0, tokens: 0 };
    try { vol = volume(); } catch (e) {}
    return {
      url: location.href,
      chat: chatKey(),
      sentApi: st.sentApi,
      sentKey: st.sentKey,
      lastSendAt: st.lastSendAt,
      lastStatus: st.lastStatus,
      last429At: st.last429At,
      lastError: st.lastError,
      lastErrorAt: st.lastErrorAt,
      phrase: st.phrase,
      phraseAt: st.phraseAt,
      resetAt: st.resetAt,
      resetText: st.resetText,
      ctxChars: vol.chars,
      ctxTokens: vol.tokens,
      ctxMessages: vol.messages,
      ctxItems: vol.items || {},
      ctxMeasured: !!vol.measured
    };
  };
})();
"""

ERROR_LIMIT_RE = re.compile(
    r"(429|too many|rate.?limit|上限|限额|limit\s+(reached|exceeded)|лимит)", re.I
)

# Client hints that a real Google Chrome sends. QtWebEngine advertises only
# "Chromium", which makes Google's OAuth page reject the browser as insecure.
CH_UA = b'"Google Chrome";v="140", "Chromium";v="140", "Not=A?Brand";v="24"'
CH_UA_FULL = (
    b'"Google Chrome";v="140.0.0.0", "Chromium";v="140.0.0.0", "Not=A?Brand";v="24.0.0.0"'
)


class ChromeHintsInterceptor(QWebEngineUrlRequestInterceptor):
    def interceptRequest(self, info) -> None:
        try:
            info.setHttpHeader(b"sec-ch-ua", CH_UA)
            info.setHttpHeader(b"sec-ch-ua-mobile", b"?0")
            info.setHttpHeader(b"sec-ch-ua-platform", b'"Windows"')
            info.setHttpHeader(b"sec-ch-ua-platform-version", b'"19.0.0.0"')
            info.setHttpHeader(b"sec-ch-ua-full-version", b'"140.0.0.0"')
            info.setHttpHeader(b"sec-ch-ua-full-version-list", CH_UA_FULL)
            info.setHttpHeader(b"sec-ch-ua-arch", b'"x86"')
            info.setHttpHeader(b"sec-ch-ua-bitness", b'"64"')
            info.setHttpHeader(b"sec-ch-ua-model", b'""')
            info.setHttpHeader(b"sec-ch-ua-wow64", b"?0")
        except Exception:
            pass


class WebPage(QWebEnginePage):
    """Page that opens popups (OAuth logins etc.) in a separate window."""

    def __init__(self, profile: QWebEngineProfile, parent=None, owner=None):
        super().__init__(profile, parent)
        self._owner = owner

    def createWindow(self, _wtype):
        if self._owner is None:
            return None
        return self._owner.create_popup_page(self.profile())

    def featurePermissionRequested(self, origin: QUrl, feature):
        granted = {
            QWebEnginePage.Feature.Notifications,
            QWebEnginePage.Feature.ClipboardReadWrite,
            QWebEnginePage.Feature.MediaAudioCapture,
            QWebEnginePage.Feature.MediaVideoCapture,
            QWebEnginePage.Feature.MediaAudioVideoCapture,
        }
        policy = (
            QWebEnginePage.PermissionPolicy.PermissionGrantedByUser
            if feature in granted
            else QWebEnginePage.PermissionPolicy.PermissionDeniedByUser
        )
        self.setFeaturePermission(origin, feature, policy)

    def certificateError(self, error) -> bool:
        if not error.isOverridable():
            return False
        host = (error.url().host() or "").lower()
        allowed = getattr(self._owner, "allowed_host", "") or ""
        return bool(host) and bool(allowed) and (host == allowed or host.endswith("." + allowed))

    def javaScriptConsoleMessage(self, level, message, line, source):
        pass


class SessionRuntime(QObject):
    """One isolated browser profile (cookies, storage, cache) + its scripts."""

    download_started = pyqtSignal(str)

    def __init__(self, session_id: str, base_dir: Path, settings: Settings, parent=None):
        super().__init__(parent)
        self.session_id = session_id
        self.dir = Path(base_dir) / "profiles" / session_id
        (self.dir / "storage").mkdir(parents=True, exist_ok=True)
        (self.dir / "cache").mkdir(parents=True, exist_ok=True)
        (self.dir / "downloads").mkdir(parents=True, exist_ok=True)

        self.profile = QWebEngineProfile(f"dsm-{session_id}", self)
        self.profile.setPersistentStoragePath(str(self.dir / "storage"))
        self.profile.setCachePath(str(self.dir / "cache"))
        self.profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.DiskHttpCache)
        self.profile.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies
        )
        self.profile.setHttpUserAgent(settings.user_agent)
        self.profile.setHttpAcceptLanguage("ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7")
        self.profile.setDownloadPath(str(self.dir / "downloads"))
        self.profile.downloadRequested.connect(self._on_download)
        self.interceptor = ChromeHintsInterceptor(self)
        self.profile.setUrlRequestInterceptor(self.interceptor)

        s = self.profile.settings()
        for attr, value in (
            (QWebEngineSettings.WebAttribute.LocalStorageEnabled, True),
            (QWebEngineSettings.WebAttribute.JavascriptCanAccessClipboard, True),
            (QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, True),
            (QWebEngineSettings.WebAttribute.FullScreenSupportEnabled, True),
            (QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, False),
            (QWebEngineSettings.WebAttribute.ScrollAnimatorEnabled, True),
        ):
            try:
                s.setAttribute(attr, value)
            except Exception:
                pass

        script = QWebEngineScript()
        script.setName("dsm-monitor")
        script.setSourceCode(MONITOR_JS)
        script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
        script.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
        script.setRunsOnSubFrames(False)
        self.profile.scripts().insert(script)

    def _on_download(self, item) -> None:
        try:
            name = item.downloadFileName() or item.suggestedFileName() or "download"
            item.setDownloadDirectory(str(self.dir / "downloads"))
            item.setDownloadFileName(name)
            item.accept()
            self.download_started.emit(name)
        except Exception:
            item.accept()

    def dispose(self) -> None:
        self.profile.deleteLater()
        self.deleteLater()


def make_view(runtime: SessionRuntime, owner) -> QWebEngineView:
    view = QWebEngineView()
    page = WebPage(runtime.profile, view, owner=owner)
    view.setPage(page)
    return view


def dir_size_bytes(path: Path) -> int:
    total = 0
    try:
        for p in Path(path).rglob("*"):
            try:
                if p.is_file():
                    total += p.stat().st_size
            except OSError:
                pass
    except OSError:
        pass
    return total


def human_size(num: int) -> str:
    if num < 1024:
        return f"{num} Б"
    if num < 1024 * 1024:
        return f"{num / 1024:.0f} КБ"
    if num < 1024 * 1024 * 1024:
        return f"{num / (1024 * 1024):.1f} МБ"
    return f"{num / (1024 * 1024 * 1024):.2f} ГБ"


def retire_dir(path: Path, trash: Path) -> bool:
    """Move a profile folder to trash and try to erase it. True if it is gone."""
    trash.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        return True
    dest = trash / f"{int(time.time() * 1000)}-{path.name}"
    try:
        path.rename(dest)
    except OSError:
        shutil.rmtree(path, ignore_errors=True)
        return not path.exists()
    shutil.rmtree(dest, ignore_errors=True)
    return True


def purge_trash(trash: Path) -> None:
    if not trash.exists():
        return
    for child in trash.iterdir():
        try:
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)
        except OSError:
            pass
