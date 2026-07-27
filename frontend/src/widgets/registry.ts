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

import { BooleanInput } from "./inputs/BooleanInput";
import { CheckboxInput } from "./inputs/CheckboxInput";
import { ChoiceButtonsInput } from "./inputs/ChoiceButtonsInput";
import { DateInput } from "./inputs/DateInput";
import { FreeTextInput } from "./inputs/FreeTextInput";
import { LikertInput } from "./inputs/LikertInput";
import { MultiSelectInput } from "./inputs/MultiSelectInput";
import { NumberInput } from "./inputs/NumberInput";
import { RadioInput } from "./inputs/RadioInput";
import { RankingInput } from "./inputs/RankingInput";
import { RatingInput } from "./inputs/RatingInput";
import { SelectInput } from "./inputs/SelectInput";
import { SliderInput } from "./inputs/SliderInput";
import { TagsInput } from "./inputs/TagsInput";
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

// span_select is a stretch goal (§2.1) — not part of the shipped input set.
export const INPUT_WIDGETS: Partial<Record<InputType, ComponentType<InputWidgetProps>>> = {
  // v1 (M3)
  radio: RadioInput,
  checkbox: CheckboxInput,
  likert: LikertInput,
  free_text: FreeTextInput,
  choice_buttons: ChoiceButtonsInput,
  // M6 builder palette
  number: NumberInput,
  select: SelectInput,
  multiselect: MultiSelectInput,
  boolean: BooleanInput,
  rating: RatingInput,
  slider: SliderInput,
  tags: TagsInput,
  ranking: RankingInput,
  date: DateInput,
  datetime: DateInput,
};

/** Every input type the renderer can actually draw — the builder's palette. */
export const SUPPORTED_INPUT_TYPES = Object.keys(INPUT_WIDGETS) as InputType[];

/** Every display block type — the other half of the builder's palette. */
export const SUPPORTED_DISPLAY_TYPES = Object.keys(DISPLAY_WIDGETS) as DisplayType[];
