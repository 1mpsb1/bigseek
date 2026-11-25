package com.bigseek.app;

import android.content.Context;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.Locale;
import java.util.UUID;

/** Sessions and their persisted state (one JSON file, atomic writes). */
public final class Store {
    public static final int SLOTS = 6;

    public static final class Session {
        public String id = "";
        public String name = "";
        public int slot = 0;
        public String status = "ok";
        public String statusReason = "";
        public long statusAt = 0;
        public long limitResetAt = 0;
        /** Sum of the peak volume of every conversation seen in this session. */
        public long contextChars = 0;
        public long contextTokens = 0;
        public long contextBaseChars = 0;
        public long contextResetAt = 0;
        /** JSON object: chat id -> biggest character count seen in that chat. */
        public String contextChats = "{}";
        /**
         * JSON object: chat id -> { virtual list row key -> characters }. The
         * site renders the chat as a virtual list, so the visible window alone
         * stops growing; remembering every row keeps the counter honest.
         */
        public String contextItems = "{}";
        public String contextChat = "";
        public int usageCount = 0;
        public String usageDate = "";
        public String lastUrl = "";
        public long updatedAt = 0;

        public long usedChars() {
            return Math.max(0, contextChars - contextBaseChars);
        }

        /**
         * Remember the biggest volume seen for a chat and sum all chats up.
         * The counter must never go down while the user writes: a partial DOM
         * re-render or switching to another chat is not a reason to reset it.
         * Returns true when the stored total changed.
         */
        public boolean measureContext(long chars, String key, JSONObject items) {
            if (chars <= 0) {
                return false;
            }
            key = key == null ? "" : key.trim();
            String previous = contextChat == null ? "" : contextChat;

            // The page is back on the home screen while the old chat is still
            // in the DOM - ignore it, or the previous chat gets counted twice.
            if (key.isEmpty() && !previous.isEmpty()) {
                return false;
            }
            long before = contextChars;

            JSONObject chats;
            try {
                chats = new JSONObject(contextChats == null || contextChats.isEmpty()
                        ? "{}" : contextChats);
            } catch (Exception e) {
                chats = new JSONObject();
            }

            if (chats.length() == 0 && contextChars > 0) {
                // Migration from versions that tracked a single page volume.
                // It belonged to the chat that was on screen last, so seed the
                // current key instead of creating a second, unrelated entry.
                try {
                    chats.put(previous.isEmpty() ? (key.isEmpty() ? "~" : key) : previous, contextChars);
                } catch (Exception ignored) {
                }
            }

            // Home screen -> first real chat id: the new conversation used to
            // be measured under "", move that peak instead of duplicating it.
            if (previous.isEmpty() && !key.isEmpty() && chats.has("")) {
                long pending = chats.optLong("", 0);
                chats.remove("");
                try {
                    chats.put(key, Math.max(pending, chats.optLong(key, 0)));
                } catch (Exception ignored) {
                }
            }

            long known = chats.optLong(key, 0);
            if (chars > known) {
                try {
                    chats.put(key, chars);
                } catch (Exception ignored) {
                }
            }

            // Rows of the virtual list seen so far. A row only ever grows
            // (streaming, expanding a reasoning block), so the maximum is
            // enough; the chat total is the sum of every row ever seen.
            JSONObject itemsByChat;
            try {
                itemsByChat = new JSONObject(contextItems == null || contextItems.isEmpty()
                        ? "{}" : contextItems);
            } catch (Exception e) {
                itemsByChat = new JSONObject();
            }
            JSONObject rows = itemsByChat.optJSONObject(key);
            if (rows == null) {
                rows = new JSONObject();
            }
            if (items != null) {
                java.util.Iterator<String> ik = items.keys();
                while (ik.hasNext()) {
                    String rowKey = ik.next();
                    long size = items.optLong(rowKey, 0);
                    if (size > rows.optLong(rowKey, 0)) {
                        try {
                            rows.put(rowKey, size);
                        } catch (Exception ignored) {
                        }
                    }
                }
            }
            if (rows.length() > 0) {
                try {
                    itemsByChat.put(key, rows);
                } catch (Exception ignored) {
                }
                long rowTotal = 0;
                java.util.Iterator<String> rk = rows.keys();
                while (rk.hasNext()) {
                    rowTotal += rows.optLong(rk.next(), 0);
                }
                if (rowTotal > chats.optLong(key, 0)) {
                    try {
                        chats.put(key, rowTotal);
                    } catch (Exception ignored) {
                    }
                }
            }
            contextItems = itemsByChat.toString();

            // Bound the map without losing characters: move the smallest
            // chats into an archive bucket so the total does not drop.
            while (chats.length() > 80) {
                String smallest = null;
                long smallestValue = Long.MAX_VALUE;
                java.util.Iterator<String> it = chats.keys();
                while (it.hasNext()) {
                    String k = it.next();
                    if ("~".equals(k)) {
                        continue;
                    }
                    long value = chats.optLong(k, 0);
                    if (value < smallestValue) {
                        smallestValue = value;
                        smallest = k;
                    }
                }
                if (smallest == null) {
                    break;
                }
                long moved = chats.optLong(smallest, 0);
                chats.remove(smallest);
                try {
                    chats.put("~", chats.optLong("~", 0) + moved);
                } catch (Exception ignored) {
                }
            }

            long total = 0;
            java.util.Iterator<String> it = chats.keys();
            while (it.hasNext()) {
                total += chats.optLong(it.next(), 0);
            }
            contextChats = chats.toString();
            contextChars = total;
            contextTokens = Math.round(total / 2.5f);
            contextChat = key;
            return total != before || !key.equals(previous);
        }

        public int usedTokens() {
            long chars = usedChars();
            if (chars <= 0) {
                return 0;
            }
            return (int) Math.max(1, Math.round(chars / 2.5));
        }

        public boolean measured() {
            return contextChars > 0;
        }

        JSONObject toJson() {
            JSONObject o = new JSONObject();
            try {
                o.put("id", id);
                o.put("name", name);
                o.put("slot", slot);
                o.put("status", status);
                o.put("statusReason", statusReason);
                o.put("statusAt", statusAt);
                o.put("limitResetAt", limitResetAt);
                o.put("contextChars", contextChars);
                o.put("contextTokens", contextTokens);
                o.put("contextBaseChars", contextBaseChars);
                o.put("contextResetAt", contextResetAt);
                o.put("contextChats", contextChats == null ? "{}" : contextChats);
                o.put("contextItems", contextItems == null ? "{}" : contextItems);
                o.put("contextChat", contextChat == null ? "" : contextChat);
                o.put("usageCount", usageCount);
                o.put("usageDate", usageDate);
                o.put("lastUrl", lastUrl);
                o.put("updatedAt", updatedAt);
            } catch (Exception ignored) {
            }
            return o;
        }

        static Session fromJson(JSONObject o) {
            Session s = new Session();
            s.id = o.optString("id", "");
            s.name = o.optString("name", "Сессия");
            s.slot = o.optInt("slot", 0);
            s.status = o.optString("status", "ok");
            s.statusReason = o.optString("statusReason", "");
            s.statusAt = o.optLong("statusAt", 0);
            s.limitResetAt = o.optLong("limitResetAt", 0);
            s.contextChars = o.optLong("contextChars", 0);
            s.contextTokens = o.optLong("contextTokens", 0);
            s.contextBaseChars = o.optLong("contextBaseChars", 0);
            s.contextResetAt = o.optLong("contextResetAt", 0);
            s.contextChats = o.optString("contextChats", "{}");
            s.contextItems = o.optString("contextItems", "{}");
            s.contextChat = o.optString("contextChat", "");
            s.usageCount = o.optInt("usageCount", 0);
            s.usageDate = o.optString("usageDate", "");
            s.lastUrl = o.optString("lastUrl", "");
            s.updatedAt = o.optLong("updatedAt", 0);
            return s;
        }
    }

    private Store() {
    }

    public static String today() {
        return new SimpleDateFormat("yyyy-MM-dd", Locale.US).format(new Date());
    }

    private static File file(Context c) {
        return new File(c.getFilesDir(), "sessions.json");
    }

    public static List<Session> load(Context c) {
        List<Session> out = new ArrayList<>();
        File f = file(c);
        if (f.exists()) {
            try {
                String raw = new String(Files.readAllBytes(f.toPath()), StandardCharsets.UTF_8);
                JSONObject root = new JSONObject(raw);
                JSONArray arr = root.optJSONArray("sessions");
                if (arr != null) {
                    for (int i = 0; i < arr.length(); i++) {
                        JSONObject o = arr.optJSONObject(i);
                        if (o != null && !o.optString("id", "").isEmpty()) {
                            out.add(Session.fromJson(o));
                        }
                    }
                }
            } catch (Exception ignored) {
            }
        }
        String today = today();
        Prefs prefs = Prefs.load(c);
        boolean changed = false;
        for (Session s : out) {
            if (Ui.autoResetDue(s, prefs)) {
                Ui.autoResetSession(s);
                changed = true;
            } else if (!today.equals(s.usageDate)) {
                s.usageDate = today;
                s.usageCount = 0;
            }
        }
        if (changed) {
            // Persist the automatic reset right away: otherwise the card list
            // looks fine but the stale "exhausted" status returns on reload.
            save(c, out);
        }
        return out;
    }

    public static void save(Context c, List<Session> list) {
        try {
            JSONArray arr = new JSONArray();
            for (Session s : list) {
                arr.put(s.toJson());
            }
            JSONObject root = new JSONObject();
            root.put("version", 1);
            root.put("sessions", arr);
            File dir = c.getFilesDir();
            File tmp = new File(dir, "sessions.json.tmp");
            try (FileOutputStream out = new FileOutputStream(tmp)) {
                out.write(root.toString(2).getBytes(StandardCharsets.UTF_8));
                out.getFD().sync();
            }
            File f = file(c);
            if (f.exists() && !f.delete()) {
                return;
            }
            if (!tmp.renameTo(f)) {
                // Retry once in case a reader holds the file.
                if (f.exists() && !f.delete()) {
                    return;
                }
                tmp.renameTo(f);
            }
        } catch (Exception ignored) {
        }
    }

    public static Session bySlot(Context c, int slot) {
        for (Session s : load(c)) {
            if (s.slot == slot) {
                return s;
            }
        }
        return null;
    }

    public static Session byId(Context c, String id) {
        for (Session s : load(c)) {
            if (s.id.equals(id)) {
                return s;
            }
        }
        return null;
    }

    public static String nextName(List<Session> sessions) {
        for (int n = 1; n < 100; n++) {
            String candidate = "Сессия " + n;
            boolean taken = false;
            for (Session s : sessions) {
                if (s.name.equals(candidate)) {
                    taken = true;
                    break;
                }
            }
            if (!taken) {
                return candidate;
            }
        }
        return "Сессия";
    }

    public static void update(Context c, Session session) {
        List<Session> list = load(c);
        for (int i = 0; i < list.size(); i++) {
            if (list.get(i).id.equals(session.id)) {
                list.set(i, session);
                break;
            }
        }
        save(c, list);
    }

    public static Session create(Context c, List<Session> list, String name) {
        boolean[] used = new boolean[SLOTS + 1];
        for (Session s : list) {
            if (s.slot >= 1 && s.slot <= SLOTS) {
                used[s.slot] = true;
            }
        }
        for (int slot = 1; slot <= SLOTS; slot++) {
            if (!used[slot]) {
                Session s = new Session();
                s.id = UUID.randomUUID().toString().replace("-", "").substring(0, 10);
                s.slot = slot;
                s.name = name;
                s.usageDate = today();
                s.updatedAt = System.currentTimeMillis();
                list.add(s);
                return s;
            }
        }
        return null;
    }

    public static void markWipe(Context c, int slot) {
        try {
            new File(c.getFilesDir(), "wipe_" + slot).createNewFile();
        } catch (Exception ignored) {
        }
    }

    public static boolean takeWipe(Context c, int slot) {
        return new File(c.getFilesDir(), "wipe_" + slot).delete();
    }
}
