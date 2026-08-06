// What the palette offers, and where each entry goes (§ UX plan, phase 6).
//
// `buildCommands` is a pure function of the route plus the fetched index, which
// is the point of splitting it out of the widget: "is Export offered outside a
// project" is a table lookup here rather than a click-through with a mock
// router. The destinations are asserted by running the command, because a
// command whose label is right and whose href is wrong is the failure mode that
// a label assertion cannot see.

import { describe, expect, it, vi } from "vitest";

import type { MiniLpClient } from "../../api/client";
import type { ProjectSummary, Template } from "../../api/types";
import { buildCommands, EMPTY_INDEX, type CommandContext } from "./commands";

const PROJECTS = [
  { id: 3, name: "Image QA", description: "Is the product in focus?" },
  { id: 7, name: "Ticket triage" },
] as ProjectSummary[];

const TEMPLATES = [{ id: 9, name: "Pairwise A/B", version: 2, kind: "comparison" }] as Template[];

function ctx(over: Partial<CommandContext> = {}) {
  const navigate = vi.fn();
  const client = { myAnnotator: vi.fn().mockResolvedValue({ id: 42 }) } as unknown as MiniLpClient;
  const onThemeChange = vi.fn();
  const context: CommandContext = {
    client,
    apiKey: "k",
    theme: "light",
    onThemeChange,
    projectId: null,
    projectName: null,
    index: EMPTY_INDEX,
    navigate,
    ...over,
  };
  return { context, navigate, onThemeChange, client, commands: buildCommands(context) };
}

/** Run the command with this id, or fail loudly rather than silently passing. */
function run(commands: ReturnType<typeof buildCommands>, id: string) {
  const command = commands.find((c) => c.id === id);
  if (!command) throw new Error(`no command ${id} in [${commands.map((c) => c.id).join(", ")}]`);
  command.run();
  return command;
}

describe("destinations", () => {
  it("offers every admin destination", () => {
    const { commands, navigate } = ctx();

    run(commands, "go:projects");
    run(commands, "go:templates");
    run(commands, "go:marketplace");

    expect(navigate.mock.calls.map(([h]) => h)).toEqual([
      "#/admin",
      "#/admin/templates",
      "#/admin/marketplace",
    ]);
  });

  it("carries the key into the review queue, which lives outside the router", () => {
    const { commands, navigate } = ctx({ apiKey: "sec ret" });
    run(commands, "go:review");
    expect(navigate).toHaveBeenCalledWith(expect.stringContaining("review=1&key=sec%20ret"));
  });

  it("hides the key-dependent entries when there is no key", () => {
    const { commands } = ctx({ apiKey: "" });
    const ids = commands.map((c) => c.id);
    expect(ids).not.toContain("go:review");
    expect(ids).not.toContain("action:start-labeling");
  });
});

describe("the project you are in", () => {
  it("offers all nine sections, named by their group and project", () => {
    const { commands, navigate } = ctx({ projectId: 3, projectName: "Image QA" });

    const sections = commands.filter((c) => c.group === "This project");
    expect(sections).toHaveLength(9);
    expect(sections.find((c) => c.id === "section:roster")).toMatchObject({
      label: "Annotators",
      hint: "Image QA · People",
    });

    run(commands, "section:units");
    expect(navigate).toHaveBeenCalledWith("#/admin/project/3/units");
  });

  it("finds a section by the word the docs use rather than the label", () => {
    // "roster" is the slug and the API name; "Annotators" is what the rail
    // calls it. Both have shipped in the docs, so both have to find it.
    const { commands } = ctx({ projectId: 3 });
    expect(commands.find((c) => c.id === "section:roster")?.keywords).toContain("roster");
  });

  it("falls back to the id before the name has arrived", () => {
    const { commands } = ctx({ projectId: 3, projectName: null });
    expect(commands.find((c) => c.id === "section:units")?.hint).toBe("Project #3 · Monitor");
  });

  it("offers neither the sections nor Export outside a project", () => {
    const { commands } = ctx({ projectId: null });
    expect(commands.some((c) => c.group === "This project")).toBe(false);
    // An entry that silently picks a project for you is worse than no entry.
    expect(commands.some((c) => c.id === "action:export")).toBe(false);
  });

  it("sends Export to the project's export section", () => {
    const { commands, navigate } = ctx({ projectId: 7, projectName: "Ticket triage" });
    run(commands, "action:export");
    expect(navigate).toHaveBeenCalledWith("#/admin/project/7/export");
  });
});

describe("the fetched index", () => {
  it("offers every project, opening it at the default section", () => {
    const { commands, navigate } = ctx({ index: { projects: PROJECTS, templates: [] } });

    expect(commands.filter((c) => c.group === "Projects").map((c) => c.label)).toEqual([
      "Image QA",
      "Ticket triage",
    ]);
    // The description is what tells two similarly-named projects apart.
    expect(commands.find((c) => c.id === "project:3")?.hint).toBe("Is the product in focus?");
    expect(commands.find((c) => c.id === "project:7")?.hint).toBe("Project #7");

    run(commands, "project:3");
    expect(navigate).toHaveBeenCalledWith("#/admin/project/3/progress");
  });

  it("offers every template, opening it in the builder", () => {
    const { commands, navigate } = ctx({ index: { projects: [], templates: TEMPLATES } });

    expect(commands.find((c) => c.id === "template:9")?.hint).toBe("comparison · v2");
    run(commands, "template:9");
    expect(navigate).toHaveBeenCalledWith("#/admin/templates/9/edit");
  });

  it("is simply absent before the first fetch lands", () => {
    // The palette has to be useful the instant it opens, on the static half of
    // the list, rather than refusing to render until two requests return.
    const { commands } = ctx();
    expect(commands.some((c) => c.group === "Projects")).toBe(false);
    expect(commands.length).toBeGreaterThan(0);
  });
});

describe("actions", () => {
  it("names the theme action after what pressing it does", () => {
    const light = ctx({ theme: "light" });
    expect(light.commands.find((c) => c.id === "action:theme")?.label).toBe(
      "Switch to dark theme",
    );
    run(light.commands, "action:theme");
    expect(light.onThemeChange).toHaveBeenCalledWith("dark");

    const dark = ctx({ theme: "dark" });
    expect(dark.commands.find((c) => c.id === "action:theme")?.label).toBe(
      "Switch to light theme",
    );
    run(dark.commands, "action:theme");
    expect(dark.onThemeChange).toHaveBeenCalledWith("light");
  });

  it("resolves the admin's annotator id before opening the labeling view", async () => {
    const { commands, navigate, client } = ctx({ apiKey: "k", projectId: 3 });

    run(commands, "action:start-labeling");

    // An admin holds a user token and the annotation view wants an annotator
    // id; the palette has to bridge them exactly as the rail button does.
    await vi.waitFor(() => expect(navigate).toHaveBeenCalled());
    expect(client.myAnnotator).toHaveBeenCalled();
    expect(navigate.mock.calls[0][0]).toContain("annotator=42");
    expect(navigate.mock.calls[0][0]).toContain("project=3");
  });

  it("says which project it would label when you are inside one", () => {
    expect(ctx({ projectId: 3 }).commands.find((c) => c.id === "action:start-labeling")?.label)
      .toBe("Start labeling this project");
    expect(ctx({ projectId: null }).commands.find((c) => c.id === "action:start-labeling")?.label)
      .toBe("Start labeling");
  });

  it("does not navigate when the annotator lookup fails", async () => {
    const client = {
      myAnnotator: vi.fn().mockRejectedValue(new Error("401")),
    } as unknown as MiniLpClient;
    const { commands, navigate } = ctx({ client });

    run(commands, "action:start-labeling");

    await vi.waitFor(() => expect(client.myAnnotator).toHaveBeenCalled());
    expect(navigate).not.toHaveBeenCalled();
  });
});

describe("the list as a whole", () => {
  it("gives every command a unique id, so the listbox cursor cannot alias", () => {
    const { commands } = ctx({
      projectId: 3,
      index: { projects: PROJECTS, templates: TEMPLATES },
    });
    const ids = commands.map((c) => c.id);
    expect(new Set(ids).size).toBe(ids.length);
  });
});
