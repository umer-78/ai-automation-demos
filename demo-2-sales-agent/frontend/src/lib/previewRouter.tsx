import { useEffect, type ReactNode } from "react";
import { MemoryRouter, useLocation, useNavigate } from "react-router-dom";

/**
 * Router for the hosted preview. The host only passes a plain #name between its address bar and
 * the page, so each page is addressed as #approvals, #leads and so on instead of a path.
 */
const toHash = (pathname: string) => pathname.replace(/^\/+|\/+$/g, "");
const fromHash = () => {
  const name = window.location.hash.replace(/^#/, "");
  return /^[a-z0-9-]+$/.test(name) ? `/${name}` : "/";
};

function HashSync() {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  useEffect(() => {
    const want = toHash(pathname);
    if (window.location.hash.replace(/^#/, "") === want) return;
    try {
      window.history.replaceState(null, "", want ? `#${want}` : window.location.pathname + window.location.search);
    } catch {
      // some hosts do not allow it; the page still works, only the address does not change
    }
  }, [pathname]);
  useEffect(() => {
    const onHash = () => navigate(fromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, [navigate]);
  return null;
}

export default function PreviewRouter({ children }: { children: ReactNode }) {
  return (
    <MemoryRouter initialEntries={[fromHash()]}>
      <HashSync />
      {children}
    </MemoryRouter>
  );
}
