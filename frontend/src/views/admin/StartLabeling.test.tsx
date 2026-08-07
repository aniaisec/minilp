// "Start labeling" (§11) and template deletion (§2.5) in the admin surface.
//
// Both are small features whose whole value is in the edge cases: the labeling
// link is worthless if it sends the admin back into the admin surface, and the
// delete button is dangerous if it offers itself on something it would refuse.

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ProjectSummary, Template, TemplateUsage } from "../../api/types";
import { Dashboard } from "./Dashboard";
import { StartLabeling, labelingUrl } from "./StartLabeling";
import { TemplateGallery } from "./TemplateGallery";

// --- the URL ----------------------------------------------------------------

describe("labelingUrl", () => {
  it("carries project, annotator and key", () => {
    const url = new URL(labelingUrl(7, "k123", 3), "http://localhost");
    expect(url.searchParams.get("project")).toBe("3");
    expect(url.searchParams.get("annotator")).toBe("7");
    expect(url.searchParams.get("key")).toBe("k123");
  });

  it("drops the project to open the task landing page", () => {
    const url = new URL(labelingUrl(7, "k123"), "http://localhost");
    expect(url.searchParams.has("project")).toBe(false);
    expect(url.searchParams.get("annotator")).toBe("7");
  });

  it("never carries a #/admin hash — that would bounce straight back to admin", () => {
    expect(labelingUrl(7, "k", 3)).not.toContain("#");
  });

  it("omits an empty key rather than sending key=", () => {
    expect(labelingUrl(7, "", 3)).not.toContain("key=");
  });
});

// --- the button -------------------------------------------------------------

describe("StartLabeling", () => {
  it("resolves the caller's annotator id before navigating", async () => {
    const navigate = vi.fn();
    const client = { myAnnotator: vi.fn().mockResolvedValue({ id: 42 }) } as never;

    render(
      <StartLabeling client={client} projectId={5} apiKey="abc" navigate={navigate} />,
    );
    fireEvent.click(screen.getByTestId("start-labeling"));

    await waitFor(() => expect(navigate).toHaveBeenCalled());
    const url = new URL(navigate.mock.calls[0][0], "http://localhost");
    expect(url.searchParams.get("annotator")).toBe("42");
    expect(url.searchParams.get("project")).toBe("5");
  });

  it("surfaces a failure instead of navigating nowhere", async () => {
    const navigate = vi.fn();
    const client = {
      myAnnotator: vi.fn().mockRejectedValue(new Error("invalid API key")),
    } as never;

    render(<StartLabeling client={client} apiKey="" navigate={navigate} />);
    fireEvent.click(screen.getByTestId("start-labeling"));

    expect(await screen.findByTestId("start-labeling-error")).toHaveTextContent(
      "invalid API key",
    );
    expect(navigate).not.toHaveBeenCalled();
  });

  it("does not trigger the surrounding card's click handler", async () => {
    // The dashboard card is itself clickable; without stopPropagation, "Label
    // this" would also open the project view underneath the navigation.
    const onCardClick = vi.fn();
    const navigate = vi.fn();
    const client = { myAnnotator: vi.fn().mockResolvedValue({ id: 1 }) } as never;

    render(
      <div onClick={onCardClick}>
        <StartLabeling client={client} projectId={1} apiKey="k" navigate={navigate} />
      </div>,
    );
    fireEvent.click(screen.getByTestId("start-labeling"));

    await waitFor(() => expect(navigate).toHaveBeenCalled());
    expect(onCardClick).not.toHaveBeenCalled();
  });
});

// --- the dashboard ----------------------------------------------------------

const PROJECTS: ProjectSummary[] = [
  {
    id: 3,
    name: "Preference run",
    description: null,
    template_id: 1,
    template_version: 1,
    labels_per_unit: 2,
    gold_ratio: 0.1,
  },
];

describe("Dashboard", () => {
  it("offers a labeling link on every project", async () => {
    const client = {
      listProjects: vi.fn().mockResolvedValue(PROJECTS),
      myAnnotator: vi.fn().mockResolvedValue({ id: 9 }),
    } as never;

    render(<Dashboard client={client} apiKey="k" onOpen={vi.fn()} onNew={vi.fn()} />);

    const card = await screen.findByTestId("project-card-3");
    expect(within(card).getByTestId("start-labeling")).toBeInTheDocument();
  });

  it("still opens the project when the card itself is clicked", async () => {
    const onOpen = vi.fn();
    const client = {
      listProjects: vi.fn().mockResolvedValue(PROJECTS),
      myAnnotator: vi.fn(),
    } as never;

    render(<Dashboard client={client} apiKey="k" onOpen={onOpen} onNew={vi.fn()} />);
    fireEvent.click(await screen.findByTestId("project-card-3"));

    expect(onOpen).toHaveBeenCalledWith(3);
  });
});

// --- template deletion ------------------------------------------------------

function template(over: Partial<Template> = {}): Template {
  return {
    id: 10,
    name: "my-template",
    version: 1,
    description: "A custom one",
    kind: "custom",
    schema: {
      name: "my-template",
      inputs: [{ id: "category", type: "radio", label: "Category", options: ["a", "b"] }],
    },
    ...over,
  } as Template;
}

function usage(over: Partial<TemplateUsage> = {}): TemplateUsage {
  return {
    template_id: 10,
    kind: "custom",
    deletable: true,
    projects: [],
    lineage_projects: [],
    versions: 1,
    ...over,
  };
}

function galleryClient(over: Record<string, unknown> = {}) {
  return {
    listTemplates: vi.fn().mockResolvedValue([template()]),
    getTemplateSample: vi
      .fn()
      .mockResolvedValue({
        template_id: 10,
        saved: false,
        sample: {},
        fields: { required: [], optional: [] },
      }),
    getTemplateUsage: vi.fn().mockResolvedValue(usage()),
    deleteTemplate: vi
      .fn()
      .mockResolvedValue({ name: "my-template", count: 1, deleted: [{ id: 10, name: "m", version: 1 }] }),
    saveTemplateSample: vi.fn(),
    cloneTemplate: vi.fn(),
    ...over,
  } as never;
}

describe("TemplateGallery — delete", () => {
  // Phase 7 moved the second click into the shared confirmation dialog, so the
  // pair of assertions below is now "the dialog names what it is about to do"
  // rather than "a second button appeared".
  it("confirms in a dialog that names the version, then calls the API with that scope", async () => {
    const client = galleryClient();
    render(<TemplateGallery client={client} onEdit={vi.fn()} />);

    fireEvent.click(await screen.findByTestId("template-delete-start"));
    const dialog = screen.getByTestId("template-delete-dialog");
    expect(dialog).toHaveTextContent("Delete “my-template” v1?");
    // The confirm button names the act, not the click — the whole reason this
    // stopped being `window.confirm`'s "OK".
    expect(screen.getByTestId("confirm-accept")).toHaveTextContent("Delete version");
    fireEvent.click(screen.getByTestId("confirm-accept"));

    await waitFor(() => expect(client.deleteTemplate).toHaveBeenCalledWith(10, "one"));
  });

  it("cancel backs out without calling the API", async () => {
    const client = galleryClient();
    render(<TemplateGallery client={client} onEdit={vi.fn()} />);

    fireEvent.click(await screen.findByTestId("template-delete-start"));
    fireEvent.click(screen.getByTestId("confirm-cancel"));

    expect(screen.queryByTestId("template-delete-dialog")).not.toBeInTheDocument();
    expect(screen.getByTestId("template-delete-start")).toBeInTheDocument();
    expect(client.deleteTemplate).not.toHaveBeenCalled();
  });

  it("Escape cancels, and does not delete", async () => {
    // The dialog is destructive, so the cheapest possible dismissal has to be
    // the safe one.
    const client = galleryClient();
    render(<TemplateGallery client={client} onEdit={vi.fn()} />);

    fireEvent.click(await screen.findByTestId("template-delete-start"));
    fireEvent.keyDown(document, { key: "Escape" });

    await waitFor(() =>
      expect(screen.queryByTestId("template-delete-dialog")).not.toBeInTheDocument(),
    );
    expect(client.deleteTemplate).not.toHaveBeenCalled();
  });

  it("removes the template from the list once deleted", async () => {
    const client = galleryClient();
    render(<TemplateGallery client={client} onEdit={vi.fn()} />);

    fireEvent.click(await screen.findByTestId("template-delete-start"));
    fireEvent.click(screen.getByTestId("confirm-accept"));

    await waitFor(() =>
      expect(screen.queryByTestId("template-delete-start")).not.toBeInTheDocument(),
    );
  });

  it("offers no delete at all on a builtin", async () => {
    const client = galleryClient({
      listTemplates: vi.fn().mockResolvedValue([template({ kind: "builtin" })]),
    });
    render(<TemplateGallery client={client} onEdit={vi.fn()} />);

    await screen.findByTestId("gallery-clone");
    expect(screen.queryByTestId("template-delete")).not.toBeInTheDocument();
    expect(screen.getByText(/cannot be deleted/)).toBeInTheDocument();
  });

  it("disables delete and names the blocking project, before the click", async () => {
    // The reason a template can't go should be visible, not discovered via 409.
    const client = galleryClient({
      getTemplateUsage: vi.fn().mockResolvedValue(
        usage({
          deletable: false,
          projects: [
            { project_id: 4, name: "Q3 run", template_id: 10, template_version: 1 },
          ],
        }),
      ),
    });
    render(<TemplateGallery client={client} onEdit={vi.fn()} />);

    const button = await screen.findByTestId("template-delete-start");
    expect(button).toBeDisabled();
    expect(screen.getByTestId("template-delete-blocked")).toHaveTextContent("Q3 run (#4)");
  });

  it("offers a lineage delete only when there is more than one version", async () => {
    render(<TemplateGallery client={galleryClient()} onEdit={vi.fn()} />);
    await screen.findByTestId("template-delete-start");
    expect(screen.queryByTestId("template-delete-lineage")).not.toBeInTheDocument();
  });

  it("deletes the whole lineage when asked", async () => {
    const client = galleryClient({
      getTemplateUsage: vi.fn().mockResolvedValue(usage({ versions: 3 })),
    });
    render(<TemplateGallery client={client} onEdit={vi.fn()} />);

    fireEvent.click(await screen.findByTestId("template-delete-lineage"));
    fireEvent.click(screen.getByTestId("template-delete-start"));
    expect(screen.getByTestId("template-delete-dialog")).toHaveTextContent(
      "Delete all 3 versions of “my-template”?",
    );
    // The count is on the button too: the checkbox that widened the blast
    // radius was ticked before the dialog opened, and by the time the confirm
    // is pressed it is behind a modal.
    expect(screen.getByTestId("confirm-accept")).toHaveTextContent("Delete 3 versions");
    fireEvent.click(screen.getByTestId("confirm-accept"));

    await waitFor(() => expect(client.deleteTemplate).toHaveBeenCalledWith(10, "all"));
  });

  it("blocks a lineage delete when a sibling version is in use", async () => {
    // Per-version is fine here; the lineage is not — and the button must reflect
    // whichever scope is currently selected.
    const client = galleryClient({
      getTemplateUsage: vi.fn().mockResolvedValue(
        usage({
          versions: 2,
          projects: [],
          lineage_projects: [
            { project_id: 8, name: "older run", template_id: 9, template_version: 1 },
          ],
        }),
      ),
    });
    render(<TemplateGallery client={client} onEdit={vi.fn()} />);

    expect(await screen.findByTestId("template-delete-start")).not.toBeDisabled();
    fireEvent.click(screen.getByTestId("template-delete-lineage"));
    expect(screen.getByTestId("template-delete-start")).toBeDisabled();
    expect(screen.getByTestId("template-delete-blocked")).toHaveTextContent("older run (#8)");
  });

  it("shows the server's refusal if one slips past the pre-check", async () => {
    // A project created between the usage read and the click.
    const client = galleryClient({
      deleteTemplate: vi
        .fn()
        .mockRejectedValue(new Error("cannot delete 'my-template': it is in use by 'Late' (#12)")),
    });
    render(<TemplateGallery client={client} onEdit={vi.fn()} />);

    fireEvent.click(await screen.findByTestId("template-delete-start"));
    fireEvent.click(screen.getByTestId("confirm-accept"));

    // Inline, not a toast: the template is still on the page, and the reason it
    // would not go belongs beside the button that refused.
    expect(await screen.findByTestId("template-delete-error")).toHaveTextContent("Late");
    expect(screen.getByTestId("template-delete-start")).toBeInTheDocument();
    expect(screen.queryByTestId("template-delete-dialog")).not.toBeInTheDocument();
  });
});
