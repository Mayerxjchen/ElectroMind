# Desktop Workbench — page override

> **Project:** ElectroMind Codex-style Desktop
> **Page:** desktop workbench (sidebar · timeline · contextual Inspector · Composer)
> **Date:** 2026-08-05
> **Overrides:** MASTER.md component specs (marketing-page blocks) — the
> desktop is a native-feeling developer tool, not a landing page.
> **Product pattern (ui-ux-pro-max `product` domain):** Developer Tool / IDE —
> Dark Mode (OLED) + Minimalism; dashboard style Real-Time Monitor + Terminal.
> **Style:** Codex-style, minimal, quiet, task-focused, native-feeling.

## Tokens (frozen in D3.5)

```css
--space-1: 4px;  --space-2: 8px;  --space-3: 12px; --space-4: 16px; --space-5: 24px;
--radius-sm: 6px; --radius-md: 8px; --radius-lg: 12px;
--text-xs: 12px; --text-sm: 13px; --text-md: 14px; --text-lg: 16px; --text-xl: 20px;
--motion-fast: 120ms; --motion-normal: 180ms; --motion-slow: 240ms;
```

Color roles from MASTER.md apply (dark slate + run green): primary `#1E293B`,
accent/run `#22C55E`, background `#0F172A`, foreground `#F8FAFC`, muted
`#272F42`, border `#475569`, destructive `#EF4444`.  Status never relies on
color alone — text/icon always present.  Focus ring required on every
interactive element (no `outline: none` without replacement).

D3.5 contrast pass (WCAG 4.5:1 measured, both themes): dark
`--text-tertiary` `#666b75 → #858a96`; light `--text-tertiary`
`#8a9096 → #6a6f76`; light statuses darkened — `--success #15803d`,
`--danger #b91c1c`, `--warning #8a6400`, `--added #0f766e`,
`--modified #1d4ed8`.  All status colors are theme-aware tokens
(`var(--success)` etc.) — no hardcoded hexes in status styles.

## Layout

| Window | Left | Center | Right Inspector |
|---|---|---|---|
| ≥ 1536px | 220px | ≥ 680px | 420px, pushes content |
| 1280–1535px | 220px | ≥ 680px | 360px, pushes content |
| 900–1279px | 220px | full | drawer overlay (min(380px, 100vw)) |
| < 900px | auto-collapsed rail | full | drawer overlay |

Inspector: default-closed, contextual triggers open the matching tab,
pinnable, Escape closes non-pinned, focus returns to the trigger.

## Interaction rules (Inspector)

- Open via trigger → tab mapping: plan / changes / files / artifacts / jobs /
  runtime / logs.
- Same-trigger click toggles; tab bar always opens; pinned survives thread
  switch (content refreshes); pinned + last tab persist across restarts.
- Drawer: transform+opacity only, 180ms in / 120ms out, exit faster than
  enter; no width animation; `prefers-reduced-motion` disables.

## Do / Don't

- ✅ 2–3 char compact tab labels at 12px, chips with text (never color-only)
- ✅ hairline borders + subtle shadows (≤ 0.08 alpha, 16px blur) for drawer
- ✅ monospace for paths/hunks; tabular numerals for stats
- ❌ glass blur, big shadows, nested cards, purple-pink gradients, decorative
  animation, emoji-as-icon, body text < 12px, mixing Codicons and Lucide at
  the same level
