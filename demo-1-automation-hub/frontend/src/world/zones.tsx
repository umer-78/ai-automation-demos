import { useFrame, type ThreeEvent } from "@react-three/fiber";
import { useEffect, useMemo, useRef, type RefObject } from "react";
import * as THREE from "three";
import { RoundedBoxGeometry } from "three/examples/jsm/geometries/RoundedBoxGeometry.js";
import { rb, studioMats } from "../components/FlowScene";
import { sectionText } from "../lib/siteText";
import type { Alert, ChannelRow, Cube, LogRow, SiteDraft } from "../lib/api";
import { SHOTS, ZONES, world, useWorld, type Zone } from "./store";
import {
  R0,
  R1,
  RUN,
  SITE_KINDS,
  SLAB,
  SOCKETS,
  SPEND,
  alertDays,
  bandOf,
  barHeight,
  barX,
  channelArcs,
  pedestalHeight,
  pedestalPos,
  rowZ,
  runPoint,
  slabY,
  slotTheta,
  socketPos,
  sortedRows,
  type Band,
  type ClientCol,
} from "./layout";

// ------------------------------------------------------------------ materials
const physical = (color: string, extra: THREE.MeshPhysicalMaterialParameters = {}) =>
  new THREE.MeshPhysicalMaterial({ color, roughness: 0.32, clearcoat: 0.8, clearcoatRoughness: 0.18, ...extra });
export const COLORS = { cobalt: "#2f5bff", teal: "#0f9f88", amber: "#f59e0b", red: "#e5484d", graphite: "#25282e", white: "#fafafa" };
const M = {
  cobalt: physical(COLORS.cobalt),
  teal: physical(COLORS.teal),
  amber: physical(COLORS.amber),
  red: physical(COLORS.red),
  graphite: physical("#353a42", { roughness: 0.38, clearcoat: 0.6 }),
  grey: physical("#d7dae0", { roughness: 0.5, clearcoat: 0.2 }),
  hover: physical(COLORS.cobalt, { emissive: new THREE.Color(COLORS.cobalt), emissiveIntensity: 0.35 }),
  belt: new THREE.MeshStandardMaterial({ color: "#2a2d33", roughness: 0.72, metalness: 0.1 }),
  ledTeal: new THREE.MeshStandardMaterial({ color: "#22d3a6", emissive: "#22d3a6", emissiveIntensity: 2.2 }),
  ledRed: new THREE.MeshStandardMaterial({ color: "#ff4d55", emissive: "#ff4d55", emissiveIntensity: 2.4 }),
  ledAmber: new THREE.MeshStandardMaterial({ color: "#f5a524", emissive: "#f5a524", emissiveIntensity: 1.6 }),
};
const halo = (color: string) => new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0, depthWrite: false });

/** Each zone builds itself the first time the camera arrives, then stays built. */
function useReveal(zone: Zone, still: boolean) {
  const p = useRef(still ? 1 : 0);
  const seen = useRef(still);
  useFrame((_, dt) => {
    const s = world.get();
    if (SHOTS[s.shot].zone === zone || s.focus?.zone === zone) seen.current = true;
    p.current += ((seen.current ? 1 : 0) - p.current) * Math.min(1, dt * 1.4);
  });
  return p;
}
const easeOut = (x: number) => 1 - Math.pow(1 - THREE.MathUtils.clamp(x, 0, 1), 3);

// ------------------------------------------------------------------ spend landscape and daily ribbon
const BAND_MAT: Record<Band, THREE.Material> = { better: M.teal, normal: studioMats.ceramic, watch: M.amber, alert: M.red, none: M.grey };


function Bars({ cube, alerts, still }: { cube: Cube; alerts: Alert[] | null; still: boolean }) {
  const reveal = useReveal("spend", still);
  const hover = useWorld((s) => s.hoverBar);
  const bars = useMemo(() => {
    const flagged = alertDays(cube, alerts);
    return sortedRows(cube).flatMap((r, ri) =>
      r.days.map((d, di) => ({ ri, di, h: barHeight(d.spend, cube.max_spend), band: flagged.has(`${r.client_id}:${di}`) ? ("alert" as Band) : bandOf(d.cpa, r.median_cpa) })),
    );
  }, [cube, alerts]);
  const geos = useMemo(
    () =>
      bars.map((b) => {
        const g = new RoundedBoxGeometry(SPEND.w, b.h, SPEND.d, 3, Math.min(0.07, b.h / 2 - 0.005));
        g.translate(0, b.h / 2, 0);
        return g;
      }),
    [bars],
  );
  useEffect(() => () => geos.forEach((g) => g.dispose()), [geos]);
  const refs = useRef<(THREE.Mesh | null)[]>([]);
  useFrame(() => {
    const p = reveal.current;
    for (let i = 0; i < bars.length; i++) {
      const m = refs.current[i];
      if (m) m.scale.y = Math.max(0.002, easeOut(p * 1.9 - (bars[i].di / 30) * 0.75 - bars[i].ri * 0.05));
    }
  });
  return (
    <group>
      {bars.map((b, i) => (
        <mesh
          key={`${b.ri}:${b.di}`}
          ref={(el) => {
            refs.current[i] = el;
          }}
          geometry={geos[i]}
          material={hover && hover.row === b.ri && hover.day === b.di ? M.hover : BAND_MAT[b.band]}
          position={[barX(b.di), 0, rowZ(b.ri)]}
          castShadow
          receiveShadow
          onPointerOver={(e: ThreeEvent<PointerEvent>) => {
            e.stopPropagation();
            world.set({ hoverBar: { row: b.ri, day: b.di } });
          }}
          onPointerOut={() => world.set({ hoverBar: null })}
        />
      ))}
    </group>
  );
}

export function SpendZone({ cube, alerts, still }: { cube: Cube | null; alerts: Alert[] | null; still: boolean }) {
  return <group>{cube && <Bars cube={cube} alerts={alerts} still={still} />}</group>;
}

// ------------------------------------------------------------------ channel ring
export const CHANNEL_MATS = [M.graphite, M.cobalt, studioMats.ceramic, M.teal, M.amber];

export function ChannelsZone({ channels, still }: { channels: ChannelRow[] | null; still: boolean }) {
  const reveal = useReveal("channels", still);
  const arcs = useMemo(() => channelArcs(channels ?? []), [channels]);
  const geos = useMemo(
    () =>
      arcs.map((a) => {
        const s = new THREE.Shape();
        s.absarc(0, 0, R1, a.a0, a.a1, false);
        s.absarc(0, 0, R0, a.a1, a.a0, true);
        s.closePath();
        return new THREE.ExtrudeGeometry(s, { depth: a.h, bevelEnabled: true, bevelThickness: 0.05, bevelSize: 0.05, bevelSegments: 4, curveSegments: 64 });
      }),
    [arcs],
  );
  useEffect(() => () => geos.forEach((g) => g.dispose()), [geos]);
  const refs = useRef<(THREE.Group | null)[]>([]);
  useFrame(() => {
    arcs.forEach((_, i) => {
      const g = refs.current[i];
      if (g) g.scale.set(1, 1, Math.max(0.002, easeOut(reveal.current * 1.6 - i * 0.18)));
    });
  });
  return (
    <group position={ZONES.channels}>
      <mesh material={studioMats.ceramic} position-y={0.06} castShadow receiveShadow>
        <cylinderGeometry args={[R1 + 0.45, R1 + 0.5, 0.12, 96]} />
      </mesh>
      {arcs.map((a, i) => (
        <group
          key={a.name}
          rotation-x={-Math.PI / 2}
          ref={(el) => {
            refs.current[i] = el;
          }}
        >
          <mesh geometry={geos[i]} material={CHANNEL_MATS[i % CHANNEL_MATS.length]} castShadow receiveShadow />
        </group>
      ))}
    </group>
  );
}

// ------------------------------------------------------------------ client pedestals

function Pedestal({ c, i, n, max, still, reveal }: { c: ClientCol; i: number; n: number; max: number; still: boolean; reveal: RefObject<number> }) {
  const focused = useWorld((s) => s.focusClient === c.client_id);
  const H = pedestalHeight(c.spend, max);
  const geo = useMemo(() => {
    const R = 0.66;
    const pts = [
      [0, 0],
      [R, 0],
      [R, H - 0.1],
      [R - 0.02, H - 0.035],
      [R - 0.1, H],
      [0, H],
    ].map(([x, y]) => new THREE.Vector2(x, y));
    return new THREE.LatheGeometry(pts, 72);
  }, [H]);
  useEffect(() => () => geo.dispose(), [geo]);
  const body = useRef<THREE.Group>(null);
  const ring = useMemo(() => halo(c.alerts ? COLORS.red : COLORS.cobalt), [c.alerts]);
  useFrame((state, dt) => {
    if (!body.current) return;
    const e = easeOut((reveal.current ?? 1) * 1.7 - i * 0.12);
    body.current.scale.y = Math.max(0.002, e);
    body.current.visible = e > 0.01;
    const lift = focused ? 0.18 : 0;
    body.current.position.y += (lift - body.current.position.y) * Math.min(1, dt * 7);
    ring.opacity += ((focused ? 0.85 : 0) - ring.opacity) * Math.min(1, dt * 7);
    if (!still && c.alerts) M.ledRed.emissiveIntensity = 1.6 + Math.sin(state.clock.elapsedTime * 4) * 0.9;
  });
  const [x, , z] = pedestalPos(i, n);
  return (
    <group position={[x, 0, z]}>
      <mesh rotation-x={-Math.PI / 2} position-y={0.004} material={ring}>
        <ringGeometry args={[0.82, 0.88, 96]} />
      </mesh>
      <group
        ref={body}
        onPointerOver={(e) => {
          e.stopPropagation();
          document.body.style.cursor = "pointer";
        }}
        onPointerOut={() => (document.body.style.cursor = "")}
        onClick={(e) => {
          e.stopPropagation();
          if (e.delta < 6) world.set({ focusClient: c.client_id });
        }}
      >
        <mesh geometry={geo} material={studioMats.ceramic} castShadow receiveShadow />
        <mesh position-y={H - 0.24} rotation-x={Math.PI / 2} material={c.alerts ? M.red : M.cobalt}>
          <torusGeometry args={[0.665, 0.032, 14, 96]} />
        </mesh>
        <mesh position={[0, 0.22, 0.66]} scale={0.04} geometry={rb(1, 1, 1, 0.5)} material={c.alerts ? M.ledRed : M.ledTeal} />
      </group>
    </group>
  );
}

export function ClientsZone({ clients, still }: { clients: ClientCol[] | null; still: boolean }) {
  const reveal = useReveal("clients", still);
  const list = useMemo(() => [...(clients ?? [])].sort((a, b) => b.spend - a.spend).slice(0, 7), [clients]);
  const max = Math.max(1, ...list.map((c) => c.spend));
  return (
    <group>
      {list.map((c, i) => (
        <Pedestal key={c.client_id} c={c} i={i} n={list.length} max={max} still={still} reveal={reveal} />
      ))}
    </group>
  );
}

// ------------------------------------------------------------------ automation runs on a conveyor

function ellipseCurve(da: number, db: number, y: number) {
  const pts: THREE.Vector3[] = [];
  for (let i = 0; i <= 64; i++) {
    const t = RUN.t0 - 0.12 + ((RUN.t1 - RUN.t0 + 0.24) * i) / 64;
    pts.push(new THREE.Vector3(ZONES.runs[0] + (RUN.a + da) * Math.cos(t), y, ZONES.runs[2] + (RUN.b + db) * Math.sin(t)));
  }
  return new THREE.CatmullRomCurve3(pts);
}

function Tile({ log, k, n, still }: { log: LogRow; k: number; n: number; still: boolean }) {
  const g = useRef<THREE.Group>(null);
  const state = useRef({ theta: still ? slotTheta(k, n) : RUN.t1 + 0.3, y: still ? 0 : 1.6 });
  useFrame((s, dt) => {
    const st = state.current;
    const ease = Math.min(1, dt * 3);
    st.theta += (slotTheta(k, n) - st.theta) * ease;
    st.y += (0 - st.y) * Math.min(1, dt * 4);
    const [x, , z] = runPoint(st.theta);
    if (!g.current) return;
    g.current.position.set(x, 0.2 + st.y + (k === 0 && !still ? Math.sin(s.clock.elapsedTime * 3) * 0.02 : 0), z);
    const dx = -RUN.a * Math.sin(st.theta);
    const dz = RUN.b * Math.cos(st.theta);
    g.current.rotation.y = -Math.atan2(dz, dx);
  });
  const ok = log.status === "success";
  return (
    <group ref={g}>
      <mesh geometry={rb(0.86, 0.16, 0.62, 0.05)} material={ok ? studioMats.ceramic : M.red} castShadow receiveShadow />
      <mesh geometry={rb(0.42, 0.03, 0.07, 0.015)} material={ok ? M.ledTeal : studioMats.white} position={[0, 0.09, 0.16]} />
    </group>
  );
}

export function RunsZone({ logs, still }: { logs: LogRow[] | null; still: boolean }) {
  const parts = useMemo(() => {
    const belt = (() => {
      const N = 96;
      const pos = new Float32Array((N + 1) * 6);
      const idx: number[] = [];
      for (let i = 0; i <= N; i++) {
        const t = RUN.t0 - 0.12 + ((RUN.t1 - RUN.t0 + 0.24) * i) / N;
        const [ix, , iz] = [ZONES.runs[0] + (RUN.a - 0.5) * Math.cos(t), 0, ZONES.runs[2] + (RUN.b - 0.5) * Math.sin(t)];
        const [ox, , oz] = [ZONES.runs[0] + (RUN.a + 0.5) * Math.cos(t), 0, ZONES.runs[2] + (RUN.b + 0.5) * Math.sin(t)];
        pos.set([ix, 0.1, iz, ox, 0.1, oz], i * 6);
        if (i < N) idx.push(i * 2, i * 2 + 2, i * 2 + 1, i * 2 + 1, i * 2 + 2, i * 2 + 3);
      }
      const g = new THREE.BufferGeometry();
      g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
      g.setIndex(idx);
      g.computeVertexNormals();
      return g;
    })();
    return {
      belt,
      railIn: new THREE.TubeGeometry(ellipseCurve(-0.55, -0.55, 0.12), 128, 0.05, 12),
      railOut: new THREE.TubeGeometry(ellipseCurve(0.55, 0.55, 0.12), 128, 0.05, 12),
    };
  }, []);
  const tiles = (logs ?? []).slice(0, RUN.slots);
  return (
    <group>
      <mesh geometry={parts.belt} material={M.belt} receiveShadow />
      <mesh geometry={parts.railIn} material={studioMats.metal} castShadow />
      <mesh geometry={parts.railOut} material={studioMats.metal} castShadow />
      {tiles.map((l, k) => (
        <Tile key={l.id} log={l} k={k} n={tiles.length} still={still} />
      ))}
    </group>
  );
}

// ------------------------------------------------------------------ website sections, exploded

function wrap(ctx: CanvasRenderingContext2D, text: string, x: number, y: number, maxW: number, lh: number, maxLines: number) {
  const words = text.split(" ");
  let line = "";
  let lines = 0;
  for (const w of words) {
    const test = line ? `${line} ${w}` : w;
    if (ctx.measureText(test).width > maxW && line) {
      ctx.fillText(lines === maxLines - 1 ? `${line}…` : line, x, y + lines * lh);
      lines += 1;
      line = w;
      if (lines >= maxLines) return;
    } else line = test;
  }
  if (line && lines < maxLines) ctx.fillText(line, x, y + lines * lh);
}

function paintSection(kind: (typeof SITE_KINDS)[number], draft: SiteDraft) {
  const c = document.createElement("canvas");
  c.width = 1024;
  c.height = 620;
  const ctx = c.getContext("2d")!;
  const pal = draft.palette ?? { primary: "#2f5bff", primary_dark: "#1e3a8a", primary_soft: "#e8edff", accent: "#f59e0b", canvas: "#ffffff" };
  const font = (w: number, s: number) => `${w} ${s}px "Geist Variable", system-ui, sans-serif`;
  const t = sectionText(draft);
  const pill = (x: number, y: number, label: string, bg: string, fg: string, size = 26) => {
    ctx.font = font(600, size);
    const w = ctx.measureText(label).width + size * 1.6;
    ctx.fillStyle = bg;
    ctx.beginPath();
    ctx.roundRect(x, y, w, size * 2.3, size * 1.15);
    ctx.fill();
    ctx.fillStyle = fg;
    ctx.fillText(label, x + size * 0.8, y + size * 1.5);
    return w;
  };
  const bg = kind === "hero" ? pal.primary : kind === "cta" ? pal.primary_dark : kind === "proof" ? pal.primary_soft : pal.canvas;
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, c.width, c.height);
  if (kind === "hero") {
    ctx.fillStyle = "rgba(255,255,255,0.78)";
    ctx.font = font(600, 28);
    ctx.fillText(draft.business_name, 64, 92);
    ctx.fillStyle = "#ffffff";
    ctx.font = font(650, 62);
    wrap(ctx, t.hero.title || draft.business_name, 64, 200, 880, 72, 3);
    let x = 64;
    t.hero.pills.slice(0, 2).forEach((p) => (x += pill(x, 404, p, "rgba(255,255,255,0.16)", "#ffffff", 22) + 14));
    pill(64, 486, t.hero.button || "Get in touch", pal.accent, "#111318", 28);
  } else if (kind === "services") {
    ctx.fillStyle = "#111318";
    ctx.font = font(650, 44);
    wrap(ctx, t.services.title || "Services", 64, 104, 900, 52, 1);
    const cards = t.services.cards.length ? t.services.cards : draft.inputs?.services ?? [];
    cards.slice(0, 3).forEach((label, i) => {
      const x = 64 + i * 304;
      ctx.fillStyle = pal.primary_soft;
      ctx.beginPath();
      ctx.roundRect(x, 180, 280, 360, 26);
      ctx.fill();
      ctx.fillStyle = pal.primary;
      ctx.beginPath();
      ctx.roundRect(x + 32, 216, 64, 64, 18);
      ctx.fill();
      ctx.fillStyle = "#111318";
      ctx.font = font(600, 30);
      wrap(ctx, label, x + 32, 340, 220, 38, 4);
    });
  } else if (kind === "proof") {
    ctx.fillStyle = "#111318";
    ctx.font = font(650, 46);
    wrap(ctx, t.proof.title || "What clients say", 64, 130, 890, 56, 2);
    t.proof.stats.slice(0, 3).forEach((label, i) => {
      const x = 64 + i * 304;
      ctx.fillStyle = "#ffffff";
      ctx.beginPath();
      ctx.roundRect(x, 300, 280, 220, 24);
      ctx.fill();
      ctx.fillStyle = pal.primary;
      ctx.fillRect(x + 32, 344, 72, 10);
      ctx.fillStyle = "#3b3f48";
      ctx.font = font(500, 28);
      wrap(ctx, label, x + 32, 412, 220, 36, 3);
    });
  } else {
    ctx.fillStyle = "#ffffff";
    ctx.font = font(650, 56);
    wrap(ctx, t.cta.title || `Talk to ${draft.business_name}`, 64, 180, 880, 66, 3);
    pill(64, 430, t.cta.button || "Book a call", "#ffffff", "#111318", 30);
  }
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 8;
  return tex;
}

export function SitesZone({ draft, still }: { draft: SiteDraft | null; still: boolean }) {
  const reveal = useReveal("sites", still);
  const textures = useMemo(() => (draft ? SITE_KINDS.map((k) => paintSection(k, draft)) : []), [draft]);
  useEffect(() => {
    if (!draft) return;
    let live = true;
    void document.fonts?.ready.then(() => {
      if (!live) return;
      SITE_KINDS.forEach((k, i) => {
        const fresh = paintSection(k, draft);
        textures[i].image = fresh.image;
        textures[i].needsUpdate = true;
      });
    });
    return () => {
      live = false;
    };
  }, [draft, textures]);
  useEffect(() => () => textures.forEach((t) => t.dispose()), [textures]);
  const faces = useMemo(() => textures.map((t) => new THREE.MeshPhysicalMaterial({ map: t, roughness: 0.42, clearcoat: 0.6, clearcoatRoughness: 0.2 })), [textures]);
  const refs = useRef<(THREE.Group | null)[]>([]);
  const lift = useRef([0, 0, 0, 0]);
  const flashAt = useRef<{ key: string | null; t: number }>({ key: null, t: -10 });
  useFrame((s, dt) => {
    const { slab, slabFlash } = world.get();
    if (slabFlash !== flashAt.current.key) flashAt.current = { key: slabFlash, t: s.clock.elapsedTime };
    refs.current.forEach((g, i) => {
      if (!g) return;
      const e = easeOut(reveal.current * 1.6 - i * 0.15);
      const key = SITE_KINDS[i];
      lift.current[i] += ((slab === key ? 0.38 : 0) - lift.current[i]) * Math.min(1, dt * 8);
      const since = flashAt.current.key === key ? s.clock.elapsedTime - flashAt.current.t : 10;
      const pop = since < 1.2 ? Math.sin(since * Math.PI * 2.5) * Math.exp(-since * 3) * 0.25 : 0;
      g.position.y = 0.3 + (slabY(i) - 0.3) * e + lift.current[i] + pop + (still ? 0 : Math.sin(s.clock.elapsedTime * 0.7 + i) * 0.03);
    });
  });
  return (
    <group position={ZONES.sites} rotation-y={0.32}>
      <mesh geometry={rb(4.6, 0.22, 3.1, 0.1)} material={studioMats.ceramic} position-y={0.11} castShadow receiveShadow />
      {faces.map((f, i) => (
        <group
          key={SITE_KINDS[i]}
          ref={(el) => {
            refs.current[i] = el;
          }}
        >
          <mesh geometry={rb(SLAB.w, 0.1, SLAB.d, 0.04)} material={studioMats.white} castShadow receiveShadow />
          <mesh rotation-x={-Math.PI / 2} position-y={0.052} material={f}>
            <planeGeometry args={[SLAB.w - 0.12, SLAB.d - 0.12]} />
          </mesh>
        </group>
      ))}
    </group>
  );
}

// ------------------------------------------------------------------ API key board

export function SettingsZone({ live }: { live: Record<string, boolean> }) {
  return (
    <group>
      <mesh geometry={rb(9.6, 0.3, 4, 0.12)} material={studioMats.ceramic} position={[ZONES.settings[0], 0.15, ZONES.settings[2]]} castShadow receiveShadow />
      {SOCKETS.map((k, i) => {
        const [x, y, z] = socketPos(i);
        const on = !!live[k];
        return (
          <group key={k} position={[x, y, z]}>
            <mesh material={studioMats.white} castShadow>
              <cylinderGeometry args={[0.46, 0.48, 0.18, 64]} />
            </mesh>
            <mesh rotation-x={Math.PI / 2} position-y={0.092} material={on ? M.ledTeal : M.ledAmber}>
              <torusGeometry args={[0.37, 0.018, 12, 96]} />
            </mesh>
            <mesh position-y={0.1} material={M.graphite}>
              <cylinderGeometry args={[0.24, 0.24, 0.04, 48]} />
            </mesh>
          </group>
        );
      })}
    </group>
  );
}
