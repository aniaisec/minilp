// Widget registry — the frontend half of the extensibility contract (§2.6).
// One component per display/input type; adding a type means registering here.

import type { ComponentType } from "react";
import type { DisplayType, InputType } from "../api/types";

import { AudioBlock } from "./display/AudioBlock";
import { CodeBlock } from "./display/CodeBlock";
import { HtmlSnippetBlock } from "./display/HtmlSnippetBlock";
import { ImageBlock } from "./display/ImageBlock";
import { MarkdownBlock } from "./display/MarkdownBlock";
import { PanelGroup } from "./display/PanelGroup";
import { TextBlock } from "./display/TextBlock";
import type { DisplayWidgetProps } from "./display/types";

import { CheckboxInput } from "./inputs/CheckboxInput";
import { ChoiceButtonsInput } from "./inputs/ChoiceButtonsInput";
import { FreeTextInput } from "./inputs/FreeTextInput";
import { LikertInput } from "./inputs/LikertInput";
import { RadioInput } from "./inputs/RadioInput";
import type { InputWidgetProps } from "./inputs/types";

export const DISPLAY_WIDGETS: Record<DisplayType, ComponentType<DisplayWidgetProps>> = {
  text: TextBlock,
  markdown: MarkdownBlock,
  image: ImageBlock,
  audio: AudioBlock,
  code: CodeBlock,
  html_snippet: HtmlSnippetBlock,
  panel_group: PanelGroup,
};

// span_select is a stretch goal (§2.1) — not part of the v1 input set.
export const INPUT_WIDGETS: Partial<Record<InputType, ComponentType<InputWidgetProps>>> = {
  radio: RadioInput,
  checkbox: CheckboxInput,
  likert: LikertInput,
  free_text: FreeTextInput,
  choice_buttons: ChoiceButtonsInput,
};
