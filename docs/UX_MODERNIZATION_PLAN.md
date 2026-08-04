# UX modernization plan

Status: proposed, not implemented. This document is the agreed scope before any
code changes land.

## Why

The app works but reads as a prototype. Four specific problems drive everything
below.

The admin surface navigates from a horizontal strip of undifferentiated text
links, so with seven destinations the header is a wall of similar-looking words
with no visual hierarchy and nowhere to grow. Adding an eighth destination makes
it worse, and there is no room for the per-project context an admin actually
needs while working inside a project.

Nothing in the chrome tells you which mode you are in. The admin surface and the
labeler surface share the same neutral card system and the same accent blue, so
an admin who clicks "Label tasks" lands on a screen that looks like the one they
left. This matters more than it sounds: the two surfaces have different stakes.
Admin actions change project configuration; labeler actions produce data. A
person should never be uncertain which of those they are doing.

The visual language is flat in the unhelpful sense. Everything is a white card
with a hairline border and the same 10px radius, so a stat, a destructive
action, a data table, and a form field all carry equal visual weight. Nothing
guides the eye, and the accent color appears only on primary buttons and
progress fills.

The app is not currently usable without a mouse or without sight. This is not a
polish item and it is not deferred to the end of this plan — it is a correctness
problem, treated below as a first-class constraint on every phase. An audit of
the current code found no `<h1>` anywhere in the application, exactly two
`:focus-visible` rules across a 1341-line stylesheet, no `prefers-reduced-motion`
block, no focus management in the hotkey overlay or the unit-detail drawer, no
`aria-live` region on any of the fourteen loading states, and no landmark
structure outside a single `<header>`/`<main>` pair in the admin shell.

## Target look

Azure-portal shaped, not Azure-portal skinned. The parts worth taking are the
persistent left rail with icons and a collapse toggle, the breadcrumb-plus-title
command bar that tells you where you are, the secondary navigation inside a
resource (Azure's blade tabs, our project tabs), and a restrained accent that
appears on the leading edge of active things rather than as large fills. The
parts worth leaving are the density, the nested blade stacking, and the
information-dense chrome that only makes sense when you administer hundreds of
resources.

## Mode identity: blue for admin, teal for labeler

The single highest-value change per line of code. Both surfaces keep the same
neutral grays, spacing, type scale, and component shapes — only the accent hue
and a few identity elements change.

The admin surface uses blue (`#185FA5` at strength, `#378ADD` mid, `#E6F1FB`
soft). The labeler and reviewer surfaces use teal (`#0F6E56` at strength,
`#1D9E75` mid, `#E1F5EE` soft). Teal is chosen over violet or amber because it
stays calm across a long labeling session and does not collide with the
warning/danger semantics already used in the bias, judges, and webhook panels.

Mode is expressed in four places and no more. The accent token itself, which
propagates to buttons, focus rings, selected options, progress fills, and active
nav items for free. A 3px accent bar along the top edge of the shell, which is
visible in peripheral vision and survives dark mode. The mode chip in the header
("Admin" / "Labeling" / "Reviewing"), which names the mode in words. And the app
icon tile in the rail header.

That the mode is named in words and marked by position, not by hue alone, is the
accessibility requirement rather than a stylistic preference — roughly one in
twelve men has a color vision deficiency, and blue against teal is a plausible
confusion under deuteranopia. The chip is the primary signal; the hue is
reinforcement. The mode is also announced to assistive technology through the
document title (`Image QA · Labeling · MiniLP`) so a screen-reader user knows
which surface they landed on without exploring it.

Mechanically this is a `data-mode="admin" | "label" | "review"` attribute on the
shell root that re-points `--accent`, `--accent-soft`, and `--accent-strong`.
Because `data-theme` already sets the same variables for dark mode, the mode
block must be declared after the theme block and scoped as
`[data-theme="dark"][data-mode="label"]` for the dark variants — a single
combined selector matrix of six rules, not a second theming system.

Deliberately excluded: colored page backgrounds and colored card surfaces. They
make text harder to read and fight with the widget previews that render inside
the template builder.

## Accessibility baseline

The target is WCAG 2.2 AA across both surfaces. These requirements are not a
phase; they are conditions that each phase below must satisfy before it merges,
and they are listed once here rather than repeated in every section.

**Every interactive element is reachable and operable by keyboard.** No control
is mouse-only, tab order follows visual order, and nothing traps focus except
modals, which trap it deliberately and release it on close. The two `div
role="button"` patterns in `Dashboard.tsx` and the builder `Canvas.tsx` are the
current exceptions: the dashboard project card is a clickable div that also
contains a real button, which is why it was written that way. It becomes a card
with a single anchor as its title — the whole card stays clickable for mouse
users, but the accessible name and the tab stop belong to the link, which is
also what makes the card announce correctly.

**Focus is always visible.** A 2px `:focus-visible` ring in the accent color
with a 2px offset, defined once on a shared selector list rather than per
component, plus a knockout inner ring so it stays visible against both surface
and accent backgrounds. Two rules exist today; every focusable element needs
one.

**Landmarks and headings form a real document.** One `<h1>` per screen naming
the screen, headings descending without skipping levels — the panels currently
start at `<h3>` under no `<h2>`, and `ProjectView` renders `<h2>Project #3</h2>`
with `<h3>` panels beneath it inconsistently. Landmarks: `<nav>` for the rail
with an `aria-label`, `<main>` with `id="main"` as the target of a skip link,
`<aside>` for the guidelines drawer, and `<header>` for the command bar. A
skip-to-content link, visually hidden until focused, is the first tab stop on
every page.

**State changes are announced.** `aria-current="page"` on the active rail item
and the active project tab. `aria-expanded` and `aria-controls` on the rail
collapse toggle and the guidelines drawer. A polite `aria-live` region for
session stats so a labeler using a screen reader hears their count update, and
an assertive one for errors and destructive confirmations. The fourteen `Loading…`
strings become `role="status"` regions so the load is announced rather than
silently swapped in.

**Modals behave like modals.** The hotkey overlay and the unit-detail drawer
currently have no focus management at all. Both need `role="dialog"`,
`aria-modal="true"`, an accessible name, focus moved to the dialog on open,
focus trapped inside while open, focus restored to the trigger on close, and
Escape to dismiss. This is one shared `useFocusTrap` hook, not three
implementations.

**Contrast passes at AA.** Both accent ramps against both themes, `--text-muted`
against `--surface-2` (which is borderline today at 4.3:1), the pill variants,
and the disabled button state, which currently uses `opacity: 0.5` — opacity
multiplies against whatever is behind it and cannot be reasoned about, so
disabled states get explicit tokens instead.

**Motion respects the user.** A `prefers-reduced-motion: reduce` block that
disables the rail collapse animation, the progress-bar width transition, and the
drawer slide. None exists today.

**Hotkeys do not fight assistive technology.** The existing single-letter
hotkeys (`x` to exit, `s` to skip, `?` for help) are already guarded by
`isTypingTarget`, but they also need to not fire while a modal is open, and the
new `[` and `g`-prefixed navigation keys must follow the same guard. Every
hotkey is discoverable in the overlay, and every hotkey-driven action also has a
visible control — the keyboard is an accelerator, never the only path.

**Forms name their fields.** The API key input, the filter controls in the unit
browser, and the inspector fields in the builder rely on placeholder text or
visual proximity in several places. Each gets a real `<label>` association,
`aria-describedby` for help text, and `aria-invalid` plus an error message tied
by id when validation fails.

**Touch targets are 24px minimum** (WCAG 2.2 target size), which the tiny
buttons in the ranking widget and the chip close affordances currently miss.

## Phased work

### Phase 1 — token layer

Restructure `theme.css` into a token block, a primitives block, and a components
block. Today it is a single file appended to milestone by milestone, with
`--muted` referenced in several places where `--text-muted` was intended (the
rating stars, palette headings, and rank numbers currently inherit rather than
resolve). Fixing those typos is part of this phase.

Tokens to add: an accent triple per mode, an elevation scale of three shadow
levels rather than one, a spacing scale (`--space-1` through `--space-6`) so
padding stops being a mix of literals, a radius scale (`--radius-sm` 6px,
`--radius` 8px, `--radius-lg` 12px), a sidebar width pair (expanded 232px,
collapsed 56px), explicit disabled-state tokens to replace `opacity: 0.5`, and a
focus-ring token. Radius drops from 10px to 8px on controls; cards keep 12px.
The current uniform 10px is what makes small controls look soft and cards look
sharp at the same time.

The shared `:focus-visible` rule, the `prefers-reduced-motion` block, and a
`.mlp-visually-hidden` utility for skip links and screen-reader-only text all
land here, since everything downstream depends on them.

No visual change ships in this phase beyond the radius adjustment and focus
rings appearing where they were missing. It exists so later phases are edits
rather than rewrites.

### Phase 2 — the admin shell

Replace `mlp-admin-bar` with a two-part shell: a fixed left rail and a content
column with its own sticky command bar.

The rail holds the brand tile, the primary destinations (Projects, Templates,
Marketplace, Review queue), a divider, then the actions (New project, Label
tasks), and a collapse toggle pinned to the bottom. Each destination gets an
icon rendered as an inline SVG component in a new `components/icons.tsx` — no
icon dependency, roughly a dozen 16px paths, which is cheaper than adding a
package to a project that currently has two runtime dependencies. Every icon is
`aria-hidden` with the label carrying the accessible name, so nothing is
announced twice.

The active item is marked with a 3px accent bar on its left edge plus an accent
tint background, accent text, and `aria-current="page"`. This is the Azure
pattern and it reads correctly at a glance in both collapsed and expanded
states.

Collapse behavior: the toggle switches the rail between 232px and 56px, hides
labels, and centers icons. The toggle carries `aria-expanded` and
`aria-controls`. Collapsed items keep their accessible name through
`aria-label`, and get a real tooltip rather than the `title` attribute, which
does not appear on keyboard focus and is unreliable for assistive technology.
The state persists to `localStorage` under `mlp.navCollapsed` alongside the
existing theme and home-view preferences. Below 900px viewport width the rail
auto-collapses; below 640px it becomes an overlay drawer opened by a hamburger
in the command bar, with a scrim, a focus trap, and Escape to close.

The command bar carries a skip-to-content link as its first tab stop, a
breadcrumb in a labeled `<nav>` with `aria-current="page"` on the last crumb,
the page `<h1>`, the mode chip, and the right-side tools (API key field, theme
toggle) moved out of the nav. The API key input collapses into an icon button
that opens a small labeled popover — it currently sits in the header at all
times as a 180px password field, which is prominent chrome for something you
touch once per session.

Keyboard: `[` toggles the rail, `g` then `p`/`t`/`m` jumps to Projects,
Templates, Marketplace. These follow the existing conventions in
`hotkeys/event.ts`, respect `isTypingTarget`, and are suppressed while a modal
is open.

### Phase 3 — project view

The nine tabs in `ProjectView` are the second navigation problem. Nine
horizontal tabs at 14px overflow on a laptop and give no sense of grouping.

Convert them to a secondary rail inside the project, grouped under quiet section
headings: *Monitor* (Progress, Units, Bias and distribution), *People*
(Annotators, Judges), *Automate* (Active learning), *Manage* (Configure, Add
tasks, Export). The grouping is not cosmetic — it separates read-only inspection
from actions that change project state. Groups are real `<nav>` sections with
labels, not styled divs, so the grouping is available non-visually too.

The tab also moves into the URL (`#/admin/project/3/units`) so a tab is
linkable, survives refresh, and appears in the breadcrumb. Right now the tab is
component state and a refresh silently returns you to Progress. Because they
become routes rather than tabs, they are links with `aria-current` rather than
an ARIA tablist, which is the simpler and more robust pattern.

The project header gains a status line: project name as the `<h1>` rather than
`Project #3`, a state pill, and the completion bar that currently lives inside
the Progress tab only.

### Phase 4 — labeler surface

Apply the teal mode, then fix the two things that hurt during actual labeling.

The topbar becomes a slim task bar: exit control, project name, a segmented
progress indicator, session stats, and the hotkey-help trigger. The current
topbar mixes navigation and stats in one flex row with no hierarchy. Session
stats become a polite live region so the count is announced as it changes.

The submit affordance moves to a sticky footer on the input rail so it is
reachable without scrolling on a long task, with the primary action, the skip
control, the auto-submit toggle, and its hotkey hint grouped together. Today the
rail actions sit at the natural end of the form, which on an image-heavy task
means scrolling to submit. The sticky footer must not overlap the last field
when the on-screen keyboard is open on a tablet, and must remain reachable at
200% zoom and at 320px width (WCAG reflow) — both are acceptance criteria, not
afterthoughts.

Smaller items in the same pass: the guidelines panel becomes a collapsible
`<aside>` drawer rather than a permanently expanded card competing with the
task, with `aria-expanded` on its trigger; the hotkey overlay gets grouped
sections, a real dialog role, a focus trap, and a proper close affordance; and
skeleton loaders with `role="status"` replace the current bare loading states,
since a labeler sees that transition on every single unit.

The annotation widgets get an accessibility audit of their own. They already use
`role="radio"`, `role="checkbox"`, and `aria-checked` correctly in most places,
but the ranking widget is drag-and-drop with `Alt+Arrow` as its only keyboard
path and no announcement when an item moves, the rating stars need
`aria-valuetext` so "3 of 5" is spoken rather than a bare number, and the
free-text and number inputs need their validation messages associated by id.
Drag-and-drop that has no non-drag alternative is a WCAG 2.2 failure outright.

### Phase 5 — component polish

A pass across the shared primitives once the shells are settled. Buttons get
three explicit variants (primary, secondary, ghost) plus a size scale, replacing
the current single `mlp-btn` with ad-hoc inline overrides, and a `disabled`
appearance that comes from tokens rather than opacity. Cards get an optional
header slot with title, description, and an action area, which the admin panels
currently rebuild by hand each time. Tables get sticky headers, row hover,
`<caption>` or an `aria-label`, scope attributes on header cells, and a defined
empty state. Every panel gets a real empty state and a real error state rather
than a bare string.

Motion stays minimal: the rail collapse at 180ms, tint and border transitions at
120ms, nothing else, all of it disabled under `prefers-reduced-motion`.

### Phase 6 — command palette

`Cmd/Ctrl+K` opens a palette that jumps to any project, template, or admin
destination and runs the common actions (new project, start labeling, toggle
theme, export). In an app with two navigation levels this removes most
navigation entirely for anyone who uses it daily, and it is roughly 150 lines
over the existing hash router.

It is also, done properly, the best keyboard affordance in the app: a combobox
with `role="combobox"`, `aria-expanded`, `aria-controls`, and
`aria-activedescendant`, results in a `role="listbox"`, arrow keys to move,
Enter to run, Escape to dismiss, focus restored to the trigger, and a live
region announcing the result count. Done improperly it is a keyboard trap, so
this phase does not merge without a screen-reader pass.

### Phase 7 — feedback and confirmation

Toast notifications for the operations that currently succeed silently or throw
into a bare `<div className="mlp-error">`. Exports, judge runs, template saves,
and webhook tests all complete with no confirmation today. Toasts render into a
single `aria-live` region — polite for success, assertive for failure — are
dismissible, and never auto-dismiss an error, since a message that disappears
before it can be read is worse than no message.

Confirmation dialogs replace `window.confirm`, which is used by the exit control
and template delete. The native dialog cannot be styled, cannot be tested
cleanly, looks foreign, and gives no control over focus. The replacement is one
`<dialog>`-based component with the shared focus trap, a named destructive
action rather than "OK", and Escape to cancel.

### Phase 8 — density, dark mode, and the audit

A density toggle (comfortable/compact) for the admin tables. The unit browser
and roster are where an admin scans hundreds of rows, and the current 7px cell
padding is a compromise between reading and scanning that serves neither.
Density is a root attribute remapping the spacing tokens, not per-component
props, and it never shrinks a touch target below 24px.

Dark mode parity across both modes. The dark palette exists but has only been
exercised on the annotation view; the admin panels, tables, and builder need an
audit, and the accent-per-mode change is the right moment to do it. Dark mode
also needs the theme preference to default from `prefers-color-scheme` rather
than hardcoding `light`, which is what both shells do today.

The closing accessibility audit: automated axe-core checks wired into the test
run so regressions fail CI, a manual keyboard-only walkthrough of every screen,
a screen-reader pass on the two shells and the annotation loop, a 200%-zoom and
320px-reflow check, and a contrast sweep of every token pair in both themes and
both modes.

## Risk and verification

The blast radius is CSS plus two shell components. `AdminApp.tsx` and the topbar
in `Annotate.tsx` change structurally; the panels themselves are only touched
for the header, heading-level, and empty-state work in phases 5 and 8.

Test coupling is low — a grep across the test suite shows only
`data-testid="admin-review-link"` depends on the admin header markup, and the
`data-theme` assertions in `Annotate.test.tsx` continue to hold because the mode
attribute is separate.

New tests needed: rail collapse persists and restores; the mode attribute is
correct on each surface; tab state round-trips through the URL; the mobile
drawer, hotkey overlay, and confirmation dialog each trap focus and restore it
to their trigger; the skip link is the first tab stop and moves focus to
`<main>`; `aria-current` follows the route; and the palette is operable and
escapable by keyboard alone.

Per-phase verification: `npm run typecheck`, `npm test`, an axe-core pass with
zero violations, a keyboard-only walkthrough, and a visual pass in both themes
and both modes. Phases 4 and 6 additionally require a screen-reader pass before
merge.

## Sequencing

Phases 1 and 2 together are the visible win and should land first as one
reviewable change. Phase 3 follows since it depends on the shell. Phase 4 is
independent of 2 and 3 and could be parallelized. Phases 5 through 7 are
additive and can land in any order once the shells are settled. Phase 8 closes
the work and should not be skipped — it is where the accessibility baseline
above stops being a set of intentions and becomes a checked property of the app.
