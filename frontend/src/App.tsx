import "./theme.css";
import { useEffect, useState } from "react";

import { ToastProvider } from "./components/Toast";
import { AdminApp } from "./views/admin/AdminApp";
import { AnnotatePage } from "./views/AnnotatePage";

// A hash prefix of #/admin selects the M5 admin surface; anything else is the
// annotation view (which reads its config from the query string, §M3). Kept as a
// one-line switch so neither surface needs a routing dependency.
function useIsAdmin(): boolean {
  const [admin, setAdmin] = useState(() => window.location.hash.startsWith("#/admin"));
  useEffect(() => {
    const on = () => setAdmin(window.location.hash.startsWith("#/admin"));
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return admin;
}

// One `ToastProvider` for the whole app rather than one per surface (phase 7).
// The two surfaces are not as separate as the switch below suggests: the
// template gallery embeds the *labeler* view inside the admin shell as a live
// preview, so a provider on each would nest, and a toast posted from the
// preview would land in a second region stacked on top of the first. One
// provider above the switch also means a message outlives a route change —
// which is what makes the template editor's "saved as v3" survive the
// navigation back to the gallery that happens in the same commit.
export default function App() {
  const isAdmin = useIsAdmin();
  return <ToastProvider>{isAdmin ? <AdminApp /> : <AnnotatePage />}</ToastProvider>;
}
