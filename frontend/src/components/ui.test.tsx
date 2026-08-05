// Tests for the shared primitives (UX plan, phase 5).
//
// These assert the properties the rest of the app is allowed to rely on, and
// not much else. Class names are checked where a class *is* the contract — the
// variant and size modifiers exist so a stylesheet rule can find them — and
// roles are checked everywhere else, because a role is what an assistive
// technology actually reads.

import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Button, Card, EmptyState, ErrorState, Table } from "./ui";

describe("Button", () => {
  it("is a secondary button that does not submit, by default", () => {
    render(<Button>Save</Button>);
    const btn = screen.getByRole("button", { name: "Save" });
    expect(btn).toHaveClass("mlp-btn", "mlp-btn-secondary");
    // A bare <button> inside a <form> defaults to submit; several call sites
    // this replaced were one refactor away from that bug.
    expect(btn).toHaveAttribute("type", "button");
  });

  it("emits one modifier per variant", () => {
    for (const variant of ["primary", "secondary", "ghost", "danger"] as const) {
      const { unmount } = render(<Button variant={variant}>x</Button>);
      expect(screen.getByRole("button")).toHaveClass(`mlp-btn-${variant}`);
      unmount();
    }
  });

  it("emits a size modifier only when the size is not the default", () => {
    const { rerender } = render(<Button size="md">x</Button>);
    expect(screen.getByRole("button").className).not.toMatch(/mlp-btn-(sm|md|lg)/);

    rerender(<Button size="sm">x</Button>);
    expect(screen.getByRole("button")).toHaveClass("mlp-btn-sm");

    rerender(<Button size="lg">x</Button>);
    expect(screen.getByRole("button")).toHaveClass("mlp-btn-lg");
  });

  it("keeps a caller's own className and passes through button props", () => {
    render(
      <Button className="mlp-project-card-cta" disabled aria-pressed={false} type="submit">
        Label
      </Button>,
    );
    const btn = screen.getByRole("button", { name: "Label" });
    expect(btn).toHaveClass("mlp-btn", "mlp-btn-secondary", "mlp-project-card-cta");
    expect(btn).toBeDisabled();
    expect(btn).toHaveAttribute("aria-pressed", "false");
    // An explicit `type` still wins — the default is a default, not a lock.
    expect(btn).toHaveAttribute("type", "submit");
  });
});

describe("Card", () => {
  it("renders the title as an h2 by default", () => {
    render(<Card title="Annotators">body</Card>);
    expect(screen.getByRole("heading", { level: 2, name: "Annotators" })).toBeInTheDocument();
  });

  it("renders the title at the level the caller asks for", () => {
    // Panels nested inside ProjectView's already-named <section> pass 3, so the
    // outline descends h1 → h2 → h3 rather than skipping.
    render(
      <Card title="Status funnel" headingLevel={3}>
        body
      </Card>,
    );
    expect(screen.getByRole("heading", { level: 3, name: "Status funnel" })).toBeInTheDocument();
  });

  it("renders the description and the action slot", () => {
    render(
      <Card title="Enroll a judge" description="Adds a model annotator." actions={<Button>New…</Button>}>
        body
      </Card>,
    );
    expect(screen.getByText("Adds a model annotator.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "New…" })).toBeInTheDocument();
    expect(screen.getByText("body")).toBeInTheDocument();
  });

  it("renders no header at all when there is nothing to put in it", () => {
    const { container } = render(<Card>just a surface</Card>);
    expect(container.querySelector(".mlp-card-head")).toBeNull();
    expect(screen.queryByRole("heading")).toBeNull();
  });
});

describe("EmptyState and ErrorState", () => {
  it("announces an empty state politely", () => {
    render(<EmptyState title="No judges enrolled yet">Enroll one below.</EmptyState>);
    const region = screen.getByRole("status");
    expect(within(region).getByText("No judges enrolled yet")).toBeInTheDocument();
    expect(within(region).getByText("Enroll one below.")).toBeInTheDocument();
  });

  it("announces an error assertively", () => {
    // `role="alert"` rather than `status`: an operation that did not happen has
    // to interrupt, or the reader waits for a result that is never coming.
    render(<ErrorState title="The import failed">HTTP 500</ErrorState>);
    const region = screen.getByRole("alert");
    expect(within(region).getByText("The import failed")).toBeInTheDocument();
    expect(within(region).getByText("HTTP 500")).toBeInTheDocument();
  });

  it("keeps our sentence separate from the server's message", () => {
    render(<ErrorState>{"KeyError: 'unit_id'"}</ErrorState>);
    // The default title is ours and is always readable, whatever the detail is.
    expect(screen.getByText("Something went wrong")).toBeInTheDocument();
    expect(screen.getByText("KeyError: 'unit_id'")).toBeInTheDocument();
  });

  it("renders an action when one is offered", () => {
    render(
      <EmptyState title="No projects yet" action={<Button variant="primary">+ New project</Button>}>
        Create one to get started.
      </EmptyState>,
    );
    expect(screen.getByRole("button", { name: "+ New project" })).toBeInTheDocument();
  });
});

describe("Table", () => {
  const COLUMNS = ["id", "status", { srLabel: "Actions" }];

  function rows() {
    return (
      <tr>
        <td>#1</td>
        <td>pending</td>
        <td>
          <Button size="sm">detail</Button>
        </td>
      </tr>
    );
  }

  it("names the table with a visually hidden caption", () => {
    render(
      <Table caption="Units in this project" columns={COLUMNS}>
        {rows()}
      </Table>,
    );
    // The accessible name of the table comes from the <caption>, which is why
    // it is a caption and not a heading above the table.
    expect(screen.getByRole("table", { name: "Units in this project" })).toBeInTheDocument();
    expect(screen.getByText("Units in this project")).toHaveClass("mlp-visually-hidden");
  });

  it("puts scope=col on every header cell", () => {
    render(
      <Table caption="Units" columns={COLUMNS}>
        {rows()}
      </Table>,
    );
    const headers = screen.getAllByRole("columnheader");
    expect(headers).toHaveLength(3);
    for (const th of headers) expect(th).toHaveAttribute("scope", "col");
  });

  it("gives a visually blank header column an accessible name", () => {
    render(
      <Table caption="Units" columns={COLUMNS}>
        {rows()}
      </Table>,
    );
    expect(screen.getByRole("columnheader", { name: "Actions" })).toBeInTheDocument();
  });

  it("renders the empty state as a full-width row, keeping the headers", () => {
    render(
      <Table
        caption="Units"
        columns={COLUMNS}
        isEmpty
        empty={<EmptyState title="No units match these filters" />}
      >
        {rows()}
      </Table>,
    );
    // The headers survive, so the reader can see what they searched *in*.
    expect(screen.getAllByRole("columnheader")).toHaveLength(3);
    expect(screen.getByText("No units match these filters")).toBeInTheDocument();
    // …and the rows are gone rather than rendered underneath it.
    expect(screen.queryByText("pending")).toBeNull();
    expect(screen.getByRole("cell", { name: /No units match/ })).toHaveAttribute("colspan", "3");
  });

  it("renders rows normally when it is not empty", () => {
    render(
      <Table caption="Units" columns={COLUMNS} isEmpty={false} empty={<EmptyState title="none" />}>
        {rows()}
      </Table>,
    );
    expect(screen.getByText("pending")).toBeInTheDocument();
    expect(screen.queryByText("none")).toBeNull();
  });

  it("right-aligns a column that asks for it", () => {
    render(
      <Table caption="Costs" columns={[{ label: "Spend", align: "end" }]}>
        <tr>
          <td className="mlp-col-end">$1.20</td>
        </tr>
      </Table>,
    );
    expect(screen.getByRole("columnheader", { name: "Spend" })).toHaveClass("mlp-col-end");
  });
});
