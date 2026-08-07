import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => cleanup());

// --- <dialog> shim (phase 7) -------------------------------------------------
//
// jsdom 25 ships `HTMLDialogElement` but not `showModal`/`close`, so a component
// built on the native dialog is untestable without this. The shim implements
// exactly the observable contract `ConfirmDialog` relies on — `open` flips, and
// `close` fires a `close` event — and nothing else.
//
// Deliberately *not* shimmed: the top layer, `::backdrop`, and background
// inertness. Those are the browser's, and faking them here would let a test
// assert behaviour the app does not actually get. Focus containment is the
// shared `useFocusTrap`, which is real code and is tested as such.
const dialogProto = window.HTMLDialogElement?.prototype;
if (dialogProto && !dialogProto.showModal) {
  dialogProto.showModal = function showModal(this: HTMLDialogElement) {
    this.open = true;
  };
  dialogProto.show = function show(this: HTMLDialogElement) {
    this.open = true;
  };
  dialogProto.close = function close(this: HTMLDialogElement, returnValue?: string) {
    if (!this.open) return;
    this.open = false;
    if (returnValue !== undefined) this.returnValue = returnValue;
    this.dispatchEvent(new Event("close"));
  };
}
