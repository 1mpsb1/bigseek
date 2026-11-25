package com.bigseek.app;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Color;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.CheckBox;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.TextView;

import java.util.Comparator;
import java.util.List;
import java.util.Locale;

public class MainActivity extends Activity {
    private static final String VERSION = "1.0.1";

    private Prefs prefs;
    private LinearLayout list;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private boolean firstResume = true;
    private boolean stopPreload = false;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);
        getWindow().setStatusBarColor(Color.BLACK);
        getWindow().setNavigationBarColor(Color.BLACK);

        prefs = Prefs.load(this);
        list = findViewById(R.id.list);

        List<Store.Session> sessions = Store.load(this);
        if (sessions.isEmpty()) {
            Store.create(this, sessions, "Основная");
            Store.save(this, sessions);
            prefs.rememberSession(this, sessions.get(0).id);
        }

        findViewById(R.id.btnNew).setOnClickListener(v -> newSession());
        findViewById(R.id.btnSessions).setOnClickListener(v -> openManager());
        findViewById(R.id.btnSettings).setOnClickListener(v -> openSettings());
        findViewById(R.id.btnMenu).setOnClickListener(v -> openMenu());
    }

    @Override
    protected void onResume() {
        super.onResume();
        prefs = Prefs.load(this);
        render();
        if (firstResume) {
            firstResume = false;
            if (prefs.loadLastSession || prefs.loadAllSessions) {
                handler.postDelayed(this::onStartup, 700);
            }
        }
    }

    @Override
    protected void onDestroy() {
        handler.removeCallbacksAndMessages(null);
        super.onDestroy();
    }

    private void onStartup() {
        if (prefs.loadAllSessions) {
            preloadAll();
        } else if (prefs.loadLastSession) {
            openLastSession();
        }
    }

    private void preloadAll() {
        List<Store.Session> sessions = Store.load(this);
        sessions.sort(Comparator.comparingInt(s -> s.slot));
        if (sessions.isEmpty()) {
            return;
        }
        for (int i = 0; i < sessions.size(); i++) {
            final Store.Session session = sessions.get(i);
            handler.postDelayed(() -> {
                if (stopPreload || isFinishing()) {
                    return;
                }
                Intent intent = new Intent(this, Ui.sessionClass(session.slot));
                intent.putExtra("sessionId", session.id);
                intent.putExtra("preload", true);
                startActivity(intent);
            }, 400L + i * 3200L);
        }
    }

    private void openLastSession() {
        List<Store.Session> sessions = Store.load(this);
        if (sessions.isEmpty()) {
            return;
        }
        Store.Session target = prefs.lastSessionId.isEmpty()
                ? null : Store.byId(this, prefs.lastSessionId);
        if (target == null) {
            sessions.sort(Comparator.comparingInt(s -> s.slot));
            target = sessions.get(sessions.size() - 1);
        }
        openSession(target);
    }

    // ------------------------------------------------------------------ list
    private void render() {
        List<Store.Session> sessions = Store.load(this);
        sessions.sort(Comparator.comparingInt(s -> s.slot));
        list.removeAllViews();

        if (sessions.isEmpty()) {
            TextView empty = Ui.text(this,
                    "Пока нет сессий.\nСоздайте первую кнопкой ниже.", 13, 0xFF8A8A8A);
            empty.setGravity(Gravity.CENTER);
            empty.setPadding(0, Ui.dp(this, 70), 0, Ui.dp(this, 20));
            list.addView(empty);
            return;
        }

        for (Store.Session session : sessions) {
            addCard(session, Ui.effectiveState(session, prefs));
        }
    }

    private void addCard(Store.Session session, String state) {
        View card = getLayoutInflater().inflate(R.layout.item_session, list, false);
        TextView avatar = card.findViewById(R.id.avatar);
        TextView name = card.findViewById(R.id.name);
        TextView sub = card.findViewById(R.id.sub);
        TextView badge = card.findViewById(R.id.badge);
        ProgressBar bar = card.findViewById(R.id.bar);

        String initial = session.name.trim().isEmpty()
                ? "?" : session.name.trim().substring(0, 1).toUpperCase(Locale.ROOT);
        avatar.setText(initial);
        avatar.setBackground(Ui.circle(Ui.avatarColor(session.id)));
        name.setText(session.name);

        String badgeText = "";
        int badgeBg = R.drawable.bg_badge_muted;
        int badgeColor = 0xFFD6D6D6;
        switch (state) {
            case "blocked":
                badgeText = "НЕДОСТУПНА";
                badgeBg = R.drawable.bg_badge_danger;
                badgeColor = Color.BLACK;
                break;
            case "limited":
                badgeText = "ОГРАНИЧЕНИЕ";
                badgeBg = R.drawable.bg_badge_warn;
                break;
            case "warn":
                badgeText = "⚠";
                badgeBg = R.drawable.bg_badge_warn;
                break;
            case "exhausted":
                badgeText = "ПЕРЕНЕСЕНА";
                badgeColor = 0xFF9A9A9A;
                break;
            default:
                break;
        }
        if (!badgeText.isEmpty()) {
            badge.setText(badgeText);
            badge.setBackgroundResource(badgeBg);
            badge.setTextColor(badgeColor);
            badge.setVisibility(View.VISIBLE);
        }

        String used = session.measured() ? Ui.group(session.usedTokens()) : "—";
        String text = used + "/" + Ui.humanTokens(prefs.contextLimit)
                + " · " + session.usageCount + " сообщ.";
        if (("blocked".equals(state) || "limited".equals(state)) && session.limitResetAt > 0) {
            String hint = Ui.resetHint(session.limitResetAt);
            if (!hint.isEmpty()) {
                text += " · " + hint;
            }
        }
        sub.setText(text);

        int pct = prefs.contextLimit <= 0 ? 0
                : Math.min(100, Math.round(session.usedTokens() * 100f / prefs.contextLimit));
        bar.setProgress(pct);

        if ("blocked".equals(state)) {
            card.setBackgroundResource(R.drawable.bg_card_danger);
        } else if ("exhausted".equals(state)) {
            card.setAlpha(0.65f);
        }

        card.setOnClickListener(v -> openSession(session));
        card.setOnLongClickListener(v -> {
            sessionMenu(session);
            return true;
        });
        list.addView(card);
    }

    private void openSession(Store.Session session) {
        stopPreload = true;
        prefs.rememberSession(this, session.id);
        Intent intent = new Intent(this, Ui.sessionClass(session.slot));
        intent.putExtra("sessionId", session.id);
        startActivity(intent);
    }

    private void newSession() {
        List<Store.Session> sessions = Store.load(this);
        if (sessions.size() >= Store.SLOTS) {
            Ui.toast(this, "Можно создать не больше " + Store.SLOTS + " сессий");
            return;
        }
        Store.Session created = Store.create(this, sessions, Store.nextName(sessions));
        Store.save(this, sessions);
        if (created != null) {
            prefs.rememberSession(this, created.id);
        }
        render();
        Ui.toast(this, "Сессия создана");
    }

    // --------------------------------------------------------------- dialogs
    private void sessionMenu(Store.Session session) {
        String[] items = {
                "Открыть",
                "Переименовать…",
                "Сбросить счётчик токенов",
                "Сбросить статус",
                "Очистить данные сайта…",
                "Удалить сессию…"
        };
        Ui.appDialog(this)
                .title(session.name)
                .items(items, which -> {
                    switch (which) {
                        case 0:
                            openSession(session);
                            break;
                        case 1:
                            renameSession(session);
                            break;
                        case 2:
                            session.contextBaseChars = session.contextChars;
                            session.contextResetAt = System.currentTimeMillis();
                            Store.update(this, session);
                            render();
                            Ui.toast(this, "Счётчик токенов сброшен");
                            break;
                        case 3:
                            resetStatus(session);
                            break;
                        case 4:
                            clearData(session);
                            break;
                        default:
                            deleteSession(session);
                            break;
                    }
                })
                .negative("Закрыть")
                .show();
    }

    private void renameSession(Store.Session session) {
        EditText input = input(session.name, "Название", false);
        Ui.appDialog(this)
                .title("Переименовать сессию")
                .view(input)
                .positive("Сохранить", () -> {
                    String value = input.getText().toString().trim();
                    if (value.isEmpty()) {
                        return;
                    }
                    session.name = value.length() > 60 ? value.substring(0, 60) : value;
                    Store.update(this, session);
                    render();
                })
                .negative("Отмена")
                .show();
    }

    private void resetStatus(Store.Session session) {
        session.status = "ok";
        session.statusReason = "";
        session.statusAt = System.currentTimeMillis();
        session.limitResetAt = 0;
        session.contextBaseChars = session.contextChars;
        Store.update(this, session);
        render();
        Ui.toast(this, "Статус сессии сброшен");
    }

    private void clearData(Store.Session session) {
        Ui.appDialog(this)
                .title("Очистить данные сессии")
                .message("Удалить cookies, вход и хранилище сайта для сессии «"
                        + session.name + "»? Данные будут очищены при следующем открытии.")
                .positive("Очистить", () -> {
                    Store.markWipe(this, session.slot);
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
                    Store.update(this, session);
                    render();
                    Ui.toast(this, "При следующем открытии сессия выйдет из аккаунта");
                })
                .negative("Отмена")
                .show();
    }

    private void deleteSession(Store.Session session) {
        Ui.appDialog(this)
                .title("Удалить сессию")
                .message("Сессия «" + session.name + "» будет удалена вместе с сохранённым входом.")
                .positive("Удалить", () -> {
                    List<Store.Session> sessions = Store.load(this);
                    for (int i = 0; i < sessions.size(); i++) {
                        if (sessions.get(i).id.equals(session.id)) {
                            sessions.remove(i);
                            break;
                        }
                    }
                    Store.save(this, sessions);
                    Store.markWipe(this, session.slot);
                    render();
                    Ui.toast(this, "Сессия удалена");
                })
                .negative("Отмена")
                .show();
    }

    private void openManager() {
        List<Store.Session> sessions = Store.load(this);
        if (sessions.isEmpty()) {
            Ui.toast(this, "Сессий пока нет");
            return;
        }
        sessions.sort(Comparator.comparingInt(s -> s.slot));
        String[] names = new String[sessions.size()];
        for (int i = 0; i < sessions.size(); i++) {
            Store.Session s = sessions.get(i);
            names[i] = s.name + "  ·  " + Ui.stateTitle(Ui.effectiveState(s, prefs));
        }
        Ui.appDialog(this)
                .title("Менеджер сессий")
                .items(names, which -> sessionMenu(sessions.get(which)))
                .negative("Закрыть")
                .show();
    }

    private void openMenu() {
        String[] items = {"Новая сессия", "Менеджер сессий", "Настройки", "О приложении"};
        Ui.appDialog(this)
                .items(items, which -> {
                    switch (which) {
                        case 0:
                            newSession();
                            break;
                        case 1:
                            openManager();
                            break;
                        case 2:
                            openSettings();
                            break;
                        default:
                            about();
                            break;
                    }
                })
                .negative("Закрыть")
                .show();
    }

    private void about() {
        Ui.appDialog(this)
                .title("BigSeek")
                .message("Версия " + VERSION + "\nРазработчик: 1mpsb1\n\n"
                        + "Обёртка chat.deepseek.com с изолированными профилями, "
                        + "переносом контекста и счётчиком токенов.\n\n"
                        + "Каждая сессия — отдельный профиль браузера: свои cookies, "
                        + "localStorage и кэш.")
                .positive("Закрыть", null)
                .show();
    }

    private EditText input(String value, String hint, boolean number) {
        EditText input = new EditText(this);
        input.setText(value);
        input.setHint(hint);
        input.setTextSize(14);
        input.setTextColor(Color.WHITE);
        input.setHintTextColor(0xFF565656);
        input.setBackgroundResource(R.drawable.bg_input);
        input.setPadding(Ui.dp(this, 12), Ui.dp(this, 10), Ui.dp(this, 12), Ui.dp(this, 10));
        input.setInputType(number
                ? InputType.TYPE_CLASS_NUMBER
                : InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        return input;
    }

    private void openSettings() {
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);

        EditText domain = input(prefs.domain, "chat.deepseek.com", false);
        EditText limit = input(String.valueOf(prefs.contextLimit / 1000), "128", true);
        EditText warn = input(String.valueOf(prefs.warnPercent), "75", true);
        EditText poll = input(String.valueOf(prefs.pollSeconds), "8", true);

        CheckBox detect = new CheckBox(this);
        detect.setText("Распознавать сообщения о лимите");
        detect.setTextColor(Color.WHITE);
        detect.setTextSize(13);
        detect.setChecked(prefs.detectLimits);

        CheckBox autoReset = new CheckBox(this);
        autoReset.setText("Автоматически сбрасывать статус и счётчик");
        autoReset.setTextColor(Color.WHITE);
        autoReset.setTextSize(13);
        autoReset.setChecked(prefs.autoResetStatus);

        EditText resetHours = input(String.valueOf(prefs.autoResetHours), "5", true);

        CheckBox autoTransfer = new CheckBox(this);
        autoTransfer.setText("Переносить контекст автоматически");
        autoTransfer.setTextColor(Color.WHITE);
        autoTransfer.setTextSize(13);
        autoTransfer.setChecked(prefs.autoTransfer);

        EditText transferPercent = input(String.valueOf(prefs.autoTransferPercent), "90", true);

        autoReset.setOnCheckedChangeListener((button, checked) -> resetHours.setEnabled(checked));
        resetHours.setEnabled(prefs.autoResetStatus);
        autoTransfer.setOnCheckedChangeListener((button, checked) -> transferPercent.setEnabled(checked));
        transferPercent.setEnabled(prefs.autoTransfer);

        CheckBox loadLast = new CheckBox(this);
        loadLast.setText("Открывать последнюю сессию при запуске");
        loadLast.setTextColor(Color.WHITE);
        loadLast.setTextSize(13);
        loadLast.setChecked(prefs.loadLastSession && !prefs.loadAllSessions);

        CheckBox loadAll = new CheckBox(this);
        loadAll.setText("Загружать все сессии при запуске");
        loadAll.setTextColor(Color.WHITE);
        loadAll.setTextSize(13);
        loadAll.setChecked(prefs.loadAllSessions);

        loadAll.setOnCheckedChangeListener((button, checked) -> {
            loadLast.setEnabled(!checked);
            if (checked) {
                loadLast.setChecked(false);
            }
        });
        loadLast.setOnCheckedChangeListener((button, checked) -> {
            if (checked) {
                loadAll.setChecked(false);
            }
        });
        loadLast.setEnabled(!loadAll.isChecked());

        addLabel(box, "Домен сайта");
        box.addView(domain);
        addLabel(box, "Контекстное окно, тыс. токенов");
        box.addView(limit);
        addLabel(box, "Порог предупреждения, %");
        box.addView(warn);
        addLabel(box, "Проверять страницу каждые, секунд");
        box.addView(poll);
        box.addView(detect);
        addLabel(box, "Автосброс статуса сессии");
        box.addView(autoReset);
        addLabel(box, "Сбрасывать «перенесена» через, часов");
        box.addView(resetHours);
        addLabel(box, "Автоперенос контекста");
        box.addView(autoTransfer);
        addLabel(box, "Порог автопереноса, %");
        box.addView(transferPercent);
        addLabel(box, "Запуск");
        box.addView(loadLast);
        box.addView(loadAll);

        TextView hint = Ui.text(this,
                "Загрузка всех сессий прогревает их страницы при запуске: старт дольше, "
                        + "но переключение между сессиями быстрее. Автосброс возвращает "
                        + "сессию в работу после сброса лимита или через заданное число часов. "
                        + "Автоперенос один раз упаковывает контекст при достижении порога. "
                        + "Настройки применяются к сессии при следующем открытии.",
                11, 0xFF8A8A8A);
        hint.setPadding(0, Ui.dp(this, 10), 0, 0);
        box.addView(hint);

        Ui.appDialog(this)
                .title("Настройки")
                .view(box)
                .positive("Сохранить", () -> {
                    prefs.domain = Prefs.normalizeDomain(domain.getText().toString());
                    prefs.contextLimit = clamp(parseInt(limit.getText().toString(), 128), 8, 1000) * 1000;
                    prefs.warnPercent = clamp(parseInt(warn.getText().toString(), 75), 30, 99);
                    prefs.pollSeconds = clamp(parseInt(poll.getText().toString(), 8), 3, 120);
                    prefs.detectLimits = detect.isChecked();
                    prefs.autoResetStatus = autoReset.isChecked();
                    prefs.autoResetHours = clamp(parseInt(resetHours.getText().toString(), 5), 1, 72);
                    prefs.autoTransfer = autoTransfer.isChecked();
                    prefs.autoTransferPercent = clamp(
                            parseInt(transferPercent.getText().toString(), 90), 30, 99);
                    prefs.loadAllSessions = loadAll.isChecked();
                    prefs.loadLastSession = loadLast.isChecked() && !prefs.loadAllSessions;
                    prefs.save(this);
                    Ui.toast(this, "Настройки сохранены");
                })
                .negative("Отмена")
                .show();
    }

    private void addLabel(LinearLayout box, String text) {
        TextView label = Ui.text(this, text, 11, 0xFF8A8A8A);
        label.setPadding(0, Ui.dp(this, 12), 0, Ui.dp(this, 4));
        box.addView(label);
    }

    private static int parseInt(String value, int fallback) {
        try {
            return Integer.parseInt(value.trim());
        } catch (Exception e) {
            return fallback;
        }
    }

    private static int clamp(int value, int min, int max) {
        return Math.max(min, Math.min(max, value));
    }
}
