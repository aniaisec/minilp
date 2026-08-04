// Responsive state read from the browser rather than from a resize listener.
//
// `matchMedia` is the right primitive here: it fires only when the answer to
// the question changes, and the question is written in the same language as the
// CSS. A resize listener would re-render on every pixel and could still
// disagree with the stylesheet.
//
// Returns `false` when `matchMedia` is unavailable — jsdom does not implement
// it, and a test that has not opted into a viewport should get the desktop
// layout rather than a crash.

import { useEffect, useState } from "react";

export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return false;
    return window.matchMedia(query).matches;
  });

  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const mql = window.matchMedia(query);
    const on = (e: MediaQueryListEvent) => setMatches(e.matches);
    setMatches(mql.matches);
    // `addListener` is the deprecated form, still the only one in older Safari.
    if (mql.addEventListener) mql.addEventListener("change", on);
    else mql.addListener?.(on);
    return () => {
      if (mql.removeEventListener) mql.removeEventListener("change", on);
      else mql.removeListener?.(on);
    };
  }, [query]);

  return matches;
}
