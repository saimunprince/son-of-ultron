/** The double-submit guard (audit 2026-10-29): every request is sent with `queue: true`, so a double Enter or a double
 * click on EXEC queued the same task twice and the server ran both. The same text again within RESUBMIT_MS of the last
 * sent request is the same press, not a second request. An answer to SYRAX's question is never held back. */
export const RESUBMIT_MS = 1500;

export type LastSent = { text: string; at: number } | null;

export function isResubmit(last: LastSent, text: string, now: number, asking: boolean): boolean {
  return !asking && last !== null && last.text === text && now - last.at < RESUBMIT_MS;
}
