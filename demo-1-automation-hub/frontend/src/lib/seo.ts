import { useEffect } from "react";
import { useLocation } from "react-router-dom";
import seo from "../seo/routes.json";

/**
 * Per-page title, description, canonical link and social tags. The server writes the same values
 * into the HTML it sends (from the same routes.json), so crawlers that do not run JavaScript see
 * them too; this hook keeps them right while someone clicks around.
 */
const normalise = (pathname: string) => pathname.replace(/\/+$/, "") || "/";

function setTag(selector: string, attr: "content" | "href", value: string, create: () => HTMLElement) {
  let el = document.head.querySelector<HTMLElement>(selector);
  if (!el) {
    el = create();
    document.head.appendChild(el);
  }
  el.setAttribute(attr, value);
}

const meta = (key: "name" | "property", value: string) => () => {
  const el = document.createElement("meta");
  el.setAttribute(key, value);
  return el;
};

export function usePageMeta() {
  const { pathname } = useLocation();
  useEffect(() => {
    const path = normalise(pathname);
    const route = seo.routes.find((r) => r.path === path);
    const title = route?.title ?? `Page not found | ${seo.site}`;
    const description = route?.description ?? seo.routes[0].description;
    const url = `${window.location.origin}${path}`;
    document.title = title;
    setTag('meta[name="description"]', "content", description, meta("name", "description"));
    setTag('meta[property="og:title"]', "content", title, meta("property", "og:title"));
    setTag('meta[property="og:description"]', "content", description, meta("property", "og:description"));
    setTag('meta[property="og:url"]', "content", url, meta("property", "og:url"));
    setTag('meta[name="twitter:title"]', "content", title, meta("name", "twitter:title"));
    setTag('meta[name="twitter:description"]', "content", description, meta("name", "twitter:description"));
    setTag('meta[name="robots"]', "content", route ? "index, follow" : "noindex", meta("name", "robots"));
    setTag('link[rel="canonical"]', "href", url, () => {
      const el = document.createElement("link");
      el.setAttribute("rel", "canonical");
      return el;
    });
  }, [pathname]);
}
