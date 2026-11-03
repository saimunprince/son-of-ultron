import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";
import { ShaderPass } from "three/addons/postprocessing/ShaderPass.js";

export type OrbMode = "idle" | "listening" | "thinking" | "acting" | "speaking" | "error";

interface ModeProfile {
  speed: number; // rotation speed multiplier
  energy: number; // core surge + bloom boost
  heat: number; // 0 = the palette, 1 = fully its heat colour
}

const MODE_PROFILE: Record<OrbMode, ModeProfile> = {
  idle: { speed: 1, energy: 0, heat: 0 },
  listening: { speed: 1.4, energy: 0.35, heat: 0 },
  thinking: { speed: 2.6, energy: 0.6, heat: 0.15 },
  acting: { speed: 3.4, energy: 0.9, heat: 0.85 },
  speaking: { speed: 1.6, energy: 0.45, heat: 0.05 },
  error: { speed: 0.6, energy: 0.3, heat: 1 },
};

export interface OrbPalette {
  bright: number;
  mid: number;
  dim: number;
  faint: number;
  /** core, inner wireframe */
  hot: number;
  /** large soft glow around the core */
  glow: number;
  /** colour grade multiplier applied in post */
  grade: [number, number, number];
  /** per-channel weights after chromatic split */
  channels: [number, number, number];
  /** the colour the orb bleeds into while SYRAX acts (luminance multipliers) */
  heat: [number, number, number];
  /** character: rotation speed multiplier */
  spin: number;
  /** character: chromatic split multiplier */
  chroma: number;
  /** character: 0 = steady hologram, 1 = Ultron's glitches (flicker and tearing) */
  glitch: number;
  /** bloom threshold: higher keeps the core's detail instead of a blown-out glow */
  threshold: number;
  /** 0 = none, 1 = Ultron's menace: a heartbeat in the core, a target-lock reticle and a radar sweep */
  menace: number;
  /** the colour the orb bleeds into on an error */
  errorHeat: [number, number, number];
  bloom: number;
  exposure: number;
  /** returns a CSS colour for a floating code sprite */
  text: (alpha: number) => string;
  dust: [string, string, string, string];
}

export const PALETTES = {
  /** Red Ultron: crimson lines, a burning core (the owner, 2026-11-03: "ekdom red ultron") */
  ultron: {
    bright: 0xf04a3c,
    mid: 0xa8281f,
    dim: 0x5e1511,
    faint: 0x300b09,
    hot: 0xff3322,
    glow: 0xd8180c,
    grade: [1.16, 0.8, 0.78],
    channels: [1.0, 0.84, 0.82],
    bloom: 0.78,
    exposure: 0.6,
    heat: [2.1, 0.12, 0.08],
    spin: 1.2,
    chroma: 2.4,
    glitch: 1,
    threshold: 0.32,
    menace: 1,
    errorHeat: [2.1, 0.12, 0.08],
    text: (a: number) => {
      const r = (210 + Math.random() * 45) | 0;
      const g = (40 + Math.random() * 60) | 0;
      return `rgba(${r}, ${g}, ${(g * 0.8) | 0}, ${a})`;
    },
    dust: ["rgba(255,120,105,1)", "rgba(230,60,45,0.55)", "rgba(150,25,18,0.15)", "rgba(70,10,8,0)"],
  },
  /** Blue JARVIS: a cyan hologram; acting brightens it instead of turning it red */
  jarvis: {
    bright: 0x8fe3ff,
    mid: 0x2fa9e0,
    dim: 0x195f86,
    faint: 0x0c2f47,
    hot: 0xb5f6ff,
    glow: 0x22b8ff,
    grade: [0.78, 1.0, 1.18],
    channels: [0.82, 1.0, 1.1],
    bloom: 0.85,
    exposure: 0.66,
    heat: [0.55, 1.45, 1.9],
    spin: 0.8,
    chroma: 0.5,
    glitch: 0,
    threshold: 0.26,
    menace: 0,
    errorHeat: [1.9, 0.85, 0.15],
    text: (a: number) => {
      const g = (170 + Math.random() * 70) | 0;
      return `rgba(${(g * 0.45) | 0}, ${g}, 255, ${a})`;
    },
    dust: ["rgba(170,235,255,1)", "rgba(60,180,240,0.55)", "rgba(20,90,140,0.15)", "rgba(8,40,70,0)"],
  },
} satisfies Record<string, OrbPalette>;

export type OrbTheme = keyof typeof PALETTES;

export interface OrbSceneApi {
  /** Switch the orb's behaviour to reflect what SYRAX is doing. */
  setMode(mode: OrbMode): void;
  /** Short energy spike, e.g. when a tool fires. */
  pulse(strength?: number): void;
  /** Live audio level 0..1 (SYRAX's voice or the human's) driving the core. */
  setLevel(level: number): void;
  /** Rotate the camera around the orb by the given angles (radians). */
  rotateBy(deltaTheta: number, deltaPhi: number): void;
  /** Multiply the camera distance by `factor` (<1 zooms in, >1 zooms out). */
  zoomBy(factor: number): void;
  zoomIn(): void;
  zoomOut(): void;
  resetView(): void;
  /** What SYRAX is doing right now (a tool's name), written in a ring around the core; null clears it. */
  setActivity(text: string | null): void;
  /** Live readings (CPU, RAM, temperature ...) for JARVIS's data ring. */
  setReadout(text: string): void;
  dispose(): void;
}

const HOME_POSITION = new THREE.Vector3(0, 0.5, 5.5);
const MIN_DISTANCE = 0.6;
const MAX_DISTANCE = 40;

export function createOrbScene(container: HTMLElement, palette: OrbPalette = PALETTES.ultron): OrbSceneApi {
  const width = container.clientWidth;
  const height = container.clientHeight;

  // ——— SCENE ———
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(55, width / height, 0.1, 500);
  camera.position.copy(HOME_POSITION);

  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setSize(width, height);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = palette.exposure;
  container.appendChild(renderer.domElement);

  // ——— POST PROCESSING ———
  const composer = new EffectComposer(renderer);
  composer.addPass(new RenderPass(scene, camera));

  const bloom = new UnrealBloomPass(
    new THREE.Vector2(width, height),
    1.8, // strength
    0.4, // radius
    palette.threshold, // threshold
  );
  composer.addPass(bloom);

  // Chromatic aberration + color grade shader
  const chromaticShader = {
    uniforms: {
      tDiffuse: { value: null },
      uTime: { value: 0 },
      uIntensity: { value: 0.003 },
      uHeat: { value: 0 },
      uHeatColor: { value: new THREE.Vector3(...palette.heat) },
      uFlicker: { value: 0.02 + palette.glitch * 0.03 },
      uTear: { value: 0 },
      uTearY: { value: 0.5 },
      uGrade: { value: new THREE.Vector3(...palette.grade) },
      uChannels: { value: new THREE.Vector3(...palette.channels) },
    },
    vertexShader: `
      varying vec2 vUv;
      void main() {
        vUv = uv;
        gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
      }
    `,
    fragmentShader: `
      uniform sampler2D tDiffuse;
      uniform float uTime;
      uniform float uIntensity;
      uniform float uHeat;
      uniform vec3 uHeatColor;
      uniform float uFlicker;
      uniform float uTear;
      uniform float uTearY;
      uniform vec3 uGrade;
      uniform vec3 uChannels;
      varying vec2 vUv;
      void main() {
        // Ultron's glitch: a thin band of the picture slips sideways for a moment
        vec2 uv = vUv;
        uv.x += uTear * step(abs(uv.y - uTearY), 0.025);
        vec2 dir = uv - vec2(0.5);
        float d = length(dir);
        float offset = uIntensity * d;
        // flicker: a steady hologram barely, Ultron visibly
        float flicker = 1.0 + uFlicker * sin(uTime * 30.0) * sin(uTime * 7.3);
        vec4 cr = texture2D(tDiffuse, uv + dir * offset);
        vec4 cg = texture2D(tDiffuse, uv);
        vec4 cb = texture2D(tDiffuse, uv - dir * offset * 0.5);
        gl_FragColor = vec4(vec3(cr.r, cg.g, cb.b) * uChannels, 1.0) * flicker;
        // Palette colour grade
        gl_FragColor.rgb = mix(gl_FragColor.rgb, gl_FragColor.rgb * uGrade, 0.3);
        // heat: the whole orb bleeds into the palette's heat colour while SYRAX is acting
        float lum = dot(gl_FragColor.rgb, vec3(0.45, 0.45, 0.1));
        gl_FragColor.rgb = mix(gl_FragColor.rgb, lum * uHeatColor, uHeat);
      }
    `,
  };
  const chromaticPass = new ShaderPass(chromaticShader);
  composer.addPass(chromaticPass);

  // Controls
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.04;
  controls.minDistance = MIN_DISTANCE;
  controls.maxDistance = MAX_DISTANCE;
  controls.zoomSpeed = 1.4;
  controls.enablePan = false;

  // ——— COLORS ———
  const C_BRIGHT = palette.bright;
  const C_MID = palette.mid;
  const C_DIM = palette.dim;
  const C_FAINT = palette.faint;
  const C_HOT = palette.hot;

  // ——— ORB ROOT ———
  // Every part of the orb (shells, core, orbiting debris, text, dust, rings)
  // lives under this group.
  const orbGroup = new THREE.Group();
  scene.add(orbGroup);

  // ——— MATERIAL HELPERS ———
  function lineMat(color: number, opacity = 1) {
    return new THREE.LineBasicMaterial({
      color,
      transparent: true,
      opacity,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
  }

  // ——— UTILITY: Create ring at latitude ———
  function latRing(radius: number, lat: number, segs = 120) {
    const r = radius * Math.cos(lat);
    const y = radius * Math.sin(lat);
    const pts: THREE.Vector3[] = [];
    for (let i = 0; i <= segs; i++) {
      const a = (i / segs) * Math.PI * 2;
      pts.push(new THREE.Vector3(r * Math.cos(a), y, r * Math.sin(a)));
    }
    return new THREE.BufferGeometry().setFromPoints(pts);
  }

  // ——— UTILITY: Create meridian ———
  function meridian(radius: number, lon: number, segs = 120) {
    const pts: THREE.Vector3[] = [];
    for (let i = 0; i <= segs; i++) {
      const lat = (i / segs) * Math.PI - Math.PI / 2;
      pts.push(
        new THREE.Vector3(
          radius * Math.cos(lat) * Math.cos(lon),
          radius * Math.sin(lat),
          radius * Math.cos(lat) * Math.sin(lon),
        ),
      );
    }
    return new THREE.BufferGeometry().setFromPoints(pts);
  }

  // ═══════════════════════════════════════════════
  // LAYER 1: OUTER SHELL — dense wireframe grid
  // ═══════════════════════════════════════════════
  const outerShell = new THREE.Group();
  const R1 = 2.0;

  // Dense latitude rings (30+)
  for (let i = -15; i <= 15; i++) {
    const lat = (i / 15) * (Math.PI / 2) * 0.95;
    const opacity = i % 3 === 0 ? 0.5 : 0.12;
    const color = i % 3 === 0 ? C_MID : C_FAINT;
    outerShell.add(new THREE.Line(latRing(R1, lat), lineMat(color, opacity)));
  }

  // Dense meridians (24)
  for (let i = 0; i < 24; i++) {
    const lon = (i / 24) * Math.PI * 2;
    const isMajor = i % 6 === 0;
    outerShell.add(
      new THREE.Line(
        meridian(R1, lon),
        lineMat(isMajor ? C_MID : C_FAINT, isMajor ? 0.6 : 0.1),
      ),
    );
  }

  // 4 bright cross meridians (the "plus" shape) — wide bands
  const CROSS_LINES = 18;
  const CROSS_SPREAD = 0.25; // radians total width
  for (let i = 0; i < 4; i++) {
    const lon = (i / 4) * Math.PI * 2;
    for (let j = 0; j < CROSS_LINES; j++) {
      const t = (j / (CROSS_LINES - 1)) * 2 - 1; // -1 to 1
      const offset = (t * CROSS_SPREAD) / 2;
      const falloff = 1 - Math.abs(t) * 0.7; // brighter at center, dimmer at edges
      const opacity = 0.85 * falloff;
      const color = Math.abs(t) < 0.3 ? C_BRIGHT : C_MID;
      outerShell.add(
        new THREE.Line(meridian(R1, lon + offset, 200), lineMat(color, opacity)),
      );
    }
  }

  // Bright equator band — wide
  const EQ_LINES = 20;
  const EQ_SPREAD = 0.35;
  for (let j = 0; j < EQ_LINES; j++) {
    const t = (j / (EQ_LINES - 1)) * 2 - 1;
    const offset = (t * EQ_SPREAD) / 2;
    const falloff = 1 - Math.abs(t) * 0.65;
    const opacity = 0.8 * falloff;
    const color = Math.abs(t) < 0.3 ? C_BRIGHT : C_MID;
    outerShell.add(
      new THREE.Line(latRing(R1, offset, 200), lineMat(color, opacity)),
    );
  }

  orbGroup.add(outerShell);

  // ═══════════════════════════════════════════════
  // LAYER 2: GRID PANELS on the sphere surface
  // ═══════════════════════════════════════════════
  const panelGroup = new THREE.Group();

  function createSpherePanel(
    latCenter: number,
    lonCenter: number,
    latSpan: number,
    lonSpan: number,
    radius: number,
    divisions = 4,
  ) {
    const group = new THREE.Group();
    const mat = lineMat(C_DIM, 0.25);

    // horizontal lines
    for (let i = 0; i <= divisions; i++) {
      const lat = latCenter - latSpan / 2 + (i / divisions) * latSpan;
      const pts: THREE.Vector3[] = [];
      for (let j = 0; j <= divisions * 4; j++) {
        const lon = lonCenter - lonSpan / 2 + (j / (divisions * 4)) * lonSpan;
        pts.push(
          new THREE.Vector3(
            radius * Math.cos(lat) * Math.cos(lon),
            radius * Math.sin(lat),
            radius * Math.cos(lat) * Math.sin(lon),
          ),
        );
      }
      group.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), mat));
    }

    // vertical lines
    for (let j = 0; j <= divisions; j++) {
      const lon = lonCenter - lonSpan / 2 + (j / divisions) * lonSpan;
      const pts: THREE.Vector3[] = [];
      for (let i = 0; i <= divisions * 4; i++) {
        const lat = latCenter - latSpan / 2 + (i / (divisions * 4)) * latSpan;
        pts.push(
          new THREE.Vector3(
            radius * Math.cos(lat) * Math.cos(lon),
            radius * Math.sin(lat),
            radius * Math.cos(lat) * Math.sin(lon),
          ),
        );
      }
      group.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), mat));
    }

    return group;
  }

  // Scatter panels across the sphere
  for (let i = 0; i < 30; i++) {
    const lat = (Math.random() - 0.5) * Math.PI * 0.8;
    const lon = Math.random() * Math.PI * 2;
    const size = 0.15 + Math.random() * 0.25;
    const panel = createSpherePanel(
      lat,
      lon,
      size,
      size,
      R1 + 0.01,
      3 + Math.floor(Math.random() * 3),
    );
    panelGroup.add(panel);
  }
  orbGroup.add(panelGroup);

  // ═══════════════════════════════════════════════
  // LAYER 3: SECONDARY SHELL — offset, partial arcs
  // ═══════════════════════════════════════════════
  const shell2 = new THREE.Group();
  const R2 = 2.12;

  // Partial arcs at random latitudes
  for (let i = 0; i < 16; i++) {
    const lat = (Math.random() - 0.5) * Math.PI * 0.85;
    const startLon = Math.random() * Math.PI * 2;
    const arcLen = 0.3 + Math.random() * 1.2;
    const pts: THREE.Vector3[] = [];
    const segs = 60;
    const r = R2 * Math.cos(lat);
    const y = R2 * Math.sin(lat);
    for (let j = 0; j <= segs; j++) {
      const a = startLon + (j / segs) * arcLen;
      pts.push(new THREE.Vector3(r * Math.cos(a), y, r * Math.sin(a)));
    }
    shell2.add(
      new THREE.Line(
        new THREE.BufferGeometry().setFromPoints(pts),
        lineMat(C_MID, 0.2 + Math.random() * 0.3),
      ),
    );
  }

  // Partial meridian arcs
  for (let i = 0; i < 12; i++) {
    const lon = Math.random() * Math.PI * 2;
    const startLat = (Math.random() - 0.5) * Math.PI * 0.8;
    const arcLen = 0.3 + Math.random() * 0.8;
    const pts: THREE.Vector3[] = [];
    const segs = 40;
    for (let j = 0; j <= segs; j++) {
      const lat = startLat + (j / segs) * arcLen;
      pts.push(
        new THREE.Vector3(
          R2 * Math.cos(lat) * Math.cos(lon),
          R2 * Math.sin(lat),
          R2 * Math.cos(lat) * Math.sin(lon),
        ),
      );
    }
    shell2.add(
      new THREE.Line(
        new THREE.BufferGeometry().setFromPoints(pts),
        lineMat(C_DIM, 0.15 + Math.random() * 0.2),
      ),
    );
  }
  orbGroup.add(shell2);

  // ═══════════════════════════════════════════════
  // LAYER 4: INNER CORE — spiral geodesic
  // ═══════════════════════════════════════════════
  const innerCore = new THREE.Group();
  const R3 = 0.9;

  // Dense spirals
  for (let s = 0; s < 8; s++) {
    const pts: THREE.Vector3[] = [];
    const turns = 3 + Math.random() * 2;
    const segs = 300;
    const phase = (s / 8) * Math.PI * 2;
    for (let i = 0; i <= segs; i++) {
      const t = i / segs;
      const lat = t * Math.PI - Math.PI / 2;
      const lon = t * turns * Math.PI * 2 + phase;
      pts.push(
        new THREE.Vector3(
          R3 * Math.cos(lat) * Math.cos(lon),
          R3 * Math.sin(lat),
          R3 * Math.cos(lat) * Math.sin(lon),
        ),
      );
    }
    innerCore.add(
      new THREE.Line(
        new THREE.BufferGeometry().setFromPoints(pts),
        lineMat(C_BRIGHT, 0.3 + Math.random() * 0.2),
      ),
    );
  }

  // Inner latitude rings
  for (let i = -6; i <= 6; i++) {
    const lat = (i / 6) * (Math.PI / 2) * 0.9;
    innerCore.add(new THREE.Line(latRing(R3, lat, 80), lineMat(C_DIM, 0.2)));
  }

  // Inner meridians
  for (let i = 0; i < 12; i++) {
    const lon = (i / 12) * Math.PI * 2;
    innerCore.add(new THREE.Line(meridian(R3, lon, 80), lineMat(C_DIM, 0.15)));
  }

  orbGroup.add(innerCore);
  // JARVIS's heart is the arc reactor: the spiral core stays as a faint echo behind it, not a knot in front
  if (palette.menace === 0) {
    innerCore.traverse((o) => {
      const m = (o as THREE.Line).material as THREE.LineBasicMaterial | undefined;
      if (m && "opacity" in m) m.opacity *= 0.3;
    });
  }

  // ═══════════════════════════════════════════════
  // LAYER 5: INNERMOST CORE — bright hot center
  // ═══════════════════════════════════════════════
  const coreR = 0.25;

  // Icosahedron wireframe core
  const icoGeo = new THREE.IcosahedronGeometry(coreR, 1);
  const icoEdges = new THREE.EdgesGeometry(icoGeo);
  const icoWireMat = lineMat(C_HOT, 0.9);
  const icoWire = new THREE.LineSegments(icoEdges, icoWireMat);
  icoWire.visible = palette.menace > 0;
  orbGroup.add(icoWire);

  // Glowing center sphere — subtle, see-through
  // depthWrite off on every additive, see-through part (2026-11-03): writing depth made the glow sphere hide
  // the lines behind it, a dark disc that grew with each surge, in both themes
  const coreSphereMat = new THREE.MeshBasicMaterial({
    color: C_HOT,
    transparent: true,
    opacity: 0.15,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
  });
  const coreSphere = new THREE.Mesh(new THREE.SphereGeometry(0.15, 16, 16), coreSphereMat);
  orbGroup.add(coreSphere);

  // Larger faint glow — very subtle
  const glowSphereMat = new THREE.MeshBasicMaterial({
    color: palette.glow,
    transparent: true,
    opacity: 0.04,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
  });
  const glowSphere = new THREE.Mesh(new THREE.SphereGeometry(0.5, 16, 16), glowSphereMat);
  orbGroup.add(glowSphere);

  // ═══════════════════════════════════════════════
  // CODE TEXT — tiny, dense, scattered
  // ═══════════════════════════════════════════════
  const codeSnippets = [
    "sys.init()", "0xFF3A", "malloc()", ">> SCAN", "void*", "ACK",
    "SYNC OK", "ptr_ref", "exec()", "hash256", "::bind", "core.0",
    "01101001", "10110100", ">>> RDY", "HEAP 4K", "TCP/SYN",
    "mutex.lk", "IRQ 0x7", "DMA xfer", "REG EAX", "FAULT 0",
    "kernel.d", "pipe |>", "chmod +x", "fork()", "SIGTERM",
    "eth0: UP", "AES-256", "RSA 4096", "TLS 1.3", "HTTP/2",
    "latency", "200 OK", "PATCH /", "fn main", "use std",
    "NO STRINGS", "ULTRON.v2", "spawn()", "arc::new", ".unwrap",
  ];

  interface SpriteDrift {
    phi: number;
    theta: number;
    r: number;
    speed: number;
  }

  function makeTextSprite(text: string, size = 0.08) {
    const c = document.createElement("canvas");
    c.width = 256;
    c.height = 32;
    const ctx = c.getContext("2d")!;
    ctx.font = "bold 14px 'JetBrains Mono', 'Courier New', monospace";
    const alpha = 0.35 + Math.random() * 0.55;
    ctx.fillStyle = palette.text(alpha);
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(text, 128, 16);
    const tex = new THREE.CanvasTexture(c);
    tex.minFilter = THREE.LinearFilter;
    const s = new THREE.Sprite(
      new THREE.SpriteMaterial({
        map: tex,
        transparent: true,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
      }),
    );
    s.scale.set(size * 5, size * 0.7, 1);
    return s;
  }

  function scatterText(count: number, sizeFn: () => number, rFn: () => number, speedScale: [number, number]) {
    const group = new THREE.Group();
    for (let i = 0; i < count; i++) {
      const sp = makeTextSprite(
        codeSnippets[Math.floor(Math.random() * codeSnippets.length)],
        sizeFn(),
      );
      const phi = Math.acos(2 * Math.random() - 1);
      const theta = Math.random() * Math.PI * 2;
      const r = rFn();
      sp.position.set(
        r * Math.sin(phi) * Math.cos(theta),
        r * Math.cos(phi),
        r * Math.sin(phi) * Math.sin(theta),
      );
      sp.userData = {
        phi,
        theta,
        r,
        speed:
          (speedScale[0] + Math.random() * speedScale[1]) *
          (Math.random() > 0.5 ? 1 : -1),
      } satisfies SpriteDrift;
      group.add(sp);
    }
    return group;
  }

  // On outer sphere — dense text coverage
  const textOuter = scatterText(
    1200,
    () => 0.04 + Math.random() * 0.04,
    () => R1 + 0.03 + Math.random() * 0.08,
    [0.0002, 0.0008],
  );
  orbGroup.add(textOuter);

  // On inner core — more text
  const textInner = scatterText(
    100,
    () => 0.03 + Math.random() * 0.03,
    () => R3 + 0.02,
    [0.0005, 0.001],
  );
  orbGroup.add(textInner);

  // Floating ambient text between shells
  const textAmbient = scatterText(
    400,
    () => 0.03,
    () => R3 + 0.2 + Math.random() * (R1 - R3 - 0.3),
    [0.0003, 0.0006],
  );
  orbGroup.add(textAmbient);

  // ═══════════════════════════════════════════════
  // ORBITING DEBRIS / ROCKS
  // ═══════════════════════════════════════════════
  // Shared geometries for performance — reuse across 250 satellites
  const debrisGeos = [
    new THREE.IcosahedronGeometry(0.012, 0),
    new THREE.IcosahedronGeometry(0.02, 0),
    new THREE.IcosahedronGeometry(0.03, 1),
    new THREE.IcosahedronGeometry(0.008, 0),
    new THREE.TetrahedronGeometry(0.015, 0),
    new THREE.OctahedronGeometry(0.018, 0),
  ];
  interface DebrisOrbit {
    orbitR: number;
    speed: number;
    tiltX: number;
    tiltZ: number;
    phase: number;
  }
  const debris: THREE.Mesh[] = [];
  for (let i = 0; i < 250; i++) {
    const geo = debrisGeos[Math.floor(Math.random() * debrisGeos.length)];
    const mat = new THREE.MeshBasicMaterial({
      color: Math.random() > 0.7 ? C_BRIGHT : C_MID,
      transparent: true,
      opacity: 0.3 + Math.random() * 0.6,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const mesh = new THREE.Mesh(geo, mat);
    const orbitR = 1.2 + Math.random() * 4.0;
    const speed = (0.08 + Math.random() * 0.6) * (Math.random() > 0.5 ? 1 : -1);
    const tiltX = (Math.random() - 0.5) * Math.PI * 0.9;
    const tiltZ = (Math.random() - 0.5) * Math.PI * 0.5;
    const phase = Math.random() * Math.PI * 2;
    mesh.userData = { orbitR, speed, tiltX, tiltZ, phase } satisfies DebrisOrbit;
    debris.push(mesh);
    orbGroup.add(mesh);

    // ~15% get a faint trailing line
    if (Math.random() > 0.85) {
      const trailPts: THREE.Vector3[] = [];
      for (let j = 0; j <= 15; j++) {
        const a = -(j / 15) * 0.3;
        trailPts.push(
          new THREE.Vector3(
            orbitR * Math.cos(a + phase),
            orbitR * 0.08 * Math.sin(a * 3),
            orbitR * Math.sin(a + phase),
          ),
        );
      }
      const trail = new THREE.Line(
        new THREE.BufferGeometry().setFromPoints(trailPts),
        lineMat(C_FAINT, 0.08),
      );
      mesh.add(trail);
    }
  }

  // ═══════════════════════════════════════════════
  // DUST PARTICLES — lots of them
  // ═══════════════════════════════════════════════
  const dustCount = 2000;
  const dustPos = new Float32Array(dustCount * 3);

  for (let i = 0; i < dustCount; i++) {
    // Concentrate near the sphere, sparse further out
    const rr = 0.5 + Math.pow(Math.random(), 0.6) * 7;
    const theta = Math.random() * Math.PI * 2;
    const phi = Math.acos(2 * Math.random() - 1);
    dustPos[i * 3] = rr * Math.sin(phi) * Math.cos(theta);
    dustPos[i * 3 + 1] = rr * Math.cos(phi);
    dustPos[i * 3 + 2] = rr * Math.sin(phi) * Math.sin(theta);
  }

  const dustGeo = new THREE.BufferGeometry();
  dustGeo.setAttribute("position", new THREE.Float32BufferAttribute(dustPos, 3));

  // Soft dot texture
  const dotC = document.createElement("canvas");
  dotC.width = dotC.height = 64;
  const dCtx = dotC.getContext("2d")!;
  const g = dCtx.createRadialGradient(32, 32, 0, 32, 32, 32);
  [0, 0.2, 0.5, 1].forEach((stop, i) => g.addColorStop(stop, palette.dust[i]));
  dCtx.fillStyle = g;
  dCtx.fillRect(0, 0, 64, 64);

  const dustMat = new THREE.PointsMaterial({
    map: new THREE.CanvasTexture(dotC),
    size: 0.04,
    transparent: true,
    opacity: 0.5,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
    sizeAttenuation: true,
    color: C_BRIGHT,
  });
  const dustPoints = new THREE.Points(dustGeo, dustMat);
  orbGroup.add(dustPoints);

  // ═══════════════════════════════════════════════
  // SCANNING RINGS
  // ═══════════════════════════════════════════════
  function makeScanRing(radius: number, thickness = 0.015) {
    const geo = new THREE.RingGeometry(radius - thickness, radius + thickness, 120);
    const mat = new THREE.MeshBasicMaterial({
      color: C_BRIGHT,
      transparent: true,
      opacity: 0,
      blending: THREE.AdditiveBlending,
      side: THREE.DoubleSide,
      depthWrite: false,
    });
    const mesh = new THREE.Mesh(geo, mat);
    mesh.rotation.x = Math.PI / 2;
    return mesh;
  }

  // ═══════════════════════════════════════════════
  // MENACE (Ultron only): a target-lock reticle and a radar sweep, drawn facing the camera, thin and bounded
  // ═══════════════════════════════════════════════
  const menaceGroup = new THREE.Group();
  menaceGroup.visible = palette.menace > 0;
  scene.add(menaceGroup);

  function arc(radius: number, from: number, to: number, segments = 32) {
    const pts: THREE.Vector3[] = [];
    for (let i = 0; i <= segments; i++) {
      const a = from + ((to - from) * i) / segments;
      pts.push(new THREE.Vector3(Math.cos(a) * radius, Math.sin(a) * radius, 0));
    }
    return new THREE.BufferGeometry().setFromPoints(pts);
  }

  // tick ring: a short tick every 5 degrees, a long one every 30
  const tickRing = new THREE.Group();
  const tickPts: THREE.Vector3[] = [];
  for (let i = 0; i < 72; i++) {
    const a = (i / 72) * Math.PI * 2;
    const r0 = R1 * 1.16;
    const r1 = r0 + (i % 6 === 0 ? 0.14 : 0.05);
    tickPts.push(new THREE.Vector3(Math.cos(a) * r0, Math.sin(a) * r0, 0), new THREE.Vector3(Math.cos(a) * r1, Math.sin(a) * r1, 0));
  }
  const tickMat = lineMat(C_BRIGHT, 0.6);
  tickRing.add(new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(tickPts), tickMat));
  // a broken outer ring: 12 dashes
  const dashMat = lineMat(C_BRIGHT, 0.5);
  for (let i = 0; i < 12; i++) {
    const a = (i / 12) * Math.PI * 2;
    tickRing.add(new THREE.Line(arc(R1 * 1.24, a, a + 0.32, 12), dashMat));
  }
  menaceGroup.add(tickRing);

  // lock brackets: four hot arcs that turn the other way and close in while SYRAX acts
  const lock = new THREE.Group();
  const lockMat = lineMat(C_HOT, 0.85);
  for (let i = 0; i < 4; i++) {
    const a = (i / 4) * Math.PI * 2;
    lock.add(new THREE.Line(arc(R1 * 1.32, a - 0.22, a + 0.22, 16), lockMat));
    // a small inward notch at the middle of each bracket
    lock.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(Math.cos(a) * R1 * 1.32, Math.sin(a) * R1 * 1.32, 0),
      new THREE.Vector3(Math.cos(a) * R1 * 1.25, Math.sin(a) * R1 * 1.25, 0),
    ]), lockMat));
  }
  menaceGroup.add(lock);

  // radar sweep: a faint wedge with a bright leading edge
  const sweep = new THREE.Group();
  const sweepMat = new THREE.MeshBasicMaterial({
    color: C_HOT,
    transparent: true,
    opacity: 0.05,
    blending: THREE.AdditiveBlending,
    side: THREE.DoubleSide,
    depthWrite: false,
  });
  sweep.add(new THREE.Mesh(new THREE.RingGeometry(R1 * 0.25, R1 * 1.1, 48, 1, 0, 0.5), sweepMat));
  const edgeMat = lineMat(C_HOT, 0.9);
  sweep.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints([
    new THREE.Vector3(Math.cos(0.5) * R1 * 0.25, Math.sin(0.5) * R1 * 0.25, 0),
    new THREE.Vector3(Math.cos(0.5) * R1 * 1.1, Math.sin(0.5) * R1 * 1.1, 0),
  ]), edgeMat));
  menaceGroup.add(sweep);

  // ═══════════════════════════════════════════════
  // FACE: camera-facing parts for both themes (state rings) and each theme's own core
  // ═══════════════════════════════════════════════
  const faceGroup = new THREE.Group();
  scene.add(faceGroup);
  const hex = (c: number) => `#${c.toString(16).padStart(6, "0")}`;

  /** Text written around a circle on a canvas, drawn on a camera-facing plane. */
  function makeTextRing(radius: number, px: number, color: number) {
    const size = 1024;
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = size;
    const ctx = canvas.getContext("2d")!;
    const tex = new THREE.CanvasTexture(canvas);
    const mat = new THREE.MeshBasicMaterial({
      map: tex,
      transparent: true,
      opacity: 0,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });
    const span = radius * 2.3;
    const mesh = new THREE.Mesh(new THREE.PlaneGeometry(span, span), mat);
    const rPx = (radius / span) * size;
    let current = "";
    function set(text: string) {
      if (text === current) return;
      current = text;
      ctx.clearRect(0, 0, size, size);
      if (!text) {
        tex.needsUpdate = true;
        return;
      }
      ctx.font = `600 ${px}px ui-monospace, monospace`;
      ctx.fillStyle = hex(color);
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      const unit = `${text}   ◆   `;
      const circumference = 2 * Math.PI * rPx;
      const reps = Math.max(1, Math.floor(circumference / ctx.measureText(unit).width));
      const line = unit.repeat(reps);
      const step = (2 * Math.PI) / [...line].length;
      ctx.save();
      ctx.translate(size / 2, size / 2);
      [...line].forEach((ch, i) => {
        ctx.save();
        ctx.rotate(i * step);
        ctx.fillText(ch, 0, -rPx);
        ctx.restore();
      });
      ctx.restore();
      tex.needsUpdate = true;
    }
    return { mesh, mat, set };
  }

  // what SYRAX is doing: the running tool's name circles the core
  const activityRing = makeTextRing(1.25, 22, palette.hot);
  faceGroup.add(activityRing.mesh);
  let activityTarget = 0;

  // listening and speaking: a waveform ring around the core
  const WAVE_PTS = 160;
  const waveGeo = new THREE.BufferGeometry();
  waveGeo.setAttribute("position", new THREE.Float32BufferAttribute(new Float32Array(WAVE_PTS * 3), 3));
  const waveMat = lineMat(C_HOT, 0);
  const wave = new THREE.LineLoop(waveGeo, waveMat);
  faceGroup.add(wave);

  // JARVIS's core: an arc reactor (a triangle in rings) and data rings with live readings
  const reactor = new THREE.Group();
  const reactorMat = lineMat(C_HOT, 0.9);
  const reactorDim = lineMat(C_HOT, 0.7);
  reactor.add(new THREE.LineLoop(arc(0.5, 0, Math.PI * 2, 96), reactorMat));
  reactor.add(new THREE.LineLoop(arc(0.24, 0, Math.PI * 2, 64), reactorDim));
  reactor.add(new THREE.LineLoop(arc(0.08, 0, Math.PI * 2, 32), reactorMat));
  const tri: THREE.Vector3[] = [];
  for (let i = 0; i < 3; i++) {
    const a = Math.PI / 2 + (i * Math.PI * 2) / 3;
    tri.push(new THREE.Vector3(Math.cos(a) * 0.44, Math.sin(a) * 0.44, 0));
  }
  reactor.add(new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(tri), reactorMat));
  const reactorSegs = new THREE.Group();
  for (let i = 0; i < 10; i++) {
    const a = (i / 10) * Math.PI * 2;
    reactorSegs.add(new THREE.Line(arc(0.64, a + 0.06, a + 0.5, 10), reactorMat));
  }
  reactor.add(reactorSegs);
  const dataRings = new THREE.Group();
  const dataMat = lineMat(C_BRIGHT, 0.35);
  for (let i = 0; i < 18; i++) {
    const a = (i / 18) * Math.PI * 2;
    dataRings.add(new THREE.Line(arc(R1 * 0.74, a, a + 0.24, 8), dataMat));
  }
  const dataRings2 = new THREE.Group();
  dataRings2.add(new THREE.LineLoop(arc(R1 * 0.8, 0, Math.PI * 2, 128), lineMat(C_MID, 0.4)));
  for (let i = 0; i < 4; i++) {
    const a = (i / 4) * Math.PI * 2 + Math.PI / 4;
    dataRings2.add(new THREE.Line(arc(R1 * 0.84, a - 0.15, a + 0.15, 12), reactorMat));
  }
  const readoutRing = makeTextRing(R1 * 0.68, 17, palette.bright);
  const jarvisParts = [reactor, dataRings, dataRings2, readoutRing.mesh];
  for (const part of jarvisParts) {
    part.visible = palette.menace === 0;
    faceGroup.add(part);
  }

  // thinking: neural sparks, short bright links that flash between points inside the orb
  const SPARKS = 28;
  const sparkPos = new Float32Array(SPARKS * 6);
  const sparkCol = new Float32Array(SPARKS * 6);
  const sparkGeo = new THREE.BufferGeometry();
  sparkGeo.setAttribute("position", new THREE.BufferAttribute(sparkPos, 3));
  sparkGeo.setAttribute("color", new THREE.BufferAttribute(sparkCol, 3));
  const sparkMat = new THREE.LineBasicMaterial({
    vertexColors: true,
    transparent: true,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
  });
  orbGroup.add(new THREE.LineSegments(sparkGeo, sparkMat));
  const sparkLife = new Float32Array(SPARKS);
  const sparkRgb = new THREE.Color(C_HOT);
  function randomOnSphere(r: number, out: Float32Array, at: number) {
    const th = Math.random() * Math.PI * 2;
    const ph = Math.acos(2 * Math.random() - 1);
    out[at] = r * Math.sin(ph) * Math.cos(th);
    out[at + 1] = r * Math.cos(ph);
    out[at + 2] = r * Math.sin(ph) * Math.sin(th);
  }

  // performance guard: if frames get slow, the extras step down
  let frameAvg = 1 / 60;
  let lastFrame = performance.now();
  let lowPower = false;

  const scanRing1 = makeScanRing(R1, 0.01);
  const scanRing2 = makeScanRing(R1 * 0.7, 0.008);
  orbGroup.add(scanRing1, scanRing2);

  // ═══════════════════════════════════════════════
  // HEXAGONAL NODES — small tech details
  // ═══════════════════════════════════════════════
  for (let i = 0; i < 15; i++) {
    const phi = Math.acos(2 * Math.random() - 1);
    const theta = Math.random() * Math.PI * 2;
    const r = R1 + 0.02;
    const hexGeo = new THREE.CircleGeometry(0.03 + Math.random() * 0.02, 6);
    const hexEdges = new THREE.EdgesGeometry(hexGeo);
    const hex = new THREE.LineSegments(hexEdges, lineMat(C_MID, 0.5));
    hex.position.set(
      r * Math.sin(phi) * Math.cos(theta),
      r * Math.cos(phi),
      r * Math.sin(phi) * Math.sin(theta),
    );
    hex.lookAt(0, 0, 0);
    outerShell.add(hex);
  }

  // ═══════════════════════════════════════════════
  // GESTURE / PROGRAMMATIC CAMERA CONTROL
  // ═══════════════════════════════════════════════
  const sphericalScratch = new THREE.Spherical();
  const offsetScratch = new THREE.Vector3();

  function rotateBy(deltaTheta: number, deltaPhi: number) {
    offsetScratch.copy(camera.position).sub(controls.target);
    sphericalScratch.setFromVector3(offsetScratch);
    sphericalScratch.theta -= deltaTheta;
    sphericalScratch.phi = THREE.MathUtils.clamp(
      sphericalScratch.phi - deltaPhi,
      0.05,
      Math.PI - 0.05,
    );
    sphericalScratch.makeSafe();
    offsetScratch.setFromSpherical(sphericalScratch);
    camera.position.copy(controls.target).add(offsetScratch);
    camera.lookAt(controls.target);
  }

  function zoomBy(factor: number) {
    offsetScratch.copy(camera.position).sub(controls.target);
    const dist = THREE.MathUtils.clamp(
      offsetScratch.length() * factor,
      MIN_DISTANCE,
      MAX_DISTANCE,
    );
    offsetScratch.setLength(dist);
    camera.position.copy(controls.target).add(offsetScratch);
  }

  function resetView() {
    camera.position.copy(HOME_POSITION);
    controls.target.set(0, 0, 0);
    camera.lookAt(controls.target);
    controls.update();
  }

  // ═══════════════════════════════════════════════
  // ANIMATION
  // ═══════════════════════════════════════════════
  const timer = new THREE.Timer();
  timer.connect(document); // pauses elapsed time while the tab is hidden
  let flickerTimer = 0;
  let rafId = 0;
  let disposed = false;

  // Mode state, smoothed every frame so transitions glide instead of snapping
  let mode: OrbMode = "idle";
  let speed = 1;
  let energy = 0;
  let heat = 0;
  let tearUntil = 0;
  let kick = 0;

  function setMode(next: OrbMode) {
    mode = next;
  }

  // prefers-reduced-motion (audit 2026-10-29: the orb ignored it): no surges, and the motion runs at a fifth
  const reduced = typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  function pulse(strength = 1) {
    if (reduced) return;
    kick = Math.min(2, kick + strength);
  }

  let level = 0;
  let levelSmooth = 0;
  function setLevel(v: number) {
    level = Math.max(0, Math.min(1, v));
  }

  function animate() {
    if (disposed) return;
    rafId = requestAnimationFrame(animate);
    timer.update();
    const t = timer.getElapsed();

    const target = MODE_PROFILE[mode];
    speed += (target.speed - speed) * 0.04;
    energy += (target.energy - energy) * 0.05;
    heat += (target.heat - heat) * 0.035;
    kick *= 0.93;
    const s = (reduced ? speed * 0.2 : speed) * palette.spin;
    levelSmooth += (level - levelSmooth) * 0.35;
    const speakWave =
      mode === "speaking"
        ? levelSmooth > 0.01
          ? levelSmooth * 1.3
          : Math.abs(Math.sin(t * 9) * Math.sin(t * 3.7)) * 0.6
        : mode === "listening"
          ? levelSmooth * 0.8
          : 0;

    // Outer shell rotation
    outerShell.rotation.y += 0.0015 * s;
    outerShell.rotation.x = Math.sin(t * 0.08) * 0.05;

    // Panel group follows shell but with slight offset
    panelGroup.rotation.y += 0.0018 * s;
    panelGroup.rotation.x = Math.sin(t * 0.08 + 0.5) * 0.04;

    // Secondary shell counter-rotates slowly
    shell2.rotation.y -= 0.001 * s;
    shell2.rotation.z = Math.sin(t * 0.12) * 0.03;

    // Inner core — opposite, faster
    innerCore.rotation.y -= 0.005 * s;
    innerCore.rotation.z += 0.002 * s;
    innerCore.rotation.x = Math.cos(t * 0.1) * 0.08;

    // Innermost wireframe
    icoWire.rotation.x += 0.008 * s;
    icoWire.rotation.y += 0.012 * s;

    // Core pulse: a calm breath, and a bounded response to work and speech. The periodic "mega surges" are gone
    // (the owner, 2026-11-03: the core swelled into a red blob that covered the orb; keep it neat and clean).
    const wave1 = Math.sin(t * 1.2);
    const surge = Math.min(1, energy * 0.35 + kick * 0.25 + speakWave * 0.6);
    const coreScale = 1 + surge * 0.5 + Math.sin(t * 2) * 0.03;
    coreSphere.scale.setScalar(coreScale);
    coreSphereMat.opacity = Math.min(0.35, 0.1 + wave1 * 0.03 + surge * 0.15);
    glowSphere.scale.setScalar(1 + surge * 0.25);
    glowSphereMat.opacity = 0.02 + surge * 0.03;
    // the wireframe heart stays crisp and readable
    icoWire.scale.setScalar(1 + surge * 0.3);
    icoWireMat.opacity = Math.min(1, 0.6 + surge * 0.3);

    // Debris orbits
    debris.forEach((d) => {
      const u = d.userData as DebrisOrbit;
      const a = t * u.speed * (0.6 + s * 0.4) + u.phase;
      d.position.set(
        u.orbitR * Math.cos(a) * Math.cos(u.tiltX),
        u.orbitR * Math.sin(u.tiltX) * Math.sin(a * 0.8) + Math.sin(a * 0.3 + u.tiltZ) * 0.2,
        u.orbitR * Math.sin(a) * Math.cos(u.tiltZ),
      );
      d.rotation.x += 0.015;
      d.rotation.z += 0.01;
    });

    // Text drift
    const driftGroups: [THREE.Group, number][] = [
      [textOuter, 1],
      [textInner, 2],
      [textAmbient, 1.2],
    ];
    for (const [group, mult] of driftGroups) {
      group.children.forEach((sp) => {
        const u = sp.userData as SpriteDrift;
        u.theta += u.speed * mult * s;
        sp.position.set(
          u.r * Math.sin(u.phi) * Math.cos(u.theta),
          u.r * Math.cos(u.phi),
          u.r * Math.sin(u.phi) * Math.sin(u.theta),
        );
      });
    }

    // Menace: the reticle faces the camera, turns, and locks tighter while SYRAX acts; the core beats
    if (lowPower) sweep.visible = false;
    if (menaceGroup.visible) {
      menaceGroup.quaternion.copy(camera.quaternion);
      const m = reduced ? 0.2 : 1;
      tickRing.rotation.z += 0.0015 * m * (1 + heat * 2);
      lock.rotation.z -= 0.004 * m * (1 + heat * 3);
      const tighten = 1 - heat * 0.08 - kick * 0.02;
      lock.scale.setScalar(tighten);
      lockMat.opacity = 0.75 + heat * 0.2 + Math.abs(Math.sin(t * 3)) * 0.05;
      sweep.rotation.z = reduced ? 0 : -t * (1.2 + heat * 2.5);
      sweepMat.opacity = 0.07 + heat * 0.05;
      // heartbeat: lub-dub every 1.6 s (faster while acting), small and bounded
      const period = 1.6 - heat * 0.6;
      const p = t % period;
      const beat = reduced ? 0 : Math.exp(-((p * p) / 0.003)) + 0.6 * Math.exp(-(((p - 0.22) * (p - 0.22)) / 0.003));
      icoWire.scale.multiplyScalar(1 + beat * 0.1);
      icoWireMat.opacity = Math.min(1, icoWireMat.opacity + beat * 0.25);
      coreSphereMat.opacity = Math.min(0.4, coreSphereMat.opacity + beat * 0.08);
    }

    // ——— performance guard ———
    const nowMs = performance.now();
    frameAvg += ((nowMs - lastFrame) / 1000 - frameAvg) * 0.02;
    lastFrame = nowMs;
    if (!lowPower && frameAvg > 1 / 35 && t > 6) {
      lowPower = true; // slow machine: drop the extras, keep the orb
      renderer.setPixelRatio(1);
    }

    faceGroup.quaternion.copy(camera.quaternion);

    // ——— what SYRAX is doing: the activity ring ———
    activityRing.mat.opacity += (activityTarget - activityRing.mat.opacity) * 0.08;
    activityRing.mesh.rotation.z -= 0.004 * (reduced ? 0.2 : 1);

    // ——— listening / speaking: a waveform around the core ———
    const voiceOn = mode === "listening" || mode === "speaking";
    waveMat.opacity += ((voiceOn ? 0.75 : 0) - waveMat.opacity) * 0.1;
    if (waveMat.opacity > 0.01) {
      const arr = (waveGeo.getAttribute("position") as THREE.BufferAttribute).array as Float32Array;
      const amp = 0.03 + levelSmooth * 0.16;
      for (let i = 0; i < WAVE_PTS; i++) {
        const a = (i / WAVE_PTS) * Math.PI * 2;
        const n = reduced ? 0 : Math.sin(a * 6 + t * 7) * 0.5 + Math.sin(a * 11 - t * 5) * 0.3 + Math.sin(a * 17 + t * 9) * 0.2;
        const r = 0.6 + amp * n;
        arr[i * 3] = Math.cos(a) * r;
        arr[i * 3 + 1] = Math.sin(a) * r;
        arr[i * 3 + 2] = 0;
      }
      waveGeo.getAttribute("position").needsUpdate = true;
    }

    // ——— JARVIS: the reactor turns, the data rings turn against each other ———
    if (reactor.visible) {
      const m = reduced ? 0.2 : 1;
      reactor.rotation.z += 0.002 * m;
      reactorSegs.rotation.z -= 0.01 * m * (1 + heat * 2);
      dataRings.rotation.z += 0.0012 * m * (1 + heat);
      dataRings2.rotation.z -= 0.0008 * m;
      readoutRing.mesh.rotation.z += 0.0006 * m;
      reactorMat.opacity = 1;
      reactor.scale.setScalar(1 + Math.sin(t * 2) * 0.015 + heat * 0.05);
    }

    // ——— thinking: neural sparks ———
    const sparkRate = lowPower || reduced ? 0 : mode === "thinking" ? 0.45 : mode === "acting" ? 0.25 : 0.015;
    for (let i = 0; i < SPARKS; i++) {
      if (sparkLife[i] <= 0 && Math.random() < sparkRate / 4) {
        sparkLife[i] = 1;
        randomOnSphere(0.5 + Math.random() * 1.0, sparkPos, i * 6);
        randomOnSphere(0.5 + Math.random() * 1.0, sparkPos, i * 6 + 3);
      }
      sparkLife[i] = Math.max(0, sparkLife[i] - 0.06);
      const k = sparkLife[i];
      for (let v = 0; v < 2; v++) {
        sparkCol[i * 6 + v * 3] = sparkRgb.r * k;
        sparkCol[i * 6 + v * 3 + 1] = sparkRgb.g * k;
        sparkCol[i * 6 + v * 3 + 2] = sparkRgb.b * k;
      }
    }
    sparkGeo.getAttribute("position").needsUpdate = true;
    sparkGeo.getAttribute("color").needsUpdate = true;

    // Scan rings sweeping
    const scanY1 = Math.sin(t * 0.4) * R1;
    scanRing1.position.y = scanY1;
    const scanS1 = Math.sqrt(Math.max(0, R1 * R1 - scanY1 * scanY1)) / R1;
    scanRing1.scale.set(scanS1, scanS1, 1);
    (scanRing1.material as THREE.MeshBasicMaterial).opacity = 0.2 * scanS1;

    const scanY2 = Math.sin(t * 0.6 + 2) * R3;
    scanRing2.position.y = scanY2;
    const scanS2 = Math.sqrt(Math.max(0, R3 * R3 - scanY2 * scanY2)) / R3;
    scanRing2.scale.set(scanS2, scanS2, 1);
    (scanRing2.material as THREE.MeshBasicMaterial).opacity = 0.15 * scanS2;

    // Dust rotation
    dustPoints.rotation.y += 0.0002;

    // Random flicker on some panels
    flickerTimer += 0.016;
    if (flickerTimer > 0.1) {
      flickerTimer = 0;
      panelGroup.children.forEach((p) => {
        if (Math.random() > 0.95) {
          p.visible = !p.visible;
        }
      });
    }

    // Bloom pulse
    bloom.strength = palette.bloom + Math.sin(t * 0.8) * 0.08 + energy * 0.3 + kick * 0.25;
    chromaticPass.uniforms.uHeat.value = heat;
    (chromaticPass.uniforms.uHeatColor.value as THREE.Vector3).set(...(mode === "error" ? palette.errorHeat : palette.heat));
    chromaticPass.uniforms.uIntensity.value = (0.003 + kick * 0.004 + heat * 0.002) * palette.chroma;
    // Ultron glitches now and then (more while it acts); a JARVIS hologram never does
    if (!reduced && palette.glitch > 0) {
      if (t > tearUntil && Math.random() < 0.004 * palette.glitch * (1 + heat * 3)) {
        tearUntil = t + 0.06 + Math.random() * 0.08;
        chromaticPass.uniforms.uTearY.value = Math.random();
        chromaticPass.uniforms.uTear.value = (Math.random() - 0.5) * 0.04;
        kick = Math.min(2, kick + 0.25);
      } else if (t > tearUntil) {
        chromaticPass.uniforms.uTear.value = 0;
      }
    }

    // Update chromatic aberration time
    chromaticPass.uniforms.uTime.value = t;

    controls.update();
    composer.render();
  }

  animate();

  // ——— RESIZE ———
  function onResize() {
    const w = container.clientWidth;
    const h = container.clientHeight;
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    renderer.setSize(w, h);
    composer.setSize(w, h);
  }
  window.addEventListener("resize", onResize);

  // ——— CLEANUP ———
  function dispose() {
    disposed = true;
    cancelAnimationFrame(rafId);
    timer.dispose();
    window.removeEventListener("resize", onResize);
    controls.dispose();
    scene.traverse((obj) => {
      const mesh = obj as THREE.Mesh;
      if (mesh.geometry) mesh.geometry.dispose();
      const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
      for (const mat of mats) {
        if (!mat) continue;
        const anyMat = mat as THREE.Material & { map?: THREE.Texture };
        anyMat.map?.dispose();
        mat.dispose();
      }
    });
    composer.dispose();
    renderer.dispose();
    renderer.domElement.remove();
  }

  return {
    setMode,
    pulse,
    setLevel,
    rotateBy,
    zoomBy,
    zoomIn: () => zoomBy(0.65),
    zoomOut: () => zoomBy(1.55),
    resetView,
    setActivity(text: string | null) {
      if (text) activityRing.set(text.toUpperCase());
      activityTarget = text ? 0.85 : 0;
    },
    setReadout(text: string) {
      readoutRing.set(text);
      readoutRing.mat.opacity = text ? 0.8 : 0;
    },
    dispose,
  };
}
