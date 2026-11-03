"use client";

import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";

import { nextIndex, paletteRows, rowId, selectable, type PaletteCommand, type PaletteRow } from "@/lib/palette";

import styles from "./CommandPalette.module.css";

type Props = {
  open: boolean;
  commands: PaletteCommand[];
  /** Runs a command id, or `ask:<query>` for the free-text row. The palette closes itself after. */
  onRun: (id: string) => void;
  onClose: () => void;
};

/** Ctrl+K / Cmd+K anywhere (inputs included) calls `toggle`. */
export function usePaletteHotkey(toggle: () => void) {
  const ref = useRef(toggle);
  useEffect(() => {
    ref.current = toggle;
  }, [toggle]);
  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && e.key.toLowerCase() === "k") {
        e.preventDefault();
        ref.current();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}

export default function CommandPalette({ open, commands, onRun, onClose }: Props) {
  if (!open || typeof document === "undefined") return null;
  // mounted only while open, so the query and selection reset on every close
  return createPortal(<Palette commands={commands} onRun={onRun} onClose={onClose} />, document.body);
}

function Palette({ commands, onRun, onClose }: Omit<Props, "open">) {
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0); // index into the selectable rows
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const baseId = useId();

  const rows = useMemo(() => paletteRows(query, commands), [query, commands]);
  const pick = useMemo(() => rows.flatMap((r, i) => (selectable(r) ? [i] : [])), [rows]);
  const cur = pick.length ? Math.min(active, pick.length - 1) : -1; // commands may shrink while open
  const activeRow = cur >= 0 ? pick[cur] : -1;
  const optionId = (i: number) => `${baseId}-row-${i}`;

  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    inputRef.current?.focus();
    return () => prev?.focus?.(); // hand focus back to wherever it was
  }, []);

  useEffect(() => {
    if (activeRow < 0) return;
    listRef.current?.querySelector<HTMLElement>(`[data-row="${activeRow}"]`)?.scrollIntoView({ block: "nearest" });
  }, [activeRow]);

  const run = (row: PaletteRow | undefined) => {
    const id = row ? rowId(row) : null;
    if (!id) return;
    onRun(id);
    onClose();
  };

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    const step = (d: number) => {
      e.preventDefault();
      setActive(nextIndex(cur, d, pick.length));
    };
    if (e.key === "ArrowDown" || (e.key === "n" && e.ctrlKey)) step(1);
    else if (e.key === "ArrowUp" || (e.key === "p" && e.ctrlKey)) step(-1);
    else if (e.key === "Tab") step(e.shiftKey ? -1 : 1);
    else if (e.key === "PageDown") step(5);
    else if (e.key === "PageUp") step(-5);
    else if (e.key === "Enter" && !e.nativeEvent.isComposing) {
      e.preventDefault();
      run(rows[activeRow]);
    } else if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation(); // never let the HUD's Esc (abort task) see this one
      if (query) {
        setQuery("");
        setActive(0);
      } else onClose();
    }
  };

  return (
    <div className={styles.backdrop} onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={styles.panel} role="dialog" aria-modal="true" aria-label="Command palette">
        <div className={styles.search}>
          <svg className={styles.glyph} viewBox="0 0 16 16" aria-hidden="true">
            <circle cx="7" cy="7" r="4.5" />
            <path d="M10.5 10.5 14 14" />
          </svg>
          <input
            ref={inputRef}
            className={styles.input}
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setActive(0);
            }}
            onKeyDown={onKeyDown}
            placeholder="Type a command or ask SYRAX…"
            spellCheck={false}
            autoComplete="off"
            role="combobox"
            aria-expanded="true"
            aria-controls={`${baseId}-list`}
            aria-activedescendant={activeRow >= 0 ? optionId(activeRow) : undefined}
          />
          <kbd className={styles.esc}>ESC</kbd>
        </div>

        <div ref={listRef} id={`${baseId}-list`} className={styles.list} role="listbox" aria-label="Commands">
          {rows.map((row, i) => {
            if (row.kind === "header") {
              return (
                <div key={`h-${row.section}`} className={styles.section} role="presentation">
                  {row.section}
                </div>
              );
            }
            const isActive = i === activeRow;
            const disabled = row.kind === "cmd" && !!row.cmd.disabled;
            const cls = [
              styles.row,
              isActive && styles.active,
              row.kind === "cmd" && row.cmd.danger && styles.danger,
              disabled && styles.disabled,
              row.kind === "ask" && styles.ask,
            ]
              .filter(Boolean)
              .join(" ");
            return (
              <div
                key={row.kind === "cmd" ? row.cmd.id : "ask"}
                id={optionId(i)}
                data-row={i}
                className={cls}
                role="option"
                aria-selected={isActive}
                aria-disabled={disabled || undefined}
                onMouseMove={() => {
                  const p = pick.indexOf(i);
                  if (p >= 0 && p !== cur) setActive(p);
                }}
                onMouseDown={(e) => e.preventDefault()} // keep focus in the input
                onClick={() => run(row)}
              >
                {row.kind === "cmd" ? (
                  <>
                    <span className={styles.label}>{highlight(row.cmd.label, row.match)}</span>
                    {query.trim() && <span className={styles.tag}>{row.cmd.section}</span>}
                    {row.cmd.hint && <Hint text={row.cmd.hint} />}
                  </>
                ) : (
                  <>
                    <span className={styles.askMark} aria-hidden="true">
                      ›
                    </span>
                    <span className={styles.label}>
                      Ask SYRAX: <span className={styles.askQuery}>“{row.query}”</span>
                    </span>
                    <Hint text="↵" />
                  </>
                )}
              </div>
            );
          })}
          {rows.length === 0 && <div className={styles.empty}>No commands</div>}
        </div>

        <div className={styles.footer} aria-hidden="true">
          <span>
            <kbd>↑</kbd>
            <kbd>↓</kbd> navigate
          </span>
          <span>
            <kbd>↵</kbd> run
          </span>
          <span>
            <kbd>esc</kbd> close
          </span>
        </div>
      </div>
    </div>
  );
}

/** Wraps matched characters in <mark>, merging runs. */
function highlight(label: string, match: number[]): ReactNode {
  if (!match.length) return label;
  const hit = new Set(match);
  const out: ReactNode[] = [];
  let i = 0;
  while (i < label.length) {
    const on = hit.has(i);
    let j = i;
    while (j < label.length && hit.has(j) === on) j++;
    const text = label.slice(i, j);
    out.push(on ? <mark key={i}>{text}</mark> : text);
    i = j;
  }
  return out;
}

/** Short shortcut-like hints ("B", "Ctrl+K") become key caps; anything else is plain text. */
function Hint({ text }: { text: string }) {
  const keys = text.split("+");
  if (/\s/.test(text) || keys.some((k) => !k || k.length > 5)) return <span className={styles.hintText}>{text}</span>;
  return (
    <span className={styles.hint}>
      {keys.map((k, i) => (
        <kbd key={i}>{k}</kbd>
      ))}
    </span>
  );
}
