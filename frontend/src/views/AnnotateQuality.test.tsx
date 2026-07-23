// Quality-subsystem behavior in the annotation view (M4, §6.1/§6.2):
// the pause screen, the reputation badge, and time-on-task reporting.

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, type TaskClient } from "../api/client";
import type { LabelOut, Task } from "../api/types";
import { IMAGE_CLASSIFICATION } from "../fixtures/gallery";
import { Annotate } from "./Annotate";

function makeTask(): Task {
  return {
    slot_id: 42,
    unit_id: 7,
    project_id: 1,
    payload: { image_url: "http://x/1.png" },
    variant: null,
  };
}

function label(quality: LabelOut["quality"]): LabelOut {
  return {
    id: 1,
    slot_id: 42,
    unit_id: 7,
    annotator_id: 1,
    value: {},
    is_valid: true,
    quality,
  };
}

// These tests exercise quality behavior via the fast "one keystroke submits"
// path, so they opt into auto-submit explicitly; the default is off (§ user
// request) and covered in Annotate.test.tsx.
beforeEach(() => {
  try {
    window.localStorage.clear();
  } catch {
    /* no storage in this environment */
  }
});

function renderWith(client: TaskClient) {
  render(
    <Annotate
      client={client}
      annotatorId={1}
      projectId={1}
      schema={IMAGE_CLASSIFICATION}
      guidelines=""
      initialAutoSubmit
    />,
  );
}

describe("assignment gating (§6.2)", () => {
  it("shows the backend's reason instead of an empty queue on 403", async () => {
    const client: TaskClient = {
      nextTask: vi.fn().mockRejectedValue(new ApiError(403, "reputation 0.41 is below the project minimum 0.80")),
      submit: vi.fn(),
      skip: vi.fn(),
    };
    renderWith(client);

    await waitFor(() => expect(screen.getByTestId("paused")).toBeInTheDocument());
    expect(screen.getByTestId("paused-reason")).toHaveTextContent("below the project minimum");
    // "Paused" and "all caught up" are different states and must not be confused.
    expect(screen.queryByTestId("empty-queue")).not.toBeInTheDocument();
  });

  it("still shows the empty-queue message when there is simply no work", async () => {
    const client: TaskClient = {
      nextTask: vi.fn().mockResolvedValue(null),
      submit: vi.fn(),
      skip: vi.fn(),
    };
    renderWith(client);

    await waitFor(() => expect(screen.getByTestId("empty-queue")).toBeInTheDocument());
    expect(screen.queryByTestId("paused")).not.toBeInTheDocument();
  });

  it("stops requesting work once a submission reports a pause", async () => {
    const nextTask = vi.fn().mockResolvedValue(makeTask());
    const client: TaskClient = {
      nextTask,
      submit: vi
        .fn()
        .mockResolvedValue(label({ paused: true, labels_voided: 3, reputation: 0.4, flags: [] })),
      skip: vi.fn(),
    };
    renderWith(client);

    await waitFor(() => expect(screen.getByTestId("input-rail")).toBeInTheDocument());
    fireEvent.keyDown(window, { key: "1" }); // single required input → auto-submit

    await waitFor(() => expect(screen.getByTestId("paused")).toBeInTheDocument());
    expect(screen.getByTestId("paused-reason")).toHaveTextContent("3 recent labels");
    expect(nextTask).toHaveBeenCalledTimes(1); // no further requests after the pause
  });
});

describe("reputation badge (§6.2)", () => {
  it("is hidden until the backend reports a score", async () => {
    const client: TaskClient = {
      nextTask: vi.fn().mockResolvedValue(makeTask()),
      submit: vi.fn(),
      skip: vi.fn(),
    };
    renderWith(client);

    await waitFor(() => expect(screen.getByTestId("input-rail")).toBeInTheDocument());
    expect(screen.queryByTestId("stat-reputation")).not.toBeInTheDocument();
  });

  it("renders the score returned with a submission", async () => {
    const client: TaskClient = {
      nextTask: vi.fn().mockResolvedValueOnce(makeTask()).mockResolvedValue(null),
      submit: vi
        .fn()
        .mockResolvedValue(label({ paused: false, labels_voided: 0, reputation: 0.918, flags: [] })),
      skip: vi.fn(),
    };
    renderWith(client);

    await waitFor(() => expect(screen.getByTestId("input-rail")).toBeInTheDocument());
    fireEvent.keyDown(window, { key: "1" });

    await waitFor(() => expect(screen.getByTestId("stat-reputation")).toHaveTextContent("92%"));
  });
});

describe("time on task (§6.2 speed flags)", () => {
  it("reports latency_ms with the submission", async () => {
    const submit = vi
      .fn()
      .mockResolvedValue(label({ paused: false, labels_voided: 0, reputation: 1, flags: [] }));
    const client: TaskClient = {
      nextTask: vi.fn().mockResolvedValueOnce(makeTask()).mockResolvedValue(null),
      submit,
      skip: vi.fn(),
    };
    renderWith(client);

    await waitFor(() => expect(screen.getByTestId("input-rail")).toBeInTheDocument());
    fireEvent.keyDown(window, { key: "1" });

    await waitFor(() => expect(submit).toHaveBeenCalled());
    const body = submit.mock.calls[0][2];
    expect(typeof body.latency_ms).toBe("number");
    expect(body.latency_ms).toBeGreaterThanOrEqual(0);
    // The client still computes `value` even though the server recanonicalizes.
    expect(body.value).toEqual({ category: "cat" });
  });
});
