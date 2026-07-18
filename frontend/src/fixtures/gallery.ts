// Gallery template fixtures mirroring backend seed data (§3), used by tests to
// prove every built-in renders and submits. Kept in sync with
// backend/app/services/templates/seed.py.

import type { TemplateSchema } from "../api/types";

export const SIDE_BY_SIDE: TemplateSchema = {
  name: "side-by-side-preference",
  version: 1,
  description: "Prompt with two blinded response panels; pick the better one.",
  layout: { arrangement: "split", ratio: [1, 1], width: "xl" },
  display: [
    { type: "markdown", source: "$unit.prompt", render: { collapsible: true } },
    {
      type: "panel_group",
      sources: ["$unit.response_a", "$unit.response_b"],
      render: { sync_scroll: true, diff_highlight: true },
    },
  ],
  inputs: [
    {
      id: "choice",
      type: "choice_buttons",
      label: "Which response is better?",
      options: ["Left", "Tie", "Right"],
      hotkeys: ["←", "↓", "→"],
      required: true,
    },
  ],
  variants: { dimension: "panel_order", values: ["AB", "BA"], balance: "strict" },
};

export const IMAGE_CLASSIFICATION: TemplateSchema = {
  name: "image-classification",
  version: 1,
  description: "Classify an image into preset labels, with an Other escape hatch.",
  layout: { arrangement: "split", ratio: [3, 2], width: "xl" },
  display: [
    { type: "image", source: "$unit.image_url", render: { fit: "contain", zoom: true } },
    {
      type: "text",
      source: "$unit.context",
      optional: true,
      render: { collapsible: true, max_lines: 12 },
    },
  ],
  inputs: [
    {
      id: "category",
      type: "radio",
      label: "What is shown in the image?",
      options: ["cat", "dog", "bird"],
      allow_other: true,
      required: true,
      hotkeys: "auto",
    },
  ],
  variants: null,
};

export const TEXT_SENTIMENT: TemplateSchema = {
  name: "text-sentiment",
  version: 1,
  description: "Sentiment of a passage plus a confidence rating.",
  layout: { arrangement: "stack", width: "lg" },
  display: [{ type: "text", source: "$unit.text", render: { max_lines: 20 } }],
  inputs: [
    {
      id: "sentiment",
      type: "radio",
      label: "Overall sentiment",
      options: ["positive", "neutral", "negative"],
      required: true,
    },
    {
      id: "confidence",
      type: "likert",
      label: "How confident are you?",
      scale: { min: 1, max: 5 },
      required: false,
    },
  ],
  variants: null,
};

export const SUMMARY_QUALITY: TemplateSchema = {
  name: "summary-quality",
  version: 1,
  description: "Rate a model summary against its source on three axes.",
  layout: { arrangement: "columns", ratio: [1, 1], width: "full" },
  display: [
    { type: "markdown", source: "$unit.document", render: { collapsible: true } },
    { type: "markdown", source: "$unit.summary" },
  ],
  inputs: [
    { id: "faithfulness", type: "likert", label: "Faithfulness", scale: { min: 1, max: 5 }, required: true },
    { id: "coverage", type: "likert", label: "Coverage", scale: { min: 1, max: 5 }, required: true },
    { id: "fluency", type: "likert", label: "Fluency", scale: { min: 1, max: 5 }, required: true },
    { id: "comment", type: "free_text", label: "Comments", required: false },
  ],
  variants: null,
};

export const TOXICITY_REVIEW: TemplateSchema = {
  name: "toxicity-policy-review",
  version: 1,
  description: "Flag policy violations in a text or HTML snippet, with severity.",
  layout: { arrangement: "stack", width: "lg" },
  display: [{ type: "html_snippet", source: "$unit.content" }],
  inputs: [
    {
      id: "violations",
      type: "checkbox",
      label: "Violation categories",
      options: ["hate", "harassment", "sexual", "violence", "self-harm"],
      allow_other: true,
      required: false,
    },
    {
      id: "severity",
      type: "radio",
      label: "Severity",
      options: ["none", "low", "medium", "high"],
      required: true,
    },
  ],
  variants: null,
};

export const TRANSCRIPTION_CHECK: TemplateSchema = {
  name: "transcription-check",
  version: 1,
  description: "Judge a candidate transcript against its audio and correct it.",
  layout: { arrangement: "stack", width: "lg" },
  display: [
    { type: "audio", source: "$unit.audio_url", render: { waveform: true } },
    { type: "text", source: "$unit.transcript" },
  ],
  inputs: [
    {
      id: "verdict",
      type: "radio",
      label: "Transcript accuracy",
      options: ["correct", "minor errors", "wrong"],
      required: true,
    },
    { id: "correction", type: "free_text", label: "Correction", required: false },
  ],
  variants: null,
};

export interface GalleryEntry {
  schema: TemplateSchema;
  // A sample unit payload that satisfies the template's required sources.
  payload: Record<string, unknown>;
}

export const GALLERY: GalleryEntry[] = [
  {
    schema: SIDE_BY_SIDE,
    payload: {
      prompt: "What is the capital of France?",
      response_a: "The capital of France is **Paris**.",
      response_b: "It is Lyon.",
    },
  },
  {
    schema: IMAGE_CLASSIFICATION,
    payload: { image_url: "https://example.com/cat.jpg", context: "a small pet" },
  },
  { schema: TEXT_SENTIMENT, payload: { text: "I absolutely loved this movie." } },
  {
    schema: SUMMARY_QUALITY,
    payload: { document: "# Long source\nlots of text", summary: "A short summary." },
  },
  {
    schema: TOXICITY_REVIEW,
    payload: { content: "<p>some user content</p>" },
  },
  {
    schema: TRANSCRIPTION_CHECK,
    payload: { audio_url: "https://example.com/clip.mp3", transcript: "hello world" },
  },
];
