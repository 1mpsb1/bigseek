package com.bigseek.app;

import android.content.Context;
import android.content.SharedPreferences;

/** Lightweight settings shared by all processes. */
public final class Prefs {
    public String domain = "https://chat.deepseek.com/";
    public int contextLimit = 128000;
    public int warnPercent = 75;
    public int pollSeconds = 8;
    public boolean detectLimits = true;
    public boolean autoResetStatus = true;
    public int autoResetHours = 5;
    public boolean autoTransfer = false;
    public int autoTransferPercent = 90;
    public boolean loadLastSession = false;
    public boolean loadAllSessions = false;
    public String lastSessionId = "";

    public static Prefs load(Context c) {
        SharedPreferences p = c.getSharedPreferences("bigseek", Context.MODE_PRIVATE);
        Prefs prefs = new Prefs();
        prefs.domain = p.getString("domain", prefs.domain);
        prefs.contextLimit = p.getInt("contextLimit", prefs.contextLimit);
        prefs.warnPercent = p.getInt("warnPercent", prefs.warnPercent);
        prefs.pollSeconds = Math.max(3, p.getInt("pollSeconds", prefs.pollSeconds));
        prefs.detectLimits = p.getBoolean("detectLimits", true);
        prefs.autoResetStatus = p.getBoolean("autoResetStatus", true);
        prefs.autoResetHours = Math.max(1, Math.min(72, p.getInt("autoResetHours", 5)));
        prefs.autoTransfer = p.getBoolean("autoTransfer", false);
        prefs.autoTransferPercent = Math.max(30, Math.min(99, p.getInt("autoTransferPercent", 90)));
        prefs.loadLastSession = p.getBoolean("loadLastSession", false);
        prefs.loadAllSessions = p.getBoolean("loadAllSessions", false);
        prefs.lastSessionId = p.getString("lastSessionId", "");
        return prefs;
    }

    public void save(Context c) {
        c.getSharedPreferences("bigseek", Context.MODE_PRIVATE).edit()
                .putString("domain", domain)
                .putInt("contextLimit", contextLimit)
                .putInt("warnPercent", warnPercent)
                .putInt("pollSeconds", pollSeconds)
                .putBoolean("detectLimits", detectLimits)
                .putBoolean("autoResetStatus", autoResetStatus)
                .putInt("autoResetHours", autoResetHours)
                .putBoolean("autoTransfer", autoTransfer)
                .putInt("autoTransferPercent", autoTransferPercent)
                .putBoolean("loadLastSession", loadLastSession)
                .putBoolean("loadAllSessions", loadAllSessions)
                .putString("lastSessionId", lastSessionId)
                .apply();
    }

    public void rememberSession(Context c, String sessionId) {
        lastSessionId = sessionId;
        c.getSharedPreferences("bigseek", Context.MODE_PRIVATE).edit()
                .putString("lastSessionId", sessionId).apply();
    }

    public static String normalizeDomain(String value) {
        String v = value == null ? "" : value.trim();
        if (v.isEmpty()) {
            return "https://chat.deepseek.com/";
        }
        if (!v.contains("://")) {
            v = "https://" + v;
        }
        if (!v.endsWith("/")) {
            v = v + "/";
        }
        return v;
    }
}
