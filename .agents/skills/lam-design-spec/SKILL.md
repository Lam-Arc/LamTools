---
name: lam-design-spec
description: Use when writing or changing Vue components, CSS, scoped styles, or design tokens in core/ui or member frontends, or when making LamTools color and design decisions. Follow the LamTools design language for theme-area mapping, tokens, component recipes, color semantics, states, density, and motion. Use Impeccable only when creating a new design from scratch; this skill governs design decisions and colors for existing interfaces.
version: 0.1.0
---

# LamTools Design Language Specification

This skill is the **single source of truth** for the LamTools design language: its rules, constraints, colors, and design decisions. Its main purpose is to **prevent every component from inventing a new visual style**. The `impeccable` skill guides visual direction only for a design created from scratch. This skill governs design decisions, colors, tokens, components, and states in existing interfaces.

Do not create a separate DESIGN.md; that would create competing sources of truth.

## Core rules

1. **Prefer tokens.** Literal values must follow the scale. Propose a token before using an off-scale value; never hard-code one casually.
2. **Use one recipe for each control type.** Do not create parallel implementations (a second dropdown or another `--fb-*` namespace).
3. **Keep the hover-to-active alpha increase at exactly +4 percentage points** (`--alpha-hover` 8% → `--alpha-active` 12%). For neutral interactions, use `--alpha-*` tokens; do not invent 5%, 6%, 7%, 9%, 10%, or 14% values.

## Theme-area mapping (most important)

There are four theme areas. Each has `-background` (a gradient), `-text`, and derived variables. A component must reference the variables for its area, remap locally with `--text: var(--theme-{area}-text)`, and derive hover, border, and secondary text with `color-mix(in srgb, var(--text) X%, transparent)`. Semantic colors `--green`, `--blue`, `--orange`, `--red`, and `--purple` do not change with the theme.

| Area | Background variable | Text variable | Derived variables | Used for |
|---|---|---|---|---|
| backdrop | `--theme-backdrop-background` | `--theme-backdrop-text` | — | App shell, sidebar, conversation list, project menu |
| main | `--theme-main-background` | `--theme-main-text` | `-soft-background` / `-subtle-background` / `-sunken-background` / `-border` | Main cards, content area, settings pages |
| composer | `--theme-composer-background` | `--theme-composer-text` | `-soft-background` | Bottom input bar, text inputs, composer menus |
| control | `--theme-control-background` | `--theme-control-text` | `-soft-background` | Buttons, dropdowns, selects, badges, native non-text controls (checkbox/radio/range/color/file; not text inputs) |

**Most common mistake:** control components use `--theme-main-text`, or bypass the theme with static `--panel`, `--line`, or `--text`. Those components then fail to change color when the theme changes.

## Token source of truth

Source: `core/ui/src/styles/variables.css` (base colors, radii, and fonts), plus the spacing, shadow scale, state alpha, and row-fade tokens added by this specification.

- **Semantic colors:** `--green #32d17d` · `--blue #79bcff` · `--orange #ff9142` · `--red #f5555d` · `--purple #bd8cff` (not tied to an area and do not change with the theme).
- **Radii:** `--radius-sm 6px` (inputs/buttons/items) · `--radius 12px` (cards/menus) · `--radius-lg 18px` (large panels) · `--radius-xl 22px` (main app card).
- **Spacing:** `--space-1..6` = 4 / 8 / 12 / 16 / 24 / 32 px.
- **Shadows:** `--shadow-sm` (lift on hover/floating) · `--shadow-md` (cards/dropdowns/popovers) · `--shadow-lg` (modals/overlays); legacy `--shadow` aliases `--shadow-lg`.
- **State alpha:** `--alpha-hover 8%` · `--alpha-active 12%` · `--alpha-press 16%`.
- **Row fade:** `--row-fade 20%` (fade width on each side of an option row, relative to row width).
- **z-index:** `--z-background-info 10` · `--z-stage 15` · `--z-main-surface 20` · `--z-edge-trigger 35` · `--z-composer 40` · `--z-popover 60` · `--z-modal 80` · `--z-toast 90` (from `layout.css`).
- **Fonts:** `--font-sans` (Inter plus CJK fallback stack) · `--font-mono` (JetBrains Mono plus fallback stack) · `--font` aliases `--font-sans`.

## Color semantics

- **Task states:** Running = animated spinner (control color for the dot); waiting = 70% `--orange` + 30% control color; failed = 70% `--red` + 30% control color; complete = static, pure control color. Every state must also have a non-color cue (animation or text); color alone is insufficient.
- **Text hierarchy:** `--text` (body) > `color-mix(--text 65%)` (secondary help) > `color-mix(--text 45%)` (placeholder/disabled help). Derive secondary and placeholder text from the current area's `--text`, not from a static muted color.
- **Panel hierarchy:** `--bg` (deepest) < `--panel-2` (input/recessed) < `--panel` (card) < `--panel-3` (raised/active).
- **Dark theme is the only base palette:** default to dark. Light presets (paper white/review gray) are controlled by `--theme-*`; do not create another color system. Static tokens (`--bg`, `--panel-*`, `--line`, `--muted`, `--faint`) do not follow the theme; components must not use them directly for backgrounds or text.

## Design decisions

- **Visual density:** dense workbench with low visual noise. Prefer the tighter spacing values; avoid large amounts of empty space.
- **Hierarchy:** task state comes first. Running, waiting, failed, and complete states must be immediately distinguishable.
- **Motion:** restrained ease-out; no bounce or elastic motion. Every animation must honor `prefers-reduced-motion`. Motion details can be refined later.
- **Neutrality:** from AGENTS.md/PRODUCT.md, Core remains neutral. Member differences use slots or labels, not divergent styling.
- **Tooling rule:** from AGENTS.md, every GUI capability must have a corresponding CLI capability.

## Component recipes

Use one recipe per component type. Check this table before changing a component.

### Cards and panels (main area)

Use `--radius`, `--space-3` padding, `1px solid var(--theme-main-border)`, `--shadow-md`, and `--theme-main-background`. Express internal hierarchy with `--theme-main-soft-background` / `-subtle-background`; **do not nest solid-color cards**. For recessed surfaces (terminal or process-detail panels), use `--theme-main-sunken-background` (dark: `rgba(0,0,0,.32)`; light: `rgba(31,31,31,.06)`).

### Questions and approvals (decision surface)

**One decision, two surfaces, one shared recipe:** the in-conversation decision card (main area, rendered by `MessageView.vue` and styled in `ChatThread.vue`) and the confirmation panel that takes over the input area (composer area, `CorePendingDecisionPanel.vue`). Any change to one side must be applied to the other.

- **Surface:** rounded card (`--radius`). The in-conversation card uses `--theme-main-soft-background` and a border mixed with 10% main text; the waiting border also mixes in `--decision-attention` (`#b49a60`, the waiting semantic color). The confirmation panel sits inside the composer card and must not add another nested card.
- **Header:** `CircleHelp` (waiting state uses `--decision-attention`; composer version uses 70% `--orange`) plus category (approval/question, 58% text); place status or queue page number on the right.
- **Choices are numbered rows:** `[number auto] [label fit-content(50%)] [consequence minmax(0,1fr)]`, `align-items: baseline`. Keep the number and consequence outside the button so only clicking the label acts; reading the row must not trigger an action. The label button uses `--radius-sm`, no border, and `--alpha-*` hover/active (always +4 percentage points). Approve/reject tint text only (`--green` / `--red`); do not add colored outlines.
- The **free-response row** follows the choices and continues the same numbering. Its submit button is the only filled button on that surface and uses the primary recipe. The field starts at one line (`rows="1"`); `autoGrowTextarea` grows it to five lines, then scrolls internally. This is a response field, not a multiline editor; both surfaces use this recipe instead of the two-line minimum for small-text inputs.
- **At 640px and below:** move consequences to the line below the label (`grid-column: 2`) and make the submit button full width.
- For queued requests, use numbered tabs: label the current item “Waiting for your choice” and the rest “Pending”.

### Three input types

1. **Title input (main area):** unbordered plain text. `border: 0`, `outline: 0`, `background: transparent`; keep it unbordered on focus (the blinking caret indicates focus). Heavy font weight (760) and minimal padding (`2px 0`). Reference: `CoreSessionTitleEditor.vue`.
2. **Small-text input (composer area):** starts at two lines, grows to a maximum of five, then scrolls with `overflow: auto`; `resize: none`; `width: 100%`; wraps with `white-space: pre-wrap`. Use a background mixed from `--theme-composer-background` at 70%, text `--theme-composer-text`, and a border mixed from composer text at 12%.
3. **Standard input (composer area):** single-line form control using the same background/text/border recipe as the small-text input.

**Inputs have no focus style:** the blinking caret indicates focus. Do not add a border or outline; override the global `:focus-visible` rule.

### Dropdowns, selects, and popovers (control area)

Use one recipe: trigger `--radius-sm`, menu `--radius`, item `--radius-sm`, `--z-popover`, and `--shadow-md`. `UiSelect` is the only reusable primitive; consolidate `WfSelect` and composer menus into it.

**Option-row highlight is a row treatment:** no rounded mask (`border-radius: 0`). Use a `::before` pseudo-element for the hover/active background and fade it at each side with a `mask` using `--row-fade` (alpha 0.2 at both ends). Keep `gap: var(--space-1)` between rows. Fade only the hover/active background; keep text fully visible. **Keyboard focus uses the same row highlight without an extra focus ring.** Opening the menu transfers focus to the first item; an additional blue outline makes a menu opened by mouse look selected.

### Buttons (control area)

Use the shared `primary` / `secondary` / `ghost` / `danger` variants and `sm` / `md` sizes. Use `--radius-sm` and disabled opacity `.45`. Neutral variants (`secondary`/`ghost`) use `--alpha-*` for hover; filled color buttons (`primary`/`danger`) use `filter: brightness(.94)`. Do not mix the two hover mechanisms.

- **Primary:** fill `--theme-control-background`, text `--theme-control-text`; follow the theme and do not use `--blue`.
- **Danger:** use fixed semantic color `--red`.

**Composer send/stop action exception:** `CoreSendStopButton` is an action surface in the composer area even though it is a button. Its outer key surface uses `--theme-composer-text`; its paper-plane/stop glyph and motion trail use `--theme-composer-background`. Send and stop share this inversion. This explicit recipe takes precedence over generic control-area button colors for this component; do not introduce control tokens or semantic red for its action colors.

### Optical liquid glass (true glass surface)

Reuse `.optical-glass` from `core/ui/src/styles/optical-glass.css`. Do not create `.liquid-glass` or repeat `backdrop-filter`, the main surface background, or floating shadow in consumers. Material tokens are in `variables.css`: blur 8px, saturate 1.14, brightness 1.02. Mix the current theme area's `--text` into the surface at about 16% opacity for high light transmission; do not use component-level `opacity`.

There are two transmission levels. Both are semantic modifiers of the primitive; consumers must not tune the tint themselves. **High transmission** (default, tint 16%) is for large carrying surfaces such as the right rail. **Low transmission** (`.optical-glass--low-trans`, tint controlled by `--optical-glass-low-trans-tint`) is for overlays and menus: context menus, attachment-source menus, goal area, back-to-latest button, outline preview, Study selection card, and mobile top bar. Low transmission prevents bright text behind small-blur overlays from showing through as legible bright spots.

The primitive provides a uniform 2px solid neutral-gray physical edge: light gray in light mode and dark gray in dark mode. Do not add mirror, transparency, or gradients to the edge itself. Do not add inset outlines anywhere inside the glass. This includes 1px side transition lines and top highlight lines; they form a visibly doubled border at rounded corners beside the 2px physical edge. Keep only the diffused gray-green refraction along the lower edge (a gradient, not an outline) and the short, layered shadow. Consumers control geometry, `--text` area mapping, and semantic modifier only. Interactive glass may brighten slightly on hover and scale to 0.97–0.98 on active. The primitive must provide `-webkit-backdrop-filter`, a translucent fallback when backdrop filtering is unsupported, and no continuous motion under `prefers-reduced-motion: reduce`.

True glass surfaces: right rail; context-menu root and submenus; Study selection card; Workflow catalog popover/runtime dock; back-to-latest button; mobile top-bar buttons/sync status; goal area. Do not use this primitive for modal dimmers, opaque panels, the left drawer, or Workflow node cards.

### Hover and selected states

Use the shared rules and `--alpha-*` tokens; active alpha must be exactly 4 percentage points above hover. Some components (such as settings navigation) currently merge hover and active into the same value; separate them to match this rule.

### Scrollbars

Reuse the global `base.css` styling. Do not add another scrollbar recipe: `*::-webkit-scrollbar` is 8px; the track is transparent; the thumb uses `color-mix(--theme-main-text 18%)`, `border-radius: 999px`, and `background-clip: content-box`; hover darkens it to 34%.

### Confirmation and input (`CoreConfirmDialog`, the only dialog primitive)

Use a single capsule row, not a title/body/divider/footer layout: `border-radius: 999px`, `--shadow-lg`, `--theme-main-background`, `--z-modal`, and a dimmer of `color-mix(--theme-backdrop-text 20%)` (darken with a solid color only; no blur). From left to right: title (13px/680); one description cell (object name, or error text in `--red`); when input is needed, an inline 999px input cell with a `color-mix(--text var(--alpha-hover))` background; then two pill buttons—Cancel as text only (`--theme-control-text` at 65%, `--alpha-*` hover) and Confirm filled with `--theme-control-background` / `--theme-control-text` (`brightness(.94)` hover). Route every action through this component: do not restore `window.confirm`, `window.alert`, or `window.prompt`; browser dialogs display an unrelated `127.0.0.1:5173 says` title. Show failure messages in the in-app notice bar instead of a dialog.

## Prohibitions

- Do not blur full-screen overlays (onboarding, previews, library overlays, workflow-card creation, and confirmation dialogs use a solid dimmer only).
- Do not use `window.confirm`, `window.alert`, or `window.prompt`; use the `CoreConfirmDialog` capsule or the in-app notice bar.
- Do not use `--theme-main-text` for control components; use `--theme-control-text`.
- Do not bypass the theme with static `--panel`, `--line`, or `--text`.
- Do not hard-code theme colors (for example, `#2c2c2b`) instead of using `--theme-*-background`.
- Do not add local namespaces (such as `--fb-*` or `--xxx-radius`) parallel to the theme system.
- Do not attach semantic colors to theme areas; they remain fixed.
- Do not use off-scale radii (5/7/9/10/11/14px); use `--radius-*`.
- Do not hard-code z-index values (180/200/100, etc.); use `--z-*`.
- Do not create a second dropdown or button primitive.
- Do not give inputs a focus style beyond no outline; the caret is sufficient.
- Do not add motion without a `prefers-reduced-motion` fallback.
- Do not add inset outlines or highlights to glass (top highlight, upper-left specular radial light, 1px side transition lines, or similar); they form a doubled border at rounded corners.

## Audit

To audit existing fragmentation, run `node .agents/skills/lam-design-spec/scripts/audit.mjs`. It scans `core/ui/src/styles/*.css` and `core/ui/src/components/*.vue` and reports off-scale values and violations. It does **not** edit code; use its output to consolidate issues manually.

### Most severe existing violations (prioritize these)

- `FolderBrowserDialog.vue`: local `--fb-*` namespace parallel to the theme, plus `z-index: calc(var(--z-modal-backdrop,80)+3)`.
- `UiSelect.vue` and `WfSelect.vue`: duplicate dropdown primitives; consolidate to one recipe.
- `FloatingApprovalCard.vue`: bespoke shadow and `z-index: 200`, outside the z-index scale.
- `archive/members/writer/frontend/src/styles/components.css`: orphaned file referencing a missing subdirectory and not imported. The member product is archived, so no further consolidation is needed here.

### Value-to-token mapping for consolidation

- `6px` → `var(--radius-sm)` · `12px` → `var(--radius)` · `18px` → `var(--radius-lg)` · `22px` → `var(--radius-xl)`.
- `8px` hover → `var(--alpha-hover)` · `12%` active → `var(--alpha-active)`.
- `z-index: 180` → `var(--z-popover)` · `z-index: 200` → `var(--z-modal)` or `--z-toast`.
- Bespoke shadows → `var(--shadow-sm/md/lg)`, chosen for the use case.

## Relationship with Impeccable

- `impeccable` is the general-purpose engine for how to design, audit, and refine (craft/shape/audit/polish); it reads `PRODUCT.md`. Use it only for a design from scratch.
- `lam-design-spec` is the single source of truth for what the LamTools design language is; it is constraint-oriented.
- Both can apply to a new component: Impeccable sets visual direction, and this skill keeps the result within LamTools tokens and recipes.
