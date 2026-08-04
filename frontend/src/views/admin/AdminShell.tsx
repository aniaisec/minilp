// The admin shell (§ UX plan, phase 2) — a fixed left rail and a content column
// with its own sticky command bar, replacing the single horizontal strip of
// seven undifferentiated text links.
//
// Why a rail: the strip had no hierarchy, no room for an eighth destination,
// and nowhere to put the per-project context an admin needs while inside a
// project. A vertical rail has all three, and the active item can be marked on
// its leading edge — visible at a glance whether the rail is expanded or
// collapsed to icons.
//
// The shell owns navigation, identity and chrome. It does not know what a
// project is; `AdminApp` resolves the route and hands down a title, a
// breadcrumb trail and a body.

import { useCallback, useEffect, useId, useRef, useState, type ReactNode } from "react";

import {
  IconClose,
  IconCollapse,
  IconExpand,
  IconKey,
  IconLabel,
  IconMarketplace,
  IconMenu,
  IconMoon,
  IconNew,
  IconProjects,
  IconReview,
  IconSun,
  IconTemplates,
} from "../../components/icons";
import { useFocusTrap } from "../../hooks/useFocusTrap";
import { useMediaQuery } from "../../hooks/useMediaQuery";
import { isTypingTarget } from "../../hotkeys/event";
import type { MiniLpClient } from "../../api/client";
import { StartLabeling } from "./StartLabeling";

export const COLLAPSE_STORAGE = "mlp.navCollapsed";

/** Which rail item is current. Kept as a key rather than a URL match so the
 *  shell does not have to re-implement the router's parsing. */
export type NavKey = "projects" | "templates" | "marketplace" | "review" | "new";

export interface Crumb {
  label: string;
  /** Omitted on the last crumb, which is the current page and not a link. */
  href?: string;
}

interface RailItem {
  key: NavKey;
  label: string;
  href: string;
  icon: ReactNode;
}

function readCollapsed(): boolean {
  try {
    return window.localStorage.getItem(COLLAPSE_STORAGE) === "true";
  } catch {
    return false;
  }
}

export function AdminShell({
  client,
  apiKey,
  onApiKeyChange,
  theme,
  onThemeChange,
  active,
  title,
  crumbs,
  children,
}: {
  client: MiniLpClient;
  apiKey: string;
  onApiKeyChange: (key: string) => void;
  theme: "light" | "dark";
  onThemeChange: (theme: "light" | "dark") => void;
  active: NavKey;
  /** The page `<h1>`, and the last breadcrumb. */
  title: string;
  /** Trail *above* the title; the title is appended as the current crumb. */
  crumbs: Crumb[];
  children: ReactNode;
}) {
  const [collapsedPref, setCollapsedPref] = useState<boolean>(readCollapsed);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [keyOpen, setKeyOpen] = useState(false);

  // Two breakpoints, two different behaviours. Below 900px the rail collapses
  // to icons because the content column needs the room; below 640px there is no
  // room for a rail at all, so it becomes an overlay drawer.
  const narrow = useMediaQuery("(max-width: 900px)");
  const mobile = useMediaQuery("(max-width: 640px)");

  // Auto-collapse is a *default*, not an override. Crossing below 900px
  // collapses the rail, but the toggle can still expand it afterwards —
  // otherwise the control sits there looking operable and does nothing, which
  // is worse than not offering it.
  const [autoCollapsed, setAutoCollapsed] = useState(false);
  useEffect(() => setAutoCollapsed(narrow), [narrow]);

  // The *preference* is what persists, and only the wide-screen choice writes
  // to it — an auto-collapse the admin never asked for must not come back with
  // them on a desktop.
  const collapsed = mobile ? false : collapsedPref || autoCollapsed;

  const railRef = useRef<HTMLElement | null>(null);
  const drawerRef = useRef<HTMLDivElement | null>(null);
  const menuButtonRef = useRef<HTMLButtonElement | null>(null);
  const keyButtonRef = useRef<HTMLButtonElement | null>(null);
  const keyInputRef = useRef<HTMLInputElement | null>(null);
  const mainRef = useRef<HTMLElement | null>(null);
  const railId = useId();
  const keyPopoverId = useId();

  const closeDrawer = useCallback(() => setDrawerOpen(false), []);
  useFocusTrap(drawerRef, mobile && drawerOpen, closeDrawer);

  // The drawer is only a drawer below 640px. Growing the window past that with
  // it open would otherwise leave an invisible trap holding focus.
  useEffect(() => {
    if (!mobile) setDrawerOpen(false);
  }, [mobile]);

  useEffect(() => {
    try {
      window.localStorage.setItem(COLLAPSE_STORAGE, String(collapsedPref));
    } catch {
      /* storage unavailable — collapse state stays session-only */
    }
  }, [collapsedPref]);

  // Announce the surface to assistive technology through the document title, so
  // a screen-reader user knows which of the two modes they landed in without
  // having to explore the page to find out.
  useEffect(() => {
    document.title = `${title} · Admin · MiniLP`;
  }, [title]);

  const toggleCollapsed = useCallback(() => {
    if (collapsed) {
      setCollapsedPref(false);
      setAutoCollapsed(false);
    } else {
      setCollapsedPref(true);
    }
  }, [collapsed]);

  // Keyboard: `[` toggles the rail, `g` then p/t/m jumps. Same conventions as
  // the annotation view's hotkeys — guarded by `isTypingTarget`, and suppressed
  // while a modal (here, the mobile drawer or the key popover) is open, because
  // a hotkey that fires behind a dialog moves the page out from under it.
  useEffect(() => {
    let pendingG = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const clearPending = () => {
      pendingG = false;
      if (timer) clearTimeout(timer);
    };

    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (isTypingTarget(e.target)) return;
      if (drawerOpen || keyOpen) return;

      if (pendingG) {
        const dest: Record<string, string> = {
          p: "#/admin",
          t: "#/admin/templates",
          m: "#/admin/marketplace",
        };
        const to = dest[e.key.toLowerCase()];
        clearPending();
        if (to) {
          e.preventDefault();
          window.location.hash = to;
        }
        return;
      }

      if (e.key === "g") {
        pendingG = true;
        // A prefix that never times out is a prefix that silently eats the next
        // keystroke five minutes later.
        timer = setTimeout(clearPending, 1200);
        return;
      }
      if (e.key === "[") {
        e.preventDefault();
        toggleCollapsed();
      }
    };

    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      clearPending();
    };
  }, [drawerOpen, keyOpen, toggleCollapsed]);

  // Escape closes the key popover and hands focus back to the control that
  // opened it, which is the minimum a popover owes the keyboard.
  useEffect(() => {
    if (!keyOpen) return;
    keyInputRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setKeyOpen(false);
        keyButtonRef.current?.focus();
      }
    };
    const onClick = (e: MouseEvent) => {
      const t = e.target as Node;
      if (keyButtonRef.current?.contains(t)) return;
      if (document.getElementById(keyPopoverId)?.contains(t)) return;
      setKeyOpen(false);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onClick);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onClick);
    };
  }, [keyOpen, keyPopoverId]);

  const destinations: RailItem[] = [
    { key: "projects", label: "Projects", href: "#/admin", icon: <IconProjects /> },
    { key: "templates", label: "Templates", href: "#/admin/templates", icon: <IconTemplates /> },
    {
      key: "marketplace",
      label: "Marketplace",
      href: "#/admin/marketplace",
      icon: <IconMarketplace />,
    },
  ];

  const railBody = (
    <>
      <a className="mlp-rail-brand" href="#/admin">
        <span className="mlp-rail-tile" aria-hidden="true">
          LP
        </span>
        <span className="mlp-rail-brand-text">MiniLP</span>
      </a>

      <ul className="mlp-rail-list">
        {destinations.map((d) => (
          <li key={d.key}>
            <a
              className="mlp-rail-item"
              href={d.href}
              data-testid={`rail-${d.key}`}
              // `aria-current="page"` rather than a class alone: the accent bar
              // on the leading edge says "here" to sighted users, and this says
              // it to everyone else.
              aria-current={active === d.key ? "page" : undefined}
              onClick={closeDrawer}
            >
              <span className="mlp-rail-icon">{d.icon}</span>
              <span className="mlp-rail-label">{d.label}</span>
              {/* A real tooltip, not `title=`: `title` never appears on keyboard
                  focus and screen readers treat it inconsistently. */}
              <span className="mlp-rail-tip" aria-hidden="true">
                {d.label}
              </span>
            </a>
          </li>
        ))}
        {apiKey && (
          <li>
            {/* The review queue is a *reviewer* surface, outside the admin hash
                router — a link into it, carrying the key so no re-auth. */}
            <a
              className="mlp-rail-item"
              href={`${window.location.pathname}?review=1&key=${encodeURIComponent(apiKey)}`}
              data-testid="admin-review-link"
              aria-current={active === "review" ? "page" : undefined}
              onClick={closeDrawer}
            >
              <span className="mlp-rail-icon">
                <IconReview />
              </span>
              <span className="mlp-rail-label">Review queue</span>
              <span className="mlp-rail-tip" aria-hidden="true">
                Review queue
              </span>
            </a>
          </li>
        )}
      </ul>

      <hr className="mlp-rail-divider" />

      <ul className="mlp-rail-list">
        <li>
          <a
            className="mlp-rail-item"
            href="#/admin/new"
            data-testid="rail-new"
            aria-current={active === "new" ? "page" : undefined}
            onClick={closeDrawer}
          >
            <span className="mlp-rail-icon">
              <IconNew />
            </span>
            <span className="mlp-rail-label">New project</span>
            <span className="mlp-rail-tip" aria-hidden="true">
              New project
            </span>
          </a>
        </li>
        {apiKey && (
          <li>
            <StartLabeling
              client={client}
              apiKey={apiKey}
              className="mlp-rail-item mlp-rail-item-action"
              label={
                <>
                  <span className="mlp-rail-icon">
                    <IconLabel />
                  </span>
                  <span className="mlp-rail-label">Label tasks</span>
                  <span className="mlp-rail-tip" aria-hidden="true">
                    Label tasks
                  </span>
                </>
              }
            />
          </li>
        )}
      </ul>

      <div className="mlp-rail-foot">
        {mobile ? (
          <button
            className="mlp-rail-item mlp-rail-item-action"
            onClick={closeDrawer}
            data-testid="drawer-close"
          >
            <span className="mlp-rail-icon">
              <IconClose />
            </span>
            <span className="mlp-rail-label">Close menu</span>
          </button>
        ) : (
          <button
            className="mlp-rail-item mlp-rail-item-action"
            onClick={toggleCollapsed}
            aria-expanded={!collapsed}
            aria-controls={railId}
            data-testid="rail-toggle"
          >
            <span className="mlp-rail-icon">
              {collapsed ? <IconExpand /> : <IconCollapse />}
            </span>
            {/* The name has to describe what the press *does*, not what the rail
                currently is — a control called "Collapse" that expands is a lie
                told to exactly the people who cannot see the arrow. */}
            <span className="mlp-rail-label">{collapsed ? "Expand" : "Collapse"}</span>
            <span className="mlp-rail-tip" aria-hidden="true">
              Expand navigation
            </span>
          </button>
        )}
      </div>
    </>
  );

  const trail: Crumb[] = [...crumbs, { label: title }];

  return (
    <div
      className="mlp-app mlp-shell"
      // The mode attribute, not a second stylesheet: it re-points the accent
      // triple and nothing else. `data-theme` stays independent, so the two
      // compose (see the mode block in theme.css).
      data-mode="admin"
      data-collapsed={collapsed ? "true" : "false"}
      data-testid="admin-shell"
    >
      {/* Peripheral-vision mode marker. Decorative — the chip in the command
          bar is what actually names the mode. */}
      <div className="mlp-mode-bar" aria-hidden="true" />

      {/* First tab stop on every page. `preventDefault` because this app routes
          on the hash: navigating to "#main" would be read as a route and land
          the admin in the annotation view. */}
      <a
        className="mlp-skip-link mlp-visually-hidden-focusable"
        href="#main"
        data-testid="skip-link"
        onClick={(e) => {
          e.preventDefault();
          const main = mainRef.current;
          if (main) {
            main.focus();
            // Optional-called: jsdom has no layout, so it has no
            // `scrollIntoView`, and focus is the part that has to work anyway.
            main.scrollIntoView?.();
          }
        }}
      >
        Skip to content
      </a>

      {mobile && drawerOpen && (
        <div className="mlp-drawer-scrim mlp-rail-scrim" onClick={closeDrawer}>
          <div
            className="mlp-rail mlp-rail-drawer"
            id={railId}
            ref={drawerRef}
            role="dialog"
            aria-modal="true"
            aria-label="Navigation"
            data-testid="rail-drawer"
            onClick={(e) => e.stopPropagation()}
          >
            <nav aria-label="Primary" className="mlp-rail-inner">
              {railBody}
            </nav>
          </div>
        </div>
      )}

      {!mobile && (
        <nav
          className="mlp-rail"
          id={railId}
          ref={railRef}
          aria-label="Primary"
          data-testid="rail"
        >
          <div className="mlp-rail-inner">{railBody}</div>
        </nav>
      )}

      <div className="mlp-shell-col">
        <header className="mlp-cmdbar">
          {mobile && (
            <button
              className="mlp-icon-btn"
              ref={menuButtonRef}
              onClick={() => setDrawerOpen(true)}
              aria-expanded={drawerOpen}
              aria-controls={railId}
              data-testid="drawer-open"
            >
              <IconMenu />
              <span className="mlp-visually-hidden">Open navigation</span>
            </button>
          )}

          <div className="mlp-cmdbar-main">
            <nav aria-label="Breadcrumb" className="mlp-crumbs">
              <ol>
                {trail.map((c, i) => {
                  const last = i === trail.length - 1;
                  return (
                    <li key={`${c.label}-${i}`}>
                      {c.href && !last ? (
                        <a href={c.href}>{c.label}</a>
                      ) : (
                        <span aria-current={last ? "page" : undefined}>{c.label}</span>
                      )}
                    </li>
                  );
                })}
              </ol>
            </nav>
            <div className="mlp-cmdbar-title">
              <h1>{title}</h1>
              {/* Named in words, not hue alone: blue against teal is a plausible
                  confusion under deuteranopia, so the chip is the primary signal
                  and the colour is reinforcement. */}
              <span className="mlp-mode-chip" data-testid="mode-chip">
                Admin
              </span>
            </div>
          </div>

          <div className="mlp-cmdbar-tools">
            <div className="mlp-popover-anchor">
              <button
                className="mlp-icon-btn"
                ref={keyButtonRef}
                onClick={() => setKeyOpen((o) => !o)}
                aria-expanded={keyOpen}
                aria-controls={keyPopoverId}
                data-testid="api-key-toggle"
              >
                <IconKey />
                <span className="mlp-visually-hidden">
                  API key{apiKey ? " (set)" : " (not set)"}
                </span>
                {apiKey && <span className="mlp-dot" aria-hidden="true" />}
              </button>
              {keyOpen && (
                <div className="mlp-popover" id={keyPopoverId} data-testid="api-key-popover">
                  <label className="mlp-block-label" htmlFor={`${keyPopoverId}-input`}>
                    Admin API key
                    <input
                      id={`${keyPopoverId}-input`}
                      ref={keyInputRef}
                      className="mlp-key-input"
                      type="password"
                      value={apiKey}
                      aria-describedby={`${keyPopoverId}-help`}
                      onChange={(e) => onApiKeyChange(e.target.value)}
                    />
                  </label>
                  <p className="mlp-muted mlp-field-hint" id={`${keyPopoverId}-help`}>
                    Stored in this browser. You can also open the surface with{" "}
                    <code>?key=&lt;key&gt;</code>.
                  </p>
                </div>
              )}
            </div>

            <button
              className="mlp-icon-btn"
              onClick={() => onThemeChange(theme === "light" ? "dark" : "light")}
              data-testid="theme-toggle"
            >
              {theme === "light" ? <IconMoon /> : <IconSun />}
              <span className="mlp-visually-hidden">
                Switch to {theme === "light" ? "dark" : "light"} theme
              </span>
            </button>
          </div>
        </header>

        <main
          className="mlp-admin-main"
          id="main"
          ref={mainRef}
          // -1 so the skip link can move focus here without making <main> a
          // tab stop of its own.
          tabIndex={-1}
        >
          {children}
        </main>
      </div>
    </div>
  );
}
