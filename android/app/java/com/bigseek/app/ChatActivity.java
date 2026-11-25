package com.bigseek.app;

import android.app.Activity;
import android.app.AlertDialog;
import android.app.Dialog;
import android.app.DownloadManager;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.os.Handler;
import android.os.Looper;
import android.os.Message;
import android.util.Log;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.CookieManager;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebStorage;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.webkit.WebViewDatabase;
import android.webkit.URLUtil;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;

import org.json.JSONObject;
import org.json.JSONTokener;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.util.ArrayList;
import java.util.List;

/** One isolated browser session. Each subclass runs in its own process. */
public abstract class ChatActivity extends Activity {
    /** The WebView data dir suffix can be set only once per process. */
    private static boolean sDataDirSet = false;

    protected abstract int slot();

    private Prefs prefs;
    private Store.Session session;
    private WebView web;
    private TextView titleView;
    private TextView chip;
    private LinearLayout banner;
    private TextView bannerTitle;
    private TextView bannerText;
    private TextView bannerReset;
    private TextView bannerTransfer;
    private TextView bannerClose;
    private ProgressBar loadBar;

    private final Handler handler = new Handler(Looper.getMainLooper());
    private Runnable pollTask;
    private String monitorJs = "";
    private String driverJs = "";

    private long lastSave = 0;
    private String dismissedState = "";
    private String pendingSend = null;

    private boolean transferRunning = false;
    private boolean autoTransferDone = false;
    private int transferAttempts = 0;
    private int baselineLen = 0;
    private long replyStarted = 0;
    private long replyDeadline = 0;
    private int prevReplyLen = 0;
    private String prevReplyTail = "";
    private long replySig = -1;
    private long stableSince = 0;
    private String summary = "";
    private String targetId = null;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        boolean preload = getIntent().getBooleanExtra("preload", false);
        if (preload) {
            setTheme(android.R.style.Theme_Translucent_NoTitleBar);
        }
        if (!sDataDirSet) {
            try {
                if (Build.VERSION.SDK_INT >= 28) {
                    WebView.setDataDirectorySuffix("s" + slot());
                }
            } catch (IllegalStateException ignored) {
                // WebView was initialized earlier in this process (activity recreated
                // after the system destroyed it) - the suffix is already in place.
            }
            sDataDirSet = true;
        }
        super.onCreate(savedInstanceState);

        if (preload) {
            runPreload();
            return;
        }

        prefs = Prefs.load(this);
        String sid = getIntent().getStringExtra("sessionId");
        session = sid == null ? Store.bySlot(this, slot()) : Store.byId(this, sid);
        if (session == null) {
            finish();
            return;
        }

        setContentView(R.layout.activity_chat);
        getWindow().setStatusBarColor(Color.BLACK);
        getWindow().setNavigationBarColor(Color.BLACK);

        monitorJs = readAsset("monitor.js");
        driverJs = readAsset("driver.js");
        bindViews();
        setupWeb();

        boolean clearOnly = getIntent().getBooleanExtra("clearOnly", false);
        boolean wipe = Store.takeWipe(this, slot());
        if (wipe || clearOnly) {
            clearWebData();
        }
        if (clearOnly) {
            Ui.toast(this, "Данные сессии очищены");
            finish();
            return;
        }

        pendingSend = getIntent().getStringExtra("resume");
        String testPage = getIntent().getStringExtra("testPage");
        if (testPage != null) {
            // Test pages are served under a fake chat URL so the monitor sees a
            // real conversation id (the home screen is intentionally ignored).
            String base = prefs.domain + "a/chat/s/test-" + slot();
            web.loadDataWithBaseURL(base, mockPage(testPage), "text/html", "UTF-8", null);
        } else {
            web.loadUrl(pendingSend != null ? prefs.domain : startUrl());
        }

        pollTask = () -> {
            poll();
            handler.postDelayed(pollTask, prefs.pollSeconds * 1000L);
        };
    }

    @Override
    protected void onStart() {
        super.onStart();
        if (pollTask != null) {
            handler.postDelayed(pollTask, 1200);
        }
    }

    @Override
    protected void onStop() {
        handler.removeCallbacks(pollTask);
        saveNow(true);
        super.onStop();
    }

    @Override
    protected void onDestroy() {
        handler.removeCallbacksAndMessages(null);
        saveNow(true);
        if (web != null) {
            try {
                web.destroy();
            } catch (Exception ignored) {
            }
            web = null;
        }
        super.onDestroy();
    }

    @Override
    public void onBackPressed() {
        saveNow(true);
        finish();
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);

        String newSid = intent.getStringExtra("sessionId");
        if (newSid != null && (session == null || !newSid.equals(session.id))) {
            Store.Session fresh = Store.byId(this, newSid);
            if (fresh != null) {
                saveNow(true);
                session = fresh;
                updateHeader();
                if (web != null) {
                    web.loadUrl(startUrl());
                }
            }
        }

        boolean wipe = Store.takeWipe(this, slot());
        boolean clearOnly = intent.getBooleanExtra("clearOnly", false);
        if (wipe || clearOnly) {
            clearWebData();
        }
        if (clearOnly) {
            Ui.toast(this, "Данные сессии очищены");
            finish();
            return;
        }
        if (wipe && web != null) {
            web.loadUrl(prefs.domain);
        }

        String resume = intent.getStringExtra("resume");
        if (resume != null) {
            pendingSend = null;
            if (web != null) {
                web.loadUrl(prefs.domain);
            }
            waitComposerThenSend(resume);
        }
    }

    // ------------------------------------------------------------- preload
    private String mockPage(String mode) {
        if ("vlist".equals(mode)) {
            // Reproduces the virtual list of the real chat: only three rows
            // are in the DOM and the window slides, so the old counter froze.
            return "<!doctype html><html><head><meta name='viewport' "
                    + "content='width=device-width, initial-scale=1'></head>"
                    + "<body style='background:#0b0b0b;color:#e6e6e6;font:16px sans-serif;padding:16px'>"
                    + "<div id='list'></div><script>"
                    + "var all=[];for(var i=1;i<=30;i++){var t='';"
                    + "for(var j=0;j<10+i*3;j++){t+='Сообщение '+i+' текст для объёма. ';}"
                    + "all.push(\"<div data-virtual-list-item-key='\"+i+\"'><div class='ds-message'>\"+t+\"</div></div>\");}"
                    + "var off=0;function render(){document.getElementById('list').innerHTML=all.slice(off,off+3).join('');}"
                    + "render();setInterval(function(){off=(off+1)%28;render();},3000);"
                    + "</script></body></html>";
        }
        int repeats = "warn".equals(mode) ? 4200 : 260;
        StringBuilder longText = new StringBuilder();
        for (int i = 0; i < repeats; i++) {
            longText.append("Это длинный тестовый текст для проверки счётчика контекста. ");
        }
        String body = "<div class='ds-message'>Привет! Помоги с проверкой приложения.</div>"
                + "<div class='ds-message'>" + longText + "</div>";
        if ("limit".equals(mode)) {
            body += "<div class='ds-message'>Достигнут лимит сообщений, сброс в 23:59</div>";
        } else {
            body += "<div class='ds-message'>Ещё один ответ ассистента для объёма.</div>";
        }
        return "<!doctype html><html><head><meta name='viewport' "
                + "content='width=device-width, initial-scale=1'></head>"
                + "<body style='background:#0b0b0b;color:#e6e6e6;font:16px sans-serif;padding:16px'>"
                + body + "</body></html>";
    }

    private void runPreload() {
        prefs = Prefs.load(this);
        final WebView warm = new WebView(this);
        warm.setAlpha(0f);
        WebSettings settings = warm.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        CookieManager cookies = CookieManager.getInstance();
        cookies.setAcceptCookie(true);
        cookies.setAcceptThirdPartyCookies(warm, true);

        final boolean[] closed = {false};
        Runnable close = () -> {
            if (closed[0]) {
                return;
            }
            closed[0] = true;
            Log.d("BigSeek", "preload: done slot " + slot());
            try {
                warm.destroy();
            } catch (Exception ignored) {
            }
            setResult(RESULT_OK);
            finish();
        };
        warm.setWebViewClient(new WebViewClient() {
            @Override
            public void onPageFinished(WebView view, String url) {
                close.run();
            }
        });
        setContentView(warm, new ViewGroup.LayoutParams(1, 1));
        warm.loadUrl(prefs.domain);
        handler.postDelayed(close, 15000);
    }

    // ------------------------------------------------------------------- UI
    private void bindViews() {
        titleView = findViewById(R.id.title);
        titleView.setText(session.name);
        chip = findViewById(R.id.chip);
        int chipWidth = (int) Math.ceil(chip.getPaint().measureText(
                String.valueOf(prefs.contextLimit) + "0/" + Ui.humanTokens(prefs.contextLimit)))
                + Ui.dp(this, 24);
        chip.setMinWidth(chipWidth);
        chip.setMaxWidth(chipWidth);

        banner = findViewById(R.id.banner);
        bannerTitle = findViewById(R.id.bannerTitle);
        bannerText = findViewById(R.id.bannerText);
        bannerReset = findViewById(R.id.bannerReset);
        bannerTransfer = findViewById(R.id.bannerTransfer);
        bannerClose = findViewById(R.id.bannerClose);
        loadBar = findViewById(R.id.load);

        int resetWidth = (int) Math.ceil(bannerReset.getPaint().measureText("Сбросить счётчик"))
                + Ui.dp(this, 26);
        bannerReset.setMinWidth(resetWidth);

        findViewById(R.id.btnClose).setOnClickListener(v -> finish());
        findViewById(R.id.btnMenu).setOnClickListener(v -> openMenu());
        bannerClose.setOnClickListener(v -> {
            dismissedState = Ui.effectiveState(session, prefs);
            banner.setVisibility(View.GONE);
        });
        bannerTransfer.setOnClickListener(v -> openTransferDialog());
        bannerReset.setOnClickListener(v -> {
            if ("warn".equals(Ui.effectiveState(session, prefs))) {
                resetTokens();
            } else {
                resetStatus();
            }
        });

        updateHeader();
    }

    private void setupWeb() {
        web = findViewById(R.id.web);
        web.setBackgroundColor(Color.BLACK);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setDatabaseEnabled(true);
        s.setUseWideViewPort(true);
        s.setLoadWithOverviewMode(true);
        s.setSupportZoom(false);
        s.setBuiltInZoomControls(false);
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE);
        s.setSupportMultipleWindows(true);
        s.setJavaScriptCanOpenWindowsAutomatically(true);
        s.setUserAgentString("Mozilla/5.0 (Linux; Android 14; 2201117SY) "
                + "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Mobile Safari/537.36");

        CookieManager cookies = CookieManager.getInstance();
        cookies.setAcceptCookie(true);
        cookies.setAcceptThirdPartyCookies(web, true);

        web.setWebViewClient(new WebViewClient() {
            @Override
            public void onPageStarted(WebView view, String url, android.graphics.Bitmap favicon) {
                loadBar.setVisibility(View.VISIBLE);
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                loadBar.setVisibility(View.GONE);
                Log.d("BigSeek", "loaded " + url);
                saveUrl(url);
                onPageReady();
            }

            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri uri = request.getUrl();
                String scheme = uri.getScheme() == null ? "" : uri.getScheme();
                if (scheme.equals("http") || scheme.equals("https")) {
                    return false;
                }
                try {
                    startActivity(new Intent(Intent.ACTION_VIEW, uri));
                } catch (Exception ignored) {
                }
                return true;
            }
        });

        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onCreateWindow(WebView view, boolean isDialog, boolean isUserGesture,
                                          Message resultMsg) {
                WebView popup = new WebView(ChatActivity.this);
                WebSettings ps = popup.getSettings();
                ps.setJavaScriptEnabled(true);
                ps.setDomStorageEnabled(true);
                ps.setSupportMultipleWindows(false);
                CookieManager.getInstance().setAcceptThirdPartyCookies(popup, true);
                popup.setWebViewClient(new WebViewClient());
                WebView.WebViewTransport transport = (WebView.WebViewTransport) resultMsg.obj;
                transport.setWebView(popup);
                resultMsg.sendToTarget();

                Dialog dialog = new Dialog(ChatActivity.this);
                dialog.setTitle("Вход");
                dialog.setContentView(popup, new ViewGroup.LayoutParams(
                        ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
                dialog.setOnDismissListener(d -> {
                    try {
                        popup.destroy();
                    } catch (Exception ignored) {
                    }
                });
                dialog.show();
                return true;
            }
        });

        web.setDownloadListener((url, userAgent, contentDisposition, mimeType, contentLength) -> {
            try {
                DownloadManager.Request request = new DownloadManager.Request(Uri.parse(url));
                request.setNotificationVisibility(
                        DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
                request.setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS,
                        URLUtil.guessFileName(url, contentDisposition, mimeType));
                DownloadManager manager = (DownloadManager) getSystemService(DOWNLOAD_SERVICE);
                manager.enqueue(request);
                Ui.toast(this, "Скачивание началось");
            } catch (Exception e) {
                Ui.toast(this, "Не удалось скачать файл");
            }
        });
    }

    private String startUrl() {
        String url = session.lastUrl == null ? "" : session.lastUrl;
        String host = Uri.parse(prefs.domain).getHost();
        if (url.startsWith("http") && host != null && url.contains(host)) {
            return url;
        }
        return prefs.domain;
    }

    private void saveUrl(String url) {
        if (url == null || !url.startsWith("http")) {
            return;
        }
        String host = Uri.parse(prefs.domain).getHost();
        if (host == null || !url.contains(host)) {
            return;
        }
        session.lastUrl = url;
        saveNow(false);
    }

    private void onPageReady() {
        scanNow();
        evaluate("String(window.__bs.hasComposer())",
                value -> Log.d("BigSeek", "composer=" + value));
        if (pendingSend != null) {
            String text = pendingSend;
            pendingSend = null;
            waitComposerThenSend(text);
        }
    }

    // -------------------------------------------------------------- monitor
    private void poll() {
        if (web == null || transferRunning) {
            return;
        }
        scanNow();
    }

    private void scanNow() {
        if (web == null) {
            return;
        }
        web.evaluateJavascript(
                monitorJs + "; JSON.stringify(window.__bsmScan ? window.__bsmScan() : null)",
                value -> onScan(parseJson(value)));
    }

    private void onScan(JSONObject result) {
        if (result == null || session == null) {
            return;
        }
        Log.d("BigSeek", "scan " + result);
        long now = System.currentTimeMillis();

        // The site gives an exact reset time, but a transferred ("перенесена")
        // session has none; the configurable timeout releases it too.
        if (Ui.autoResetDue(session, prefs)) {
            Ui.autoResetSession(session);
            autoTransferDone = false;
            dismissedState = "";
        }

        if (result.optBoolean("measured", false)) {
            long chars = result.optLong("chars", 0);
            // Per-chat peaks: writing a message or switching chats must never
            // roll the session counter back. Tokens only grow until a reset.
            // The chat is virtualised, so every rendered row is remembered by
            // its key; otherwise the counter freezes when the window slides.
            session.measureContext(chars, Ui.chatKey(result.optString("url", "")),
                    result.optJSONObject("items"));
            int messages = result.optInt("messages", 0);
            if (messages > session.usageCount) {
                session.usageCount = messages;
            }
        }

        if (prefs.detectLimits) {
            String phrase = result.optString("phrase", "");
            long phraseAt = result.optLong("phraseAt", 0);
            if (!phrase.isEmpty() && phraseAt > session.statusAt) {
                session.status = "blocked";
                session.statusReason = "«" + Ui.ellipsize(phrase, 70) + "»";
                session.statusAt = now;
            }
            long resetAt = result.optLong("resetAt", 0);
            if (resetAt > now - 5000 && resetAt < now + 8L * 86400000L) {
                session.limitResetAt = resetAt;
            }
        }

        updateHeader();
        updateBanner();
        maybeAutoTransfer();
        saveNow(false);
    }

    private void updateHeader() {
        if (session == null) {
            return;
        }
        String state = Ui.effectiveState(session, prefs);
        String used = session.measured() ? Ui.group(session.usedTokens()) : "—";
        chip.setText(used + "/" + Ui.humanTokens(prefs.contextLimit));
        if ("blocked".equals(state)) {
            chip.setBackgroundResource(R.drawable.bg_pill_danger);
            chip.setTextColor(Color.BLACK);
        } else if ("warn".equals(state) || "limited".equals(state)) {
            chip.setBackgroundResource(R.drawable.bg_pill_warn);
            chip.setTextColor(Color.WHITE);
        } else {
            chip.setBackgroundResource(R.drawable.bg_pill);
            chip.setTextColor(0xFFD0D0D0);
        }
        titleView.setText(session.name);
    }

    private void updateBanner() {
        if (transferRunning) {
            return;
        }
        String state = Ui.effectiveState(session, prefs);
        boolean show = "warn".equals(state) || "limited".equals(state) || "blocked".equals(state);
        if (!show || state.equals(dismissedState)) {
            banner.setVisibility(View.GONE);
            return;
        }
        banner.setBackgroundResource("blocked".equals(state)
                ? R.drawable.bg_banner_danger : R.drawable.bg_banner);
        String limit = Ui.humanTokens(prefs.contextLimit);
        String resetHint = Ui.resetHint(session.limitResetAt);
        switch (state) {
            case "blocked":
                bannerTitle.setText("Сессия недоступна — лимит исчерпан");
                bannerText.setText("«" + session.name + "» больше не может отправлять сообщения."
                        + (session.statusReason.isEmpty() ? "" : " Причина: " + session.statusReason + ".")
                        + (resetHint.isEmpty() ? "" : " Ожидаемый сброс: " + resetHint.replace("сброс ", "") + "."));
                bannerReset.setText("Сбросить статус");
                break;
            case "limited":
                bannerTitle.setText("Временное ограничение запросов");
                bannerText.setText("«" + session.name + "»: сервер ответил 429 (слишком много запросов). "
                        + "Подожди пару минут."
                        + (resetHint.isEmpty() ? "" : " " + resetHint + "."));
                bannerReset.setText("Сбросить статус");
                break;
            default:
                bannerTitle.setText("Контекст подходит к концу");
                bannerText.setText("«" + session.name + "»: ~" + Ui.group(session.usedTokens())
                        + " из " + limit + " токенов. Самое время упаковать контекст, "
                        + "пока сессия ещё отвечает.");
                bannerReset.setText("Сбросить счётчик");
                break;
        }
        bannerReset.setVisibility(View.VISIBLE);
        // Transfer needs a working composer; for a blocked or rate-limited
        // session the reset action is the only useful one.
        boolean canTransfer = "warn".equals(state);
        bannerTransfer.setVisibility(canTransfer ? View.VISIBLE : View.GONE);
        bannerClose.setVisibility(View.VISIBLE);
        banner.setVisibility(View.VISIBLE);
    }

    // ---------------------------------------------------------------- menu
    private void openMenu() {
        String[] items = {
                "Переименовать…",
                "Сбросить счётчик токенов",
                "Сбросить статус",
                "Перенести контекст…",
                "Очистить данные сайта…",
                "Назад по истории",
                "Закрыть сессию"
        };
        Ui.appDialog(this)
                .title(session.name)
                .items(items, which -> {
                    switch (which) {
                        case 0:
                            renameSession();
                            break;
                        case 1:
                            resetTokens();
                            break;
                        case 2:
                            resetStatus();
                            break;
                        case 3:
                            openTransferDialog();
                            break;
                        case 4:
                            clearData();
                            break;
                        case 5:
                            if (web != null && web.canGoBack()) {
                                web.goBack();
                            }
                            break;
                        default:
                            finish();
                            break;
                    }
                })
                .negative("Закрыть")
                .show();
    }

    private void renameSession() {
        EditText input = new EditText(this);
        input.setText(session.name);
        input.setTextSize(14);
        input.setTextColor(Color.WHITE);
        input.setBackgroundResource(R.drawable.bg_input);
        input.setPadding(Ui.dp(this, 12), Ui.dp(this, 10), Ui.dp(this, 12), Ui.dp(this, 10));
        Ui.appDialog(this)
                .title("Переименовать сессию")
                .view(input)
                .positive("Сохранить", () -> {
                    String value = input.getText().toString().trim();
                    if (!value.isEmpty()) {
                        session.name = value.length() > 60 ? value.substring(0, 60) : value;
                        updateHeader();
                        saveNow(true);
                    }
                })
                .negative("Отмена")
                .show();
    }

    private void resetTokens() {
        session.contextBaseChars = session.contextChars;
        session.contextResetAt = System.currentTimeMillis();
        autoTransferDone = false;
        dismissedState = "";
        updateHeader();
        updateBanner();
        saveNow(true);
        Ui.toast(this, "Счётчик токенов сброшен");
    }

    private void resetStatus() {
        session.status = "ok";
        session.statusReason = "";
        session.statusAt = System.currentTimeMillis();
        session.limitResetAt = 0;
        dismissedState = "";
        updateHeader();
        updateBanner();
        saveNow(true);
        Ui.toast(this, "Статус сессии сброшен");
    }

    private void clearData() {
        Ui.appDialog(this)
                .title("Очистить данные сайта")
                .message("Удалить cookies, вход и хранилище сайта для сессии «"
                        + session.name + "»?")
                .positive("Очистить", () -> {
                    clearWebData();
                    session.status = "ok";
                    session.statusReason = "";
                    session.limitResetAt = 0;
                    session.contextChars = 0;
                    session.contextTokens = 0;
                    session.contextBaseChars = 0;
                    session.contextChats = "{}";
                    session.contextItems = "{}";
                    session.contextChat = "";
                    session.lastUrl = "";
                    autoTransferDone = false;
                    dismissedState = "";
                    saveNow(true);
                    if (web != null) {
                        web.loadUrl(prefs.domain);
                    }
                    updateHeader();
                    Ui.toast(this, "Данные очищены");
                })
                .negative("Отмена")
                .show();
    }

    private void clearWebData() {
        try {
            CookieManager.getInstance().removeAllCookies(null);
            CookieManager.getInstance().flush();
            WebStorage.getInstance().deleteAllData();
            WebViewDatabase db = WebViewDatabase.getInstance(this);
            db.clearFormData();
            db.clearHttpAuthUsernamePassword();
            if (web != null) {
                web.clearHistory();
                web.clearCache(true);
            }
        } catch (Exception ignored) {
        }
    }

    // ------------------------------------------------------------- transfer
    /** Move the context once, as soon as the chat passes the configured percent. */
    private void maybeAutoTransfer() {
        if (!prefs.autoTransfer || transferRunning || autoTransferDone || session == null) {
            return;
        }
        int limit = prefs.contextLimit;
        int percent = Math.max(1, Math.min(99, prefs.autoTransferPercent));
        if (limit <= 0 || session.usedTokens() < Math.round(limit * (percent / 100.0))) {
            return;
        }
        if ("blocked".equals(session.status) || "limited".equals(session.status)
                || "exhausted".equals(session.status)) {
            return;
        }
        Store.Session target = pickAutoTarget();
        if (target == null) {
            return;
        }
        autoTransferDone = true;
        Ui.toast(this, "Контекст заполнен на " + percent + "% — переношу автоматически");
        startTransfer(target);
    }

    /** Least loaded session that can accept the context; a new one if none. */
    private Store.Session pickAutoTarget() {
        List<Store.Session> list = Store.load(this);
        Store.Session best = null;
        for (Store.Session s : list) {
            if (s.id.equals(session.id) || "blocked".equals(s.status)
                    || "exhausted".equals(s.status) || "limited".equals(s.status)) {
                continue;
            }
            if (best == null || s.usedTokens() < best.usedTokens()) {
                best = s;
            }
        }
        if (best == null && list.size() < Store.SLOTS) {
            best = Store.create(this, list, Store.nextName(list));
            if (best != null) {
                Store.save(this, list);
            }
        }
        return best;
    }

    private void openTransferDialog() {
        String state = Ui.effectiveState(session, prefs);
        if ("blocked".equals(state) || "limited".equals(state)) {
            Ui.toast(this, "Сессия недоступна — перенос не сработает, пока действует лимит");
            return;
        }
        List<Store.Session> all = Store.load(this);
        List<Store.Session> targets = new ArrayList<>();
        for (Store.Session s : all) {
            if (!s.id.equals(session.id)
                    && !"blocked".equals(s.status)
                    && !"exhausted".equals(s.status)) {
                targets.add(s);
            }
        }
        String[] names = new String[targets.size() + 1];
        for (int i = 0; i < targets.size(); i++) {
            Store.Session s = targets.get(i);
            names[i] = s.name + " — ≈" + Ui.group(s.usedTokens()) + " токенов";
        }
        names[targets.size()] = "＋ Создать новую сессию";

        Ui.appDialog(this)
                .title("Перенести контекст")
                .items(names, which -> {
                    Store.Session target;
                    if (which == targets.size()) {
                        List<Store.Session> list = Store.load(this);
                        if (list.size() >= Store.SLOTS) {
                            Ui.toast(this, "Можно создать не больше " + Store.SLOTS + " сессий");
                            return;
                        }
                        target = Store.create(this, list, Store.nextName(list));
                        if (target == null) {
                            Ui.toast(this, "Нет свободного слота");
                            return;
                        }
                        Store.save(this, list);
                    } else {
                        target = targets.get(which);
                    }
                    startTransfer(target);
                })
                .negative("Отмена")
                .show();
    }

    private void startTransfer(Store.Session target) {
        if (transferRunning) {
            return;
        }
        Log.d("BigSeek", "transfer: start, target=" + target.name);
        targetId = target.id;
        summary = "";
        transferAttempts = 0;
        transferRunning = true;
        dismissedState = "";

        banner.setBackgroundResource(R.drawable.bg_banner);
        bannerTitle.setText("Автоперенос");
        bannerText.setText("Отправляю промт сжатия в «" + session.name + "»…");
        bannerReset.setVisibility(View.GONE);
        bannerTransfer.setVisibility(View.GONE);
        bannerClose.setVisibility(View.GONE);
        banner.setVisibility(View.VISIBLE);

        String compact = Prompts.compaction(session.name, session.usedTokens(),
                prefs.contextLimit, Ui.dateRu());

        evaluate("JSON.stringify(window.__bs.state())", raw -> {
            JSONObject state = parseJson(raw);
            if (state != null) {
                prevReplyLen = state.optInt("replyLen", 0);
                prevReplyTail = state.optString("replyTail", "");
            }
            sendMessage(compact, this::waitReply, true);
        });
    }

    private void sendMessage(String text, Runnable onSent, boolean transfer) {
        evaluate("JSON.stringify(window.__bs.state())", raw -> {
            JSONObject state = parseJson(raw);
            baselineLen = state == null ? 0 : state.optInt("len", 0);
            evaluate("String(window.__bs.setText(" + JSONObject.quote(text) + "))", ok -> {
                if (!"true".equals(unquote(ok))) {
                    fail("Не удалось вставить текст в поле ввода.", transfer);
                    return;
                }
                handler.postDelayed(() -> {
                    evaluate("window.__bs.pressEnter()", ignored -> {
                    });
                    handler.postDelayed(() -> verifySent(text, onSent, 0, transfer), 1400);
                }, 350);
            });
        });
    }

    private void verifySent(String text, Runnable onSent, int attempt, boolean transfer) {
        evaluate("JSON.stringify(window.__bs.state())", raw -> {
            JSONObject state = parseJson(raw);
            if (state == null) {
                fail("Страница перестала отвечать.", transfer);
                return;
            }
            String composer = state.optString("composer", "");
            int length = state.optInt("len", 0);
            boolean grew = length >= baselineLen + Math.min(text.length(), 120);
            if (composer.trim().isEmpty() || grew) {
                Log.d("BigSeek", "transfer: message sent (transfer=" + transfer + ")");
                onSent.run();
                return;
            }
            if (attempt == 0) {
                evaluate("window.__bs.clickSend()", ignored -> {
                });
                handler.postDelayed(() -> verifySent(text, onSent, 1, transfer), 1400);
                return;
            }
            fail("Не удалось отправить сообщение: поле ввода не очистилось.", transfer);
        });
    }

    private void waitReply() {
        replyStarted = System.currentTimeMillis();
        replyDeadline = replyStarted + 300_000;
        replySig = -1;
        stableSince = 0;
        pollReply();
    }

    private void pollReply() {
        if (!transferRunning) {
            return;
        }
        long now = System.currentTimeMillis();
        evaluate("JSON.stringify(window.__bs.state())", raw -> {
            JSONObject state = parseJson(raw);
            if (state == null) {
                if (System.currentTimeMillis() - replyStarted > 15000) {
                    fail("Страница перестала отвечать — не удалось дождаться ответа.", true);
                } else {
                    handler.postDelayed(this::pollReply, 800);
                }
                return;
            }
            int replyLen = state.optInt("replyLen", 0);
            String replyTail = state.optString("replyTail", "");
            boolean replyEnd = state.optBoolean("replyEnd", false);
            boolean stop = state.optBoolean("stop", false);
            boolean isNew = replyLen > 0
                    && (replyLen != prevReplyLen || !replyTail.equals(prevReplyTail));

            long sig = replyLen * 31L + replyTail.hashCode();
            if (sig != replySig) {
                replySig = sig;
                stableSince = now;
            }
            long quiet = stableSince == 0 ? 0 : now - stableSince;
            long elapsed = now - replyStarted;
            boolean ready = isNew && replyLen >= 80
                    && quiet >= (replyEnd ? 1200 : 3000)
                    && elapsed >= 2500
                    && (replyEnd || !stop);

            if (ready) {
                Log.d("BigSeek", "transfer: reply ready, len=" + replyLen);
                extractSummary();
                return;
            }
            if (now >= replyDeadline) {
                Log.d("BigSeek", "transfer: reply timeout");
                extractSummary();
                return;
            }
            if (elapsed % 4000 < 800) {
                bannerText.setText("Ассистент готовит конспект… " + (elapsed / 1000) + " с");
            }
            handler.postDelayed(this::pollReply, 700);
        });
    }

    private void extractSummary() {
        bannerText.setText("Извлекаю конспект из ответа…");
        String anchor = "";
        String compact = Prompts.compaction(session.name, session.usedTokens(),
                prefs.contextLimit, Ui.dateRu());
        String[] lines = compact.trim().split("\n");
        for (int i = lines.length - 1; i >= 0; i--) {
            if (!lines[i].trim().isEmpty()) {
                String line = lines[i].trim();
                anchor = line.length() > 160 ? line.substring(line.length() - 160) : line;
                break;
            }
        }
        evaluate("JSON.stringify(window.__bs.extract('КОНСПЕКТ','КОНЕЦ',"
                + JSONObject.quote(anchor) + "))", raw -> {
            JSONObject result = parseJson(raw);
            String text = result == null ? "" : result.optString("text", "");
            boolean found = result != null && result.optBoolean("found", false);
            if (!found || text.length() < 80) {
                if (transferAttempts < 2) {
                    transferAttempts++;
                    bannerText.setText("Конспект пока не виден — жду ещё немного…");
                    handler.postDelayed(this::waitReply, 1500);
                    return;
                }
                fail("В ответе не нашёлся блок конспекта (маркеры ===КОНСПЕКТ=== … ===КОНЕЦ===).", true);
                return;
            }
            summary = text;
            Log.d("BigSeek", "transfer: summary extracted, chars=" + text.length());
            finishTransfer();
        });
    }

    private void finishTransfer() {
        Store.Session target = Store.byId(this, targetId);
        if (target == null) {
            fail("Целевая сессия не найдена.", true);
            return;
        }
        session.status = "exhausted";
        session.statusReason = "контекст перенесён";
        session.statusAt = System.currentTimeMillis();
        saveNow(true);

        String resume = Prompts.resume(target.name, Ui.dateRu())
                .replace(Prompts.SUMMARY_PLACEHOLDER, summary);
        Log.d("BigSeek", "transfer: opening target " + target.name);
        Intent intent = new Intent(this, Ui.sessionClass(target.slot));
        intent.putExtra("sessionId", target.id);
        intent.putExtra("resume", resume);
        transferRunning = false;
        startActivity(intent);
    }

    private void waitComposerThenSend(String text) {
        long deadline = System.currentTimeMillis() + 45000;
        Runnable[] check = new Runnable[1];
        check[0] = () -> {
            if (isFinishing() || web == null) {
                return;
            }
            evaluate("String(window.__bs.hasComposer())", raw -> {
                if ("true".equals(unquote(raw))) {
                    banner.setBackgroundResource(R.drawable.bg_banner);
                    bannerTitle.setText("Перенос контекста");
                    bannerText.setText("Отправляю конспект в «" + session.name + "»…");
                    bannerReset.setVisibility(View.GONE);
                    bannerTransfer.setVisibility(View.GONE);
                    bannerClose.setVisibility(View.GONE);
                    banner.setVisibility(View.VISIBLE);
                    Log.d("BigSeek", "transfer: target composer ready, sending resume");
                    sendMessage(text, () -> {
                        banner.setVisibility(View.GONE);
                        Log.d("BigSeek", "transfer: resume sent");
                        Ui.toast(this, "Конспект отправлен");
                    }, false);
                } else if (System.currentTimeMillis() < deadline) {
                    banner.setBackgroundResource(R.drawable.bg_banner);
                    bannerTitle.setText("Перенос контекста");
                    bannerText.setText("Открываю новый чат…");
                    bannerReset.setVisibility(View.GONE);
                    bannerTransfer.setVisibility(View.GONE);
                    bannerClose.setVisibility(View.GONE);
                    banner.setVisibility(View.VISIBLE);
                    handler.postDelayed(check[0], 600);
                } else {
                    banner.setVisibility(View.GONE);
                    Ui.toast(this, "Не нашёл поле ввода — откройте чат и повторите");
                }
            });
        };
        handler.postDelayed(check[0], 800);
    }

    private void fail(String message, boolean transfer) {
        Log.d("BigSeek", "transfer: fail (" + transfer + ") " + message);
        transferRunning = false;
        banner.setVisibility(View.GONE);
        if (transfer) {
            Ui.appDialog(this)
                    .title("Перенос контекста")
                    .message(message)
                    .positive("Ок", null)
                    .show();
        } else {
            Ui.toast(this, message);
        }
    }

    // -------------------------------------------------------------- helpers
    private void evaluate(String code, java.util.function.Consumer<String> callback) {
        if (web == null) {
            return;
        }
        web.evaluateJavascript(driverJs + ";" + code, value -> {
            if (callback != null) {
                callback.accept(value);
            }
        });
    }

    private static String unquote(String value) {
        if (value == null) {
            return "";
        }
        String v = value.trim();
        if (v.length() >= 2 && v.startsWith("\"") && v.endsWith("\"")) {
            try {
                return String.valueOf(new JSONTokener(v).nextValue());
            } catch (Exception ignored) {
            }
        }
        return v;
    }

    private static JSONObject parseJson(String value) {
        if (value == null) {
            return null;
        }
        String v = value.trim();
        if (v.isEmpty() || v.equals("null") || v.equals("undefined")) {
            return null;
        }
        try {
            Object inner = new JSONTokener(v).nextValue();
            if (inner instanceof String) {
                String text = (String) inner;
                if (text.trim().isEmpty() || text.trim().equals("null")) {
                    return null;
                }
                return new JSONObject(text);
            }
            if (inner instanceof JSONObject) {
                return (JSONObject) inner;
            }
        } catch (Exception ignored) {
        }
        return null;
    }

    private String readAsset(String name) {
        try (InputStream in = getAssets().open(name)) {
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            byte[] buffer = new byte[8192];
            int read;
            while ((read = in.read(buffer)) > 0) {
                out.write(buffer, 0, read);
            }
            return out.toString("UTF-8");
        } catch (Exception e) {
            return "";
        }
    }

    private void saveNow(boolean force) {
        if (session == null) {
            return;
        }
        long now = System.currentTimeMillis();
        if (!force && now - lastSave < 1200) {
            return;
        }
        lastSave = now;
        session.updatedAt = now;
        Store.update(this, session);
    }
}
