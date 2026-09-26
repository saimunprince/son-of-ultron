"use client";

import { useEffect, useState } from "react";
import type { PresentationElement } from "@/lib/syraxClient";

/** The stage draws whatever the presentation engine decided to show.
 *  It never decides anything itself: elements arrive with kind, attention,
 *  ttl and dismissal already chosen by SYRAX. Empty plan → nothing rendered. */
export default function Stage({ elements, onDismiss }: { elements: PresentationElement[]; onDismiss?: (id: string) => void }) {
  const [, tick] = useState(0);
  // client-side expiry so a stale element disappears even if the server is quiet
  useEffect(() => {
    if (!elements.some((e) => e.ttl_s != null)) return;
    const id = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, [elements]);
  const now = Date.now() / 1000;
  const live = elements.filter((e) => e.ttl_s == null || e.created + e.ttl_s > now);
  if (live.length === 0) return null;
  return (
    <div className="stage" aria-live="polite">
      {live.map((e) => (
        <section key={e.presentation_id} className={`stage-el stage-${e.kind} attn-${e.attention}`}>
          <header>
            <span className="tag">{e.kind.toUpperCase()}</span>
            {e.purpose}
            {e.source === "model" && <span className="stage-src">· chosen by SYRAX</span>}
            {onDismiss && (
              <button type="button" className="stage-x" aria-label="Dismiss" title="Dismiss (SYRAX learns what you close quickly)" onClick={() => onDismiss(e.presentation_id)}>
                ×
              </button>
            )}
          </header>
          <Body el={e} />
        </section>
      ))}
    </div>
  );
}

function Body({ el }: { el: PresentationElement }) {
  const d = el.data as Record<string, unknown>;
  const text = typeof d.text === "string" ? d.text : "";
  switch (el.kind) {
    case "code":
      return (
        <>
          {typeof d.path === "string" && <div className="stage-path">{d.path}</div>}
          <pre className="tool-io">{String(d.code ?? "")}</pre>
        </>
      );
    case "terminal":
      return <pre className="tool-io tool-out">{text}</pre>;
    case "table": {
      const rows = Array.isArray(d.rows) ? (d.rows as unknown[][]) : [];
      return (
        <table className="self-table">
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>{r.map((c, k) => (i === 0 ? <th key={k}>{String(c ?? "")}</th> : <td key={k}>{String(c ?? "")}</td>))}</tr>
            ))}
          </tbody>
        </table>
      );
    }
    case "list": {
      const items = Array.isArray(d.items) ? (d.items as string[]) : [];
      return (
        <>
          {typeof d.title === "string" && d.title && <div className="stage-path">{d.title}</div>}
          {items.length > 0 ? (
            <ul className="stage-list">
              {items.map((it, i) => (
                <li key={i}>{it}</li>
              ))}
            </ul>
          ) : (
            <div className="self-dim">
              {typeof d.sources === "number" ? `${d.sources} source(s), ${String(d.stored ?? 0)} stored` : "empty"}
            </div>
          )}
        </>
      );
    }
    case "image":
      return typeof d.image === "string" ? <img className="tool-img" src={`data:image/png;base64,${d.image}`} alt={el.purpose} /> : null;
    case "notification":
      return <div className={`stage-note level-${String(d.level ?? "info")}`}>{text}</div>;
    case "status":
    case "card":
    default:
      return (
        <div className="stage-text">
          {typeof d.title === "string" && d.title && <div className="stage-path">{d.title}</div>}
          {text}
        </div>
      );
  }
}
