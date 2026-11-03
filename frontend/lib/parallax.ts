// Mouse parallax for the orb: the pointer's place on screen becomes a small tilt, eased every frame so it glides.
// Pure, so node --test can check it.

function clamp1(v: number): number {
  if (!Number.isFinite(v)) return 0;
  return Math.max(-1, Math.min(1, v));
}

/**
 * The tilt the orb should glide to. nx, ny are the pointer's normalised screen position, -1..1 (clamped), with
 * +x to the right and +y DOWN (screen convention). The result is in camera space: `x` turns about the camera's
 * right axis (positive = the front of the orb dips toward a pointer below centre), `y` about the camera's up axis
 * (positive = the front turns toward a pointer right of centre). So the orb gently looks toward the cursor.
 */
export function targetTilt(nx: number, ny: number, maxRad: number): { x: number; y: number } {
  const m = Number.isFinite(maxRad) ? Math.abs(maxRad) : 0;
  return { x: clamp1(ny) * m, y: clamp1(nx) * m };
}

/** One frame of exponential easing toward target (k in 0..1, clamped); snaps when it is close enough to rest. */
export function ease(current: number, target: number, k: number): number {
  const kk = Math.max(0, Math.min(1, k));
  const next = current + (target - current) * kk;
  return Math.abs(target - next) < 1e-5 ? target : next;
}
