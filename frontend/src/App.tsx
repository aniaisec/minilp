import "./theme.css";
import { useEffect, useState } from "react";

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

export default function App() {
  const isAdmin = useIsAdmin();
  return isAdmin ? <AdminApp /> : <AnnotatePage />;
}
