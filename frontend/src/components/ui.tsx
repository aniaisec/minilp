// Shared UI primitives (UX plan, phase 5).
//
// The four things every panel in this app was rebuilding by hand: a button, a
// card with a heading on it, a table, and the thing you show when there is
// nothing to put in the table. They were rebuilt slightly differently each
// time, which is how the app ended up with panels that open at `<h3>` under no
// `<h2>`, tables with no accessible name, and errors rendered as body text that
// no screen reader announces.
//
// These are presentational only — no fetching, no state, no context. A panel
// still owns its data; it just stops owning its markup.

import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from "react";

import { IconAlert, IconInbox } from "./icons";

/* ==========================================================================
   Button
   ========================================================================== */

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "sm" | "md" | "lg";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
};

/**
 * `variant` is a claim about rank, not about colour: one `primary` per view,
 * `secondary` for anything ordinary, `ghost` for controls that sit inside a row
 * of data and must not out-shout it, `danger` for the ones that destroy
 * something.
 *
 * `type` defaults to `"button"`. That is not a style choice — a `<button>`
 * inside a `<form>` defaults to `type="submit"`, and several of the buttons
 * this replaces were one refactor away from silently submitting a form.
 */
export function Button({
  variant = "secondary",
  size = "md",
  className,
  type = "button",
  ...rest
}: ButtonProps) {
  const classes = ["mlp-btn", `mlp-btn-${variant}`];
  if (size !== "md") classes.push(`mlp-btn-${size}`);
  if (className) classes.push(className);
  return <button type={type} className={classes.join(" ")} {...rest} />;
}

/* ==========================================================================
   Card
   ========================================================================== */

type CardProps = {
  /** Omit for a card with no header — a bare surface, as before. */
  title?: ReactNode;
  /** One line under the title. Explains the panel, not the data. */
  description?: ReactNode;
  /** Right-hand slot in the header: the panel's own controls. */
  actions?: ReactNode;
  /**
   * Heading level for `title`. Panels sit under the page `<h1>`, so `2` is
   * right almost everywhere; a card nested inside another card's section wants
   * `3`. Passing a number rather than an element keeps the outline something
   * you can grep for.
   */
  headingLevel?: 2 | 3 | 4;
  as?: "section" | "div";
  className?: string;
  children?: ReactNode;
} & Omit<HTMLAttributes<HTMLElement>, "title">;

export function Card({
  title,
  description,
  actions,
  headingLevel = 2,
  as: Tag = "section",
  className,
  children,
  ...rest
}: CardProps) {
  const Heading = `h${headingLevel}` as "h2" | "h3" | "h4";
  return (
    <Tag className={className ? `mlp-card ${className}` : "mlp-card"} {...rest}>
      {(title !== undefined || actions !== undefined) && (
        <div className="mlp-card-head">
          <div className="mlp-card-heading">
            {title !== undefined && <Heading className="mlp-card-title">{title}</Heading>}
            {description !== undefined && <p className="mlp-card-desc">{description}</p>}
          </div>
          {actions !== undefined && <div className="mlp-card-actions">{actions}</div>}
        </div>
      )}
      {children}
    </Tag>
  );
}

/* ==========================================================================
   Empty and error states
   ========================================================================== */

type StateProps = {
  title: ReactNode;
  children?: ReactNode;
  action?: ReactNode;
  /** Row layout instead of centred column — for states inside a form. */
  inline?: boolean;
  className?: string;
  "data-testid"?: string;
};

/**
 * "There is nothing here" — said properly. A title that names what is missing,
 * an optional line about why, and an optional way to fix it. `role="status"`
 * because a list that becomes empty after a filter change is a state change the
 * reader needs to hear, but not an interruption.
 */
export function EmptyState({
  title,
  children,
  action,
  inline,
  className,
  ...rest
}: StateProps) {
  const classes = ["mlp-state"];
  if (inline) classes.push("mlp-state-inline");
  if (className) classes.push(className);
  return (
    <div className={classes.join(" ")} role="status" {...rest}>
      <IconInbox size={inline ? 18 : 28} className="mlp-state-icon" />
      <div>
        <p className="mlp-state-title">{title}</p>
        {children !== undefined && <p className="mlp-state-body">{children}</p>}
        {action !== undefined && <div className="mlp-state-actions">{action}</div>}
      </div>
    </div>
  );
}

/**
 * The same shape for failure. `role="alert"` — assertive, per the plan's
 * baseline: an operation that did not happen has to interrupt, because the
 * alternative is a person waiting for a result that is never coming.
 *
 * `title` is ours and `children` is usually the server's message. Keeping them
 * apart matters: the reader gets a sentence they can act on even when the
 * detail underneath is a stack-shaped string.
 */
export function ErrorState({
  title = "Something went wrong",
  children,
  action,
  inline,
  className,
  ...rest
}: Partial<StateProps>) {
  const classes = ["mlp-state", "mlp-state-error"];
  if (inline) classes.push("mlp-state-inline");
  if (className) classes.push(className);
  return (
    <div className={classes.join(" ")} role="alert" {...rest}>
      <IconAlert size={inline ? 18 : 28} className="mlp-state-icon" />
      <div>
        <p className="mlp-state-title">{title}</p>
        {children !== undefined && <p className="mlp-state-body">{children}</p>}
        {action !== undefined && <div className="mlp-state-actions">{action}</div>}
      </div>
    </div>
  );
}

/* ==========================================================================
   Table
   ========================================================================== */

export type Column =
  | string
  | {
      label?: ReactNode;
      /** Accessible name for a column whose header is visually blank (actions). */
      srLabel?: string;
      align?: "start" | "end";
    };

type TableProps = {
  /**
   * The table's accessible name. Required rather than optional: a table with no
   * name is announced as "table" and nothing else, and a screen full of those
   * is unnavigable. Rendered as a visually-hidden `<caption>`, which is the
   * element browsers actually map to the table's name.
   */
  caption: string;
  columns: Column[];
  /** Shown in place of the body when there are no rows. */
  empty?: ReactNode;
  /** True when `children` renders no rows. Explicit, because `children` is opaque. */
  isEmpty?: boolean;
  className?: string;
  children?: ReactNode;
  "data-testid"?: string;
};

export function Table({
  caption,
  columns,
  empty,
  isEmpty,
  className,
  children,
  ...rest
}: TableProps) {
  return (
    <table className={className ? `mlp-table ${className}` : "mlp-table"} {...rest}>
      <caption className="mlp-visually-hidden">{caption}</caption>
      <thead>
        <tr>
          {columns.map((c, i) => {
            const col = typeof c === "string" ? { label: c } : c;
            const align = "align" in col && col.align === "end" ? " mlp-col-end" : "";
            return (
              // `scope="col"` on every header cell, so a reader moving down a
              // column is told which column it is. Index as the key is safe
              // here and only here: a column list is a literal in the caller.
              <th key={i} scope="col" className={align.trim() || undefined}>
                {col.label}
                {"srLabel" in col && col.srLabel && (
                  <span className="mlp-visually-hidden">{col.srLabel}</span>
                )}
              </th>
            );
          })}
        </tr>
      </thead>
      <tbody>
        {isEmpty && empty !== undefined ? (
          <tr className="mlp-table-empty">
            <td colSpan={columns.length}>{empty}</td>
          </tr>
        ) : (
          children
        )}
      </tbody>
    </table>
  );
}
