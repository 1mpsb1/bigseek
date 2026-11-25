package com.bigseek.app;

import android.app.AlertDialog;
import android.content.Context;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.text.TextUtils;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.TextView;
import android.widget.Toast;

import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;
import java.util.zip.CRC32;

/** Small helpers shared by the screens. */
public final class Ui {
    private static final int[] AVATAR_COLORS = {
            0xFFFFFFFF, 0xFFDCDCDC, 0xFFC2C2C2, 0xFFA8A8A8,
            0xFFEFEFEF, 0xFFCFCFCF, 0xFFB5B5B5, 0xFFE6E6E6
    };

    private Ui() {
    }

    public static int dp(Context c, float value) {
        return Math.round(value * c.getResources().getDisplayMetrics().density);
    }

    public static void toast(Context c, String text) {
        Toast.makeText(c, text, Toast.LENGTH_SHORT).show();
    }

    public static String group(long value) {
        String digits = String.valueOf(Math.max(0, value));
        StringBuilder out = new StringBuilder();
        for (int i = 0; i < digits.length(); i++) {
            if (i > 0 && (digits.length() - i) % 3 == 0) {
                out.append(' ');
            }
            out.append(digits.charAt(i));
        }
        return out.toString();
    }

    public static String humanTokens(long tokens) {
        return group(tokens);
    }

    public static String dateRu() {
        return new SimpleDateFormat("dd.MM.yyyy", Locale.US).format(new Date());
    }

    /** The conversation id from a DeepSeek URL, or "" for the home screen. */
    public static String chatKey(String url) {
        if (url == null || url.isEmpty()) {
            return "";
        }
        try {
            String path = android.net.Uri.parse(url).getPath();
            if (path == null) {
                return "";
            }
            java.util.regex.Matcher m = java.util.regex.Pattern
                    .compile("/a/chat/s/([^/?#]+)").matcher(path);
            if (m.find()) {
                return m.group(1);
            }
            m = java.util.regex.Pattern.compile("/chat/([^/?#]+)").matcher(path);
            if (m.find() && !"s".equals(m.group(1))) {
                return m.group(1);
            }
        } catch (Exception ignored) {
        }
        return "";
    }

    public static String stateTitle(String state) {
        switch (state) {
            case "warn": return "контекст почти заполнен";
            case "limited": return "временное ограничение";
            case "blocked": return "недоступна";
            case "exhausted": return "перенесена";
            default: return "в норме";
        }
    }

    public static String effectiveState(Store.Session session, Prefs prefs) {
        if (autoResetDue(session, prefs)) {
            autoResetSession(session);
        }
        if ("blocked".equals(session.status)) {
            return "blocked";
        }
        if ("exhausted".equals(session.status)) {
            return "exhausted";
        }
        if ("limited".equals(session.status)) {
            if (System.currentTimeMillis() - session.statusAt > 600_000) {
                session.status = "ok";
                session.statusReason = "";
            } else {
                return "limited";
            }
        }
        int limit = prefs.contextLimit;
        if (limit > 0) {
            long warnAt = Math.round(limit * (prefs.warnPercent / 100.0));
            if (session.usedTokens() >= warnAt) {
                return "warn";
            }
        }
        return "ok";
    }

    /**
     * True when a finished session should be released again: the site's reset
     * time has passed, the configured timeout expired, or a new day started.
     */
    public static boolean autoResetDue(Store.Session session, Prefs prefs) {
        if (!prefs.autoResetStatus || session == null) {
            return false;
        }
        if (!("blocked".equals(session.status) || "limited".equals(session.status)
                || "exhausted".equals(session.status))) {
            return false;
        }
        long now = System.currentTimeMillis();
        long timeout = Math.max(1, prefs.autoResetHours) * 3600_000L;
        boolean due = session.limitResetAt > 0 && session.limitResetAt <= now;
        // A transferred ("перенесена") session has no site reset time, so the
        // configurable timeout releases it instead of leaving it stuck forever.
        boolean stale = session.statusAt > 0 && now - session.statusAt >= timeout;
        boolean newDay = session.limitResetAt <= 0 && !Store.today().equals(session.usageDate);
        return due || stale || newDay;
    }

    /** Clear the status and the token counter after an automatic reset. */
    public static void autoResetSession(Store.Session session) {
        long now = System.currentTimeMillis();
        session.status = "ok";
        session.statusReason = "";
        session.statusAt = now;
        session.limitResetAt = 0;
        session.contextBaseChars = session.contextChars;
        session.contextResetAt = now;
        session.usageCount = 0;
        session.usageDate = Store.today();
    }

    public static String resetHint(long limitResetAt) {
        if (limitResetAt <= 0) {
            return "";
        }
        Date when = new Date(limitResetAt);
        Date now = new Date();
        SimpleDateFormat time = new SimpleDateFormat("HH:mm", Locale.US);
        if (new SimpleDateFormat("yyyyMMdd", Locale.US).format(when)
                .equals(new SimpleDateFormat("yyyyMMdd", Locale.US).format(now))) {
            return "сброс " + time.format(when);
        }
        return "сброс " + new SimpleDateFormat("dd.MM HH:mm", Locale.US).format(when);
    }

    public static int avatarColor(String id) {
        CRC32 crc = new CRC32();
        crc.update(id.getBytes(java.nio.charset.StandardCharsets.UTF_8));
        return AVATAR_COLORS[(int) (crc.getValue() % AVATAR_COLORS.length)];
    }

    public static GradientDrawable circle(int color) {
        GradientDrawable d = new GradientDrawable();
        d.setShape(GradientDrawable.OVAL);
        d.setColor(color);
        return d;
    }

    public static GradientDrawable pill(int fill, int stroke, float radiusDp, Context c) {
        GradientDrawable d = new GradientDrawable();
        d.setShape(GradientDrawable.RECTANGLE);
        d.setColor(fill);
        if (stroke != 0) {
            d.setStroke(dp(c, 1), stroke);
        }
        d.setCornerRadius(dp(c, radiusDp));
        return d;
    }

    public static AlertDialog.Builder dialog(Context c) {
        return new AlertDialog.Builder(new android.view.ContextThemeWrapper(c, R.style.Theme_BigSeek_Dialog));
    }

    public static AppDialog appDialog(Context c) {
        return new AppDialog(c);
    }

    public static TextView text(Context c, String value, float sp, int color) {
        TextView view = new TextView(c);
        view.setText(value);
        view.setTextSize(sp);
        view.setTextColor(color);
        view.setTypeface(Typeface.create("sans-serif", Typeface.NORMAL));
        return view;
    }

    public static TextView button(Context c, String value, boolean primary) {
        TextView view = text(c, value, primary ? 13 : 12, primary ? Color.BLACK : Color.WHITE);
        view.setGravity(Gravity.CENTER);
        view.setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL));
        view.setBackgroundResource(primary ? R.drawable.bg_primary : R.drawable.bg_ghost);
        view.setPadding(dp(c, 12), dp(c, 8), dp(c, 12), dp(c, 8));
        view.setMinHeight(dp(c, 34));
        view.setClickable(true);
        view.setFocusable(true);
        return view;
    }

    public static int findSlotActivity(int slot) {
        return 0;
    }

    public static Class<?> sessionClass(int slot) {
        switch (slot) {
            case 1: return Session1Activity.class;
            case 2: return Session2Activity.class;
            case 3: return Session3Activity.class;
            case 4: return Session4Activity.class;
            case 5: return Session5Activity.class;
            default: return Session6Activity.class;
        }
    }

    public static void setMargins(View view, int left, int top, int right, int bottom) {
        ViewGroup.MarginLayoutParams lp = (ViewGroup.MarginLayoutParams) view.getLayoutParams();
        if (lp == null) {
            return;
        }
        lp.setMargins(left, top, right, bottom);
        view.setLayoutParams(lp);
    }

    public static String ellipsize(String value, int max) {
        if (value == null) {
            return "";
        }
        String v = value.replace('\n', ' ').trim();
        return v.length() <= max ? v : v.substring(0, Math.max(0, max - 1)) + "…";
    }

    public static boolean isBlank(String value) {
        return TextUtils.isEmpty(value) || value.trim().isEmpty();
    }
}
