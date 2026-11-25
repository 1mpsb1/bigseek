package com.bigseek.app;

import android.app.Dialog;
import android.content.Context;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.ColorDrawable;
import android.util.DisplayMetrics;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.Window;
import android.view.WindowManager;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

/** A dialogs shell that follows the AMOLED theme instead of the system styling. */
public final class AppDialog {
    public interface ItemListener {
        void onItem(int index);
    }

    public interface Action {
        void run();
    }

    private final Context context;
    private final Dialog dialog;
    private final LinearLayout panel;
    private final LinearLayout content;
    private String positiveText;
    private Action positiveAction;
    private String negativeText;

    public AppDialog(Context context) {
        this.context = context;
        dialog = new Dialog(context);
        dialog.requestWindowFeature(Window.FEATURE_NO_TITLE);
        Window window = dialog.getWindow();
        window.setBackgroundDrawable(new ColorDrawable(Color.TRANSPARENT));
        window.addFlags(WindowManager.LayoutParams.FLAG_DIM_BEHIND);
        WindowManager.LayoutParams params = window.getAttributes();
        params.dimAmount = 0.78f;
        window.setAttributes(params);

        panel = new LinearLayout(context);
        panel.setOrientation(LinearLayout.VERTICAL);
        panel.setBackgroundResource(R.drawable.bg_dialog);
        int pad = Ui.dp(context, 18);
        panel.setPadding(pad, Ui.dp(context, 16), pad, Ui.dp(context, 14));

        ScrollView scroll = new ScrollView(context);
        scroll.setFillViewport(false);
        content = new LinearLayout(context);
        content.setOrientation(LinearLayout.VERTICAL);
        scroll.addView(content, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        panel.addView(scroll, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        dialog.setContentView(panel);
    }

    public AppDialog title(String text) {
        TextView view = Ui.text(context, text, 18, Color.WHITE);
        view.setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL));
        LinearLayout.LayoutParams lp = fullWidth();
        lp.bottomMargin = Ui.dp(context, 4);
        content.addView(view, lp);
        return this;
    }

    public AppDialog message(String text) {
        TextView view = Ui.text(context, text, 13, 0xFFD6D6D6);
        view.setLineSpacing(Ui.dp(context, 2), 1f);
        LinearLayout.LayoutParams lp = fullWidth();
        lp.topMargin = Ui.dp(context, 6);
        content.addView(view, lp);
        return this;
    }

    public AppDialog view(View custom) {
        LinearLayout.LayoutParams lp = fullWidth();
        lp.topMargin = Ui.dp(context, 8);
        content.addView(custom, lp);
        return this;
    }

    public AppDialog items(String[] items, ItemListener listener) {
        for (int i = 0; i < items.length; i++) {
            final int index = i;
            TextView row = Ui.text(context, items[i], 15, 0xFFF0F0F0);
            row.setPadding(Ui.dp(context, 10), Ui.dp(context, 14),
                    Ui.dp(context, 10), Ui.dp(context, 14));
            row.setBackgroundResource(R.drawable.bg_row);
            row.setClickable(true);
            row.setFocusable(true);
            row.setOnClickListener(v -> {
                dialog.dismiss();
                listener.onItem(index);
            });
            LinearLayout.LayoutParams lp = fullWidth();
            if (i == 0) {
                lp.topMargin = Ui.dp(context, 6);
            }
            content.addView(row, lp);
        }
        return this;
    }

    public AppDialog positive(String text, Action action) {
        positiveText = text;
        positiveAction = action;
        return this;
    }

    public AppDialog negative(String text) {
        negativeText = text;
        return this;
    }

    public AppDialog cancelable(boolean value) {
        dialog.setCanceledOnTouchOutside(value);
        dialog.setCancelable(value);
        return this;
    }

    public void show() {
        buildButtons();
        dialog.show();
        Window window = dialog.getWindow();
        if (window == null) {
            return;
        }
        DisplayMetrics metrics = context.getResources().getDisplayMetrics();
        int width = Math.min(metrics.widthPixels - Ui.dp(context, 32), Ui.dp(context, 520));
        window.setLayout(width, ViewGroup.LayoutParams.WRAP_CONTENT);
        window.setGravity(Gravity.CENTER);
    }

    public void dismiss() {
        dialog.dismiss();
    }

    private void buildButtons() {
        if (positiveText == null && negativeText == null) {
            return;
        }
        LinearLayout row = new LinearLayout(context);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(Gravity.END);
        LinearLayout.LayoutParams rowLp = fullWidth();
        rowLp.topMargin = Ui.dp(context, 14);

        if (negativeText != null) {
            TextView negative = Ui.button(context, negativeText, false);
            negative.setMinHeight(Ui.dp(context, 42));
            negative.setPadding(Ui.dp(context, 16), Ui.dp(context, 10),
                    Ui.dp(context, 16), Ui.dp(context, 10));
            negative.setOnClickListener(v -> dialog.dismiss());
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
            lp.rightMargin = Ui.dp(context, 8);
            row.addView(negative, lp);
        }
        if (positiveText != null) {
            TextView positive = Ui.button(context, positiveText, true);
            positive.setTextSize(14);
            positive.setMinHeight(Ui.dp(context, 42));
            positive.setPadding(Ui.dp(context, 18), Ui.dp(context, 10),
                    Ui.dp(context, 18), Ui.dp(context, 10));
            positive.setOnClickListener(v -> {
                dialog.dismiss();
                if (positiveAction != null) {
                    positiveAction.run();
                }
            });
            row.addView(positive, new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        }
        panel.addView(row, rowLp);
    }

    private LinearLayout.LayoutParams fullWidth() {
        return new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
    }
}
