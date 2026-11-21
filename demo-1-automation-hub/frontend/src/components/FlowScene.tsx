import { AccumulativeShadows, Environment, Lightformer, OrbitControls, PerformanceMonitor, RandomizedLight } from "@react-three/drei";
import { Canvas, useFrame, useThree, type ThreeElements, type ThreeEvent } from "@react-three/fiber";
import { Component, useEffect, useMemo, useRef, useState, type ReactNode, type RefObject } from "react";
import * as THREE from "three";
import type { OrbitControls as OrbitControlsImpl } from "three-stdlib";
import { RoundedBoxGeometry } from "three/examples/jsm/geometries/RoundedBoxGeometry.js";
import { EffectComposer } from "three/examples/jsm/postprocessing/EffectComposer.js";
import { OutputPass } from "three/examples/jsm/postprocessing/OutputPass.js";
import { RenderPass } from "three/examples/jsm/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/examples/jsm/postprocessing/UnrealBloomPass.js";
import { FLOW_EDGES, FLOW_NODES, type FlowNodeKey, type FlowSignal, type Glyph } from "./flowNodes";

/**
 * The onboarding automation as a physical model on a studio floor: ceramic bases, a glass block per
 * step with its icon inside, brushed metal rails between them. Teal beads are runs that worked, red
 * ones take the error route to Slack, and a real event (a client added, a forced failure) sends a
 * larger bead down the exact path it took. Light comes from a procedural softbox studio, shadows are
 * accumulated soft shadows, and every frame gets ambient occlusion, a faint bloom and PBR neutral
 * tone mapping.
 */
export const STAGE_BG = "#f2f3f5";
const KEYS = Object.keys(FLOW_NODES) as FlowNodeKey[];
export const FLOW_FLOOR: Record<FlowNodeKey, [number, number]> = {
  intake: [-6.0, 0],
  make: [-3.2, 0],
  seo: [-0.4, -2.5],
  ads: [-0.4, 0],
  web: [-0.4, 2.5],
  ai: [2.4, 0],
  db: [5.2, -1.5],
  slack: [5.2, 1.5],
  errors: [2.4, 2.95],
};
const BASE = { w: 1.8, h: 0.28, r: 0.1 };
const GLASS = { w: 1.34, h: 0.96, r: 0.16 };
const RAIL_Y = 0.14;
const GLASS_Y = BASE.h + GLASS.h / 2 + 0.015;
export const FLOW_CHIP_Y = BASE.h + GLASS.h + 0.34;
const FLAT: Partial<Record<Glyph, boolean>> = { table: true, database: true };
type Flash = Partial<Record<FlowNodeKey, { at: number; strength: number }>>;

// ------------------------------------------------------------------ rails
const edgeKey = (e: { from: FlowNodeKey; to: FlowNodeKey }) => `${e.from}-${e.to}`;
function railCurve(a: FlowNodeKey, b: FlowNodeKey) {
  const [ax, az] = FLOW_FLOOR[a];
  const [bx, bz] = FLOW_FLOOR[b];
  const off = BASE.w / 2 + 0.03;
  if (Math.abs(bz - az) > Math.abs(bx - ax) * 1.2) {
    const s = Math.sign(bz - az);
    const p0 = new THREE.Vector3(ax, RAIL_Y, az + off * s);
    const p3 = new THREE.Vector3(bx, RAIL_Y, bz - off * s);
    const mz = (p0.z + p3.z) / 2;
    return new THREE.CubicBezierCurve3(p0, new THREE.Vector3(ax, RAIL_Y, mz), new THREE.Vector3(bx, RAIL_Y, mz), p3);
  }
  const s = Math.sign(bx - ax);
  const p0 = new THREE.Vector3(ax + off * s, RAIL_Y, az);
  const p3 = new THREE.Vector3(bx - off * s, RAIL_Y, bz);
  const mx = (p0.x + p3.x) / 2;
  return new THREE.CubicBezierCurve3(p0, new THREE.Vector3(mx, RAIL_Y, az), new THREE.Vector3(mx, RAIL_Y, bz), p3);
}
const CURVES: Record<string, THREE.CubicBezierCurve3> = Object.fromEntries(FLOW_EDGES.map((e) => [edgeKey(e), railCurve(e.from, e.to)]));
const LENGTHS: Record<string, number> = Object.fromEntries(Object.entries(CURVES).map(([k, c]) => [k, c.getLength()]));
const EDGE_TO: Record<string, FlowNodeKey> = Object.fromEntries(FLOW_EDGES.map((e) => [edgeKey(e), e.to]));

// ------------------------------------------------------------------ shared materials and geometry
export const studioMats = {
  ceramic: new THREE.MeshPhysicalMaterial({ color: "#fafafa", roughness: 0.36, clearcoat: 0.45, clearcoatRoughness: 0.3 }),
  white: new THREE.MeshPhysicalMaterial({ color: "#fbfbfc", roughness: 0.34, clearcoat: 0.7, clearcoatRoughness: 0.2 }),
  grey: new THREE.MeshPhysicalMaterial({ color: "#c9ccd3", roughness: 0.4, clearcoat: 0.4 }),
  glass: new THREE.MeshPhysicalMaterial({
    color: "#ffffff",
    transmission: 1,
    thickness: 0.35,
    roughness: 0.02,
    ior: 1.35,
    attenuationColor: new THREE.Color("#d5e3f1"),
    attenuationDistance: 1.7,
    specularIntensity: 1,
    envMapIntensity: 1.2,
    clearcoat: 1,
    clearcoatRoughness: 0.04,
  }),
  metal: new THREE.MeshStandardMaterial({ color: "#d3d6dc", metalness: 1, roughness: 0.24, envMapIntensity: 1.15 }),
  ok: new THREE.MeshStandardMaterial({ color: "#0f9f88", emissive: "#2dd4bf", emissiveIntensity: 2.6, roughness: 0.25 }),
  fail: new THREE.MeshStandardMaterial({ color: "#e5484d", emissive: "#ff5a5f", emissiveIntensity: 2.6, roughness: 0.25 }),
  okTrail: new THREE.MeshBasicMaterial({ color: "#5eead4", transparent: true, opacity: 0.32, depthWrite: false }),
  failTrail: new THREE.MeshBasicMaterial({ color: "#ff8a8d", transparent: true, opacity: 0.32, depthWrite: false }),
};
const rbCache = new Map<string, RoundedBoxGeometry>();
export function rb(w: number, h: number, d: number, r: number) {
  const key = `${w},${h},${d},${r}`;
  let g = rbCache.get(key);
  if (!g) {
    g = new RoundedBoxGeometry(w, h, d, 4, Math.min(r, Math.min(w, h, d) / 2 - 0.002));
    rbCache.set(key, g);
  }
  return g;
}
function roundedTriangle(R: number, c: number) {
  const v = [0, 1, 2].map((i) => new THREE.Vector2(Math.sin((i * 2 * Math.PI) / 3) * R, Math.cos((i * 2 * Math.PI) / 3) * R));
  const s = new THREE.Shape();
  for (let i = 0; i < 3; i++) {
    const p = v[i];
    const a = p.clone().add(v[(i + 2) % 3].clone().sub(p).setLength(c));
    const b = p.clone().add(v[(i + 1) % 3].clone().sub(p).setLength(c));
    if (i === 0) s.moveTo(a.x, a.y);
    else s.lineTo(a.x, a.y);
    s.quadraticCurveTo(p.x, p.y, b.x, b.y);
  }
  s.closePath();
  return s;
}
const geo = {
  base: new RoundedBoxGeometry(BASE.w, BASE.h, BASE.w, 6, BASE.r),
  glass: new RoundedBoxGeometry(GLASS.w, GLASS.h, GLASS.w, 8, GLASS.r),
  sphere: new THREE.SphereGeometry(1, 32, 20),
  bead: new THREE.SphereGeometry(1, 20, 14),
  octa: new THREE.OctahedronGeometry(1),
  ring: new THREE.RingGeometry(1.38, 1.44, 128),
  collar: new THREE.CylinderGeometry(0.062, 0.062, 0.09, 28),
  disk: new THREE.LatheGeometry(
    [
      [0, -0.065],
      [0.27, -0.065],
      [0.293, -0.058],
      [0.3, -0.04],
      [0.3, 0.04],
      [0.293, 0.058],
      [0.27, 0.065],
      [0, 0.065],
    ].map(([x, y]) => new THREE.Vector2(x, y)),
    72,
  ),
  tri: (() => {
    const g = new THREE.ExtrudeGeometry(roundedTriangle(0.38, 0.1), { depth: 0.06, bevelEnabled: true, bevelThickness: 0.03, bevelSize: 0.03, bevelSegments: 4, curveSegments: 14 });
    g.center();
    return g;
  })(),
};

type MeshProps = ThreeElements["mesh"];
function RB({ s, r = 0.03, m, ...rest }: { s: [number, number, number]; r?: number; m: THREE.Material } & MeshProps) {
  return <mesh geometry={rb(s[0], s[1], s[2], r)} material={m} {...rest} />;
}
const UP = new THREE.Vector3(0, 1, 0);
function Rod({ a, b, r, m }: { a: [number, number, number]; b: [number, number, number]; r: number; m: THREE.Material }) {
  const { pos, quat, len } = useMemo(() => {
    const A = new THREE.Vector3(...a);
    const B = new THREE.Vector3(...b);
    const d = B.clone().sub(A);
    return { pos: A.clone().add(B).multiplyScalar(0.5), quat: new THREE.Quaternion().setFromUnitVectors(UP, d.clone().normalize()), len: d.length() };
  }, [a, b]);
  return (
    <mesh position={pos} quaternion={quat} material={m}>
      <capsuleGeometry args={[r, Math.max(0.001, len - 2 * r), 8, 20]} />
    </mesh>
  );
}

/** Each step's icon, built from rounded solids so it catches light like the real object would. */
function Glyph3D({ glyph, accent }: { glyph: Glyph; accent: THREE.Material }) {
  const { white, grey } = studioMats;
  switch (glyph) {
    case "table":
      return (
        <group position-y={-0.1}>
          <RB s={[0.88, 0.07, 0.66]} r={0.03} m={white} position-y={-0.08} />
          {[-0.27, 0, 0.27].flatMap((x) =>
            [-0.14, 0.14].map((z) => <RB key={`${x}:${z}`} s={[0.23, 0.11, 0.22]} r={0.035} m={z < 0 ? accent : white} position={[x, 0.01, z]} />),
          )}
        </group>
      );
    case "router":
      return (
        <group>
          <mesh geometry={geo.sphere} material={accent} scale={0.14} position={[-0.22, 0, 0]} />
          {([[0.26, 0.24, 0], [0.31, 0, 0], [0.26, -0.24, 0]] as [number, number, number][]).map((e, i) => (
            <group key={i}>
              <Rod a={[-0.22, 0, 0]} b={e} r={0.028} m={white} />
              <mesh geometry={geo.sphere} material={white} scale={0.075} position={e} />
            </group>
          ))}
        </group>
      );
    case "search":
      return (
        <group position={[-0.05, 0.05, 0]}>
          <mesh material={accent}>
            <torusGeometry args={[0.2, 0.055, 28, 72]} />
          </mesh>
          <Rod a={[0.15, -0.15, 0]} b={[0.33, -0.33, 0]} r={0.05} m={white} />
        </group>
      );
    case "target":
      return (
        <group>
          <mesh material={white}>
            <torusGeometry args={[0.31, 0.042, 24, 96]} />
          </mesh>
          <mesh material={accent}>
            <torusGeometry args={[0.19, 0.046, 24, 72]} />
          </mesh>
          <mesh geometry={geo.sphere} material={accent} scale={0.075} />
        </group>
      );
    case "browser":
      return (
        <group>
          <RB s={[0.86, 0.6, 0.07]} r={0.04} m={white} />
          <RB s={[0.86, 0.11, 0.08]} r={0.035} m={accent} position={[0, 0.245, 0.004]} />
          <RB s={[0.34, 0.3, 0.05]} r={0.024} m={accent} position={[-0.18, -0.07, 0.05]} />
          <RB s={[0.28, 0.05, 0.04]} r={0.018} m={grey} position={[0.2, 0.02, 0.045]} />
          <RB s={[0.28, 0.05, 0.04]} r={0.018} m={grey} position={[0.2, -0.08, 0.045]} />
          <RB s={[0.18, 0.05, 0.04]} r={0.018} m={grey} position={[0.15, -0.18, 0.045]} />
        </group>
      );
    case "doc":
      return (
        <group position-x={-0.05}>
          <RB s={[0.52, 0.68, 0.07]} r={0.04} m={white} />
          {[0.16, 0.04, -0.08].map((y, i) => (
            <RB key={y} s={[i === 2 ? 0.2 : 0.32, 0.045, 0.03]} r={0.014} m={grey} position={[i === 2 ? -0.06 : 0, y, 0.045]} />
          ))}
          <group position={[0.31, 0.27, 0.09]}>
            <mesh geometry={geo.octa} material={accent} scale={[0.07, 0.18, 0.07]} />
            <mesh geometry={geo.octa} material={accent} scale={[0.18, 0.07, 0.07]} />
          </group>
        </group>
      );
    case "database":
      return (
        <group position-y={-0.02}>
          {[0.17, 0, -0.17].map((y, i) => (
            <mesh key={y} geometry={geo.disk} material={i === 1 ? accent : white} position-y={y} />
          ))}
        </group>
      );
    case "hash":
      return (
        <group rotation-z={0.18}>
          <RB s={[0.09, 0.62, 0.09]} r={0.04} m={accent} position={[-0.11, 0, 0]} />
          <RB s={[0.09, 0.62, 0.09]} r={0.04} m={accent} position={[0.11, 0, 0]} />
          <RB s={[0.62, 0.09, 0.09]} r={0.04} m={white} position={[0, 0.11, 0.05]} />
          <RB s={[0.62, 0.09, 0.09]} r={0.04} m={white} position={[0, -0.11, 0.05]} />
        </group>
      );
    case "warning":
      return (
        <group>
          <mesh geometry={geo.tri} material={accent} />
          <RB s={[0.07, 0.2, 0.05]} r={0.024} m={white} position={[0, 0.03, 0.07]} />
          <mesh geometry={geo.sphere} material={white} scale={0.042} position={[0, -0.13, 0.07]} />
        </group>
      );
  }
}

// ------------------------------------------------------------------ one step of the automation
function Station({
  k,
  hovered,
  selected,
  flash,
  still,
  onHover,
  onSelect,
}: {
  k: FlowNodeKey;
  hovered: boolean;
  selected: boolean;
  flash: RefObject<Flash>;
  still: boolean;
  onHover: (k: FlowNodeKey | null) => void;
  onSelect: (k: FlowNodeKey) => void;
}) {
  const n = FLOW_NODES[k];
  const lift = useRef<THREE.Group>(null);
  const icon = useRef<THREE.Group>(null);
  const glass = useRef<THREE.Mesh>(null);
  const tint = k === "errors" ? "#e5484d" : "#2f5bff";
  const accent = useMemo(
    () => new THREE.MeshPhysicalMaterial({ color: tint, roughness: 0.3, clearcoat: 0.9, clearcoatRoughness: 0.14, emissive: new THREE.Color(tint), emissiveIntensity: 0.03 }),
    [tint],
  );
  const ledColor = k === "errors" ? "#ff4d55" : "#22d3a6";
  const led = useMemo(() => new THREE.MeshStandardMaterial({ color: ledColor, emissive: ledColor, emissiveIntensity: 1.4 }), [ledColor]);
  const halo = useMemo(() => new THREE.MeshBasicMaterial({ color: tint, transparent: true, opacity: 0, depthWrite: false }), [tint]);
  const phase = KEYS.indexOf(k) * 1.37;
  const tilt = FLAT[n.glyph] ? 0 : -0.45;

  useFrame((state, delta) => {
    const t = state.clock.elapsedTime;
    const f = flash.current?.[k];
    const pulse = f ? f.strength * Math.exp(-Math.max(0, t - f.at) * 3.2) : 0;
    accent.emissiveIntensity = 0.03 + pulse * 1.5;
    led.emissiveIntensity = 1.3 + pulse * 6;
    glass.current?.scale.setScalar(1 + pulse * 0.018);
    if (icon.current && !still) {
      icon.current.rotation.y = 0.24 * Math.sin(t * 0.55 + phase);
      icon.current.position.y = GLASS_Y + 0.022 * Math.sin(t * 0.8 + phase);
    }
    const ease = Math.min(1, delta * 9);
    if (lift.current) lift.current.position.y += ((hovered || selected ? 0.08 : 0) - lift.current.position.y) * ease;
    halo.opacity += ((selected ? 0.85 : hovered ? 0.4 : 0) - halo.opacity) * ease;
  });

  const over = (e: ThreeEvent<PointerEvent>) => {
    e.stopPropagation();
    onHover(k);
  };
  const click = (e: ThreeEvent<MouseEvent>) => {
    e.stopPropagation();
    if (e.delta < 6) onSelect(k);
  };
  return (
    <group position={[FLOW_FLOOR[k][0], 0, FLOW_FLOOR[k][1]]}>
      <mesh geometry={geo.ring} material={halo} rotation-x={-Math.PI / 2} position-y={0.004} />
      <group ref={lift} onPointerOver={over} onPointerOut={() => onHover(null)} onClick={click}>
        <mesh geometry={geo.base} material={studioMats.ceramic} position-y={BASE.h / 2} castShadow />
        <mesh geometry={geo.sphere} material={led} scale={0.034} position={[BASE.w / 2 - 0.24, BASE.h / 2, BASE.w / 2 + 0.004]} />
        <mesh ref={glass} geometry={geo.glass} material={studioMats.glass} position-y={GLASS_Y} castShadow />
        <group ref={icon} position-y={GLASS_Y} rotation-x={tilt}>
          <Glyph3D glyph={n.glyph} accent={accent} />
        </group>
      </group>
    </group>
  );
}

function Rails() {
  const parts = useMemo(
    () =>
      FLOW_EDGES.map((e) => {
        const c = CURVES[edgeKey(e)];
        const ends = [0, 1].map((u) => ({ pos: c.getPointAt(u), quat: new THREE.Quaternion().setFromUnitVectors(UP, c.getTangentAt(u).normalize()) }));
        return { key: edgeKey(e), tube: new THREE.TubeGeometry(c, 120, 0.03, 16, false), ends };
      }),
    [],
  );
  return (
    <group>
      {parts.map((p) => (
        <group key={p.key}>
          <mesh geometry={p.tube} material={studioMats.metal} castShadow />
          {p.ends.map((end, i) => (
            <mesh key={i} geometry={geo.collar} material={studioMats.metal} position={end.pos} quaternion={end.quat} castShadow />
          ))}
        </group>
      ))}
    </group>
  );
}

// ------------------------------------------------------------------ runs travelling through the model
type Bead = { route: string[]; i: number; t: number; ok: boolean; big: boolean; group: number; split?: ("seo" | "ads" | "web")[] };
const MAX_BEADS = 72;
const TRAIL = 4;
function mulberry(seed: number) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function Beads({ failureRate, still, signal, flash }: { failureRate: number; still: boolean; signal: FlowSignal | null; flash: RefObject<Flash> }) {
  const okHead = useRef<THREE.InstancedMesh>(null);
  const badHead = useRef<THREE.InstancedMesh>(null);
  const okTrail = useRef<THREE.InstancedMesh>(null);
  const badTrail = useRef<THREE.InstancedMesh>(null);
  const sim = useRef({ beads: [] as Bead[], timer: 0.2, group: 1, done: new Set<number>(), rng: mulberry(7) });
  const tmp = useMemo(() => ({ m: new THREE.Matrix4(), p: new THREE.Vector3(), q: new THREE.Quaternion(), s: new THREE.Vector3() }), []);

  useEffect(() => {
    if (still) {
      // a calm still frame: a few runs caught mid-route
      sim.current.beads = [
        { route: ["intake-make"], i: 0, t: 0.55, ok: true, big: false, group: 0 },
        { route: ["make-ads"], i: 0, t: 0.4, ok: true, big: false, group: 0 },
        { route: ["seo-ai"], i: 0, t: 0.7, ok: true, big: false, group: 0 },
        { route: ["ai-db"], i: 0, t: 0.5, ok: true, big: false, group: 0 },
        { route: ["errors-slack"], i: 0, t: 0.45, ok: false, big: false, group: 0 },
      ];
    }
  }, [still]);

  useEffect(() => {
    if (!signal || still) return;
    const s = sim.current;
    s.beads.push({ route: ["intake-make"], i: 0, t: 0, ok: signal.ok, big: true, group: s.group++, split: signal.branches.length ? signal.branches : ["ads"] });
  }, [signal, still]);

  useFrame((state, delta) => {
    const s = sim.current;
    const now = state.clock.elapsedTime;
    if (!still) {
      const dt = Math.min(delta, 1 / 20);
      s.timer -= dt;
      if (s.timer <= 0 && s.beads.length < MAX_BEADS - 6) {
        s.timer = 0.75 + s.rng() * 0.6;
        s.beads.push({ route: ["intake-make"], i: 0, t: 0, ok: s.rng() >= failureRate, big: false, group: s.group++ });
      }
      const next: Bead[] = [];
      for (const b of s.beads) {
        const leg = b.route[b.i];
        b.t += (dt * (b.big ? 2.1 : 2.6)) / LENGTHS[leg];
        if (b.t < 1) {
          next.push(b);
          continue;
        }
        const node = EDGE_TO[leg];
        if (flash.current) flash.current[node] = { at: now, strength: b.big ? 1 : 0.5 };
        if (b.i < b.route.length - 1) {
          b.i += 1;
          b.t = 0;
          next.push(b);
          continue;
        }
        if (node === "make") {
          const branches = b.split ?? [(["seo", "ads", "web"] as const)[Math.floor(s.rng() * 3)]];
          for (const br of branches) next.push({ ...b, route: [`make-${br}`, `${br}-ai`], i: 0, t: 0, split: undefined });
        } else if (node === "ai" && !s.done.has(b.group)) {
          s.done.add(b.group);
          if (b.ok) {
            next.push({ ...b, route: ["ai-db"], i: 0, t: 0 }, { ...b, route: ["ai-slack"], i: 0, t: 0 });
          } else {
            next.push({ ...b, route: ["ai-errors", "errors-slack"], i: 0, t: 0 });
          }
        }
      }
      s.beads = next;
      if (s.done.size > 400) s.done.clear();
    }
    let ok = 0;
    let bad = 0;
    let okT = 0;
    let badT = 0;
    const put = (mesh: THREE.InstancedMesh | null, idx: number, r: number) => {
      if (!mesh) return;
      tmp.s.setScalar(r);
      tmp.m.compose(tmp.p, tmp.q, tmp.s);
      mesh.setMatrixAt(idx, tmp.m);
    };
    for (const b of s.beads) {
      const leg = b.route[b.i];
      const c = CURVES[leg];
      const r = b.big ? 0.1 : 0.068;
      c.getPointAt(Math.min(1, b.t), tmp.p);
      tmp.p.y += r * 0.55;
      if (b.ok && ok < MAX_BEADS) put(okHead.current, ok++, r);
      else if (!b.ok && bad < MAX_BEADS) put(badHead.current, bad++, r);
      for (let g = 1; g <= TRAIL; g++) {
        const tt = b.t - (g * 0.085) / LENGTHS[leg];
        if (tt <= 0) break;
        c.getPointAt(tt, tmp.p);
        tmp.p.y += r * 0.55;
        if (b.ok && okT < MAX_BEADS * TRAIL) put(okTrail.current, okT++, r * (1 - g * 0.17));
        else if (!b.ok && badT < MAX_BEADS * TRAIL) put(badTrail.current, badT++, r * (1 - g * 0.17));
      }
    }
    for (const [mesh, count] of [
      [okHead.current, ok],
      [badHead.current, bad],
      [okTrail.current, okT],
      [badTrail.current, badT],
    ] as const) {
      if (!mesh) continue;
      mesh.count = count;
      mesh.instanceMatrix.needsUpdate = true;
    }
  });

  return (
    <group>
      <instancedMesh ref={okHead} args={[geo.bead, studioMats.ok, MAX_BEADS]} frustumCulled={false} />
      <instancedMesh ref={badHead} args={[geo.bead, studioMats.fail, MAX_BEADS]} frustumCulled={false} />
      <instancedMesh ref={okTrail} args={[geo.bead, studioMats.okTrail, MAX_BEADS * TRAIL]} frustumCulled={false} />
      <instancedMesh ref={badTrail} args={[geo.bead, studioMats.failTrail, MAX_BEADS * TRAIL]} frustumCulled={false} />
    </group>
  );
}

/** The model alone (rails, stations, runs), placed by the 3D world behind every page. */
export function FlowModel({
  failureRate,
  still,
  signal,
  selected,
  hovered,
  onHover,
  onSelect,
}: {
  failureRate: number;
  still: boolean;
  signal: FlowSignal | null;
  selected: FlowNodeKey | null;
  hovered: FlowNodeKey | null;
  onHover: (k: FlowNodeKey | null) => void;
  onSelect: (k: FlowNodeKey) => void;
}) {
  const flash = useRef<Flash>({});
  return (
    <group>
      <Rails />
      {KEYS.map((k) => (
        <Station key={k} k={k} hovered={hovered === k} selected={selected === k} flash={flash} still={still} onHover={onHover} onSelect={onSelect} />
      ))}
      <Beads failureRate={failureRate} still={still} signal={signal} flash={flash} />
    </group>
  );
}

// ------------------------------------------------------------------ camera, labels, frame
const TARGET = new THREE.Vector3(-0.35, 0.25, -0.25);
function CameraRig({ still, controls }: { still: boolean; controls: RefObject<OrbitControlsImpl | null> }) {
  const camera = useThree((s) => s.camera);
  const size = useThree((s) => s.size);
  const busy = useRef(false);
  const idleSince = useRef(-10);
  useEffect(() => {
    const aspect = size.width / Math.max(1, size.height);
    const dist = 14.6 * Math.max(1, 1.95 / aspect);
    camera.position.setFromSphericalCoords(dist, 0.86, 0).add(TARGET);
    camera.lookAt(TARGET);
    const c = controls.current;
    if (c) {
      c.target.copy(TARGET);
      c.update();
    }
  }, [camera, controls, size.width, size.height]);
  useEffect(() => {
    const c = controls.current;
    if (!c) return;
    const start = () => (busy.current = true);
    const end = () => {
      busy.current = false;
      idleSince.current = performance.now();
    };
    c.addEventListener("start", start);
    c.addEventListener("end", end);
    return () => {
      c.removeEventListener("start", start);
      c.removeEventListener("end", end);
    };
  }, [controls]);
  useFrame((state, delta) => {
    const c = controls.current;
    if (!c || still || busy.current || performance.now() - idleSince.current < 2500) return;
    const t = state.clock.elapsedTime;
    const k = 1 - Math.exp(-delta * 0.9);
    const az = 0.13 * Math.sin(t * 0.14);
    const pol = 0.86 + 0.035 * Math.sin(t * 0.1 + 1);
    c.setAzimuthalAngle(c.getAzimuthalAngle() + (az - c.getAzimuthalAngle()) * k);
    c.setPolarAngle(c.getPolarAngle() + (pol - c.getPolarAngle()) * k);
  });
  return null;
}

/** Labels are real DOM text pinned to 3D anchors, so they stay sharp at any resolution. */
function ChipAnchors({ chips }: { chips: RefObject<Partial<Record<FlowNodeKey, HTMLElement | null>>> }) {
  const camera = useThree((s) => s.camera);
  const size = useThree((s) => s.size);
  const v = useMemo(() => new THREE.Vector3(), []);
  useFrame(() => {
    for (const k of KEYS) {
      const el = chips.current?.[k];
      if (!el) continue;
      v.set(FLOW_FLOOR[k][0], FLOW_CHIP_Y, FLOW_FLOOR[k][1]).project(camera);
      const t =
        v.z < 1
          ? `translate3d(${Math.round(((v.x + 1) / 2) * size.width)}px, ${Math.round(((1 - v.y) / 2) * size.height)}px, 0) translate(-50%, -100%)`
          : "translate3d(-9999px, 0, 0)";
      if (el.dataset.at === t) continue;
      el.dataset.at = t;
      el.style.transform = t;
    }
  });
  return null;
}

export function Post() {
  const gl = useThree((s) => s.gl);
  const scene = useThree((s) => s.scene);
  const camera = useThree((s) => s.camera);
  const size = useThree((s) => s.size);
  const dpr = useThree((s) => s.viewport.dpr);
  const composer = useMemo(() => {
    const target = new THREE.WebGLRenderTarget(2, 2, { type: THREE.HalfFloatType, samples: 4 });
    const c = new EffectComposer(gl, target);
    c.addPass(new RenderPass(scene, camera));
    c.addPass(new UnrealBloomPass(new THREE.Vector2(256, 256), 0.28, 0.45, 1.35));
    c.addPass(new OutputPass());
    return c;
  }, [gl, scene, camera]);
  useEffect(() => {
    composer.setPixelRatio(dpr);
    composer.setSize(size.width, size.height);
  }, [composer, dpr, size.width, size.height]);
  useEffect(() => () => composer.dispose(), [composer]);
  useFrame((_, delta) => composer.render(delta), 1);
  return null;
}

function RecordHook({ onReady }: { onReady: (advance: (seconds: number) => void) => void }) {
  const advance = useThree((s) => s.advance);
  useEffect(() => onReady((seconds) => advance(seconds)), [advance, onReady]);
  return null;
}

type SceneProps = { failureRate: number; still: boolean; signal: FlowSignal | null; selected: FlowNodeKey | null };
type Extra = {
  hovered: FlowNodeKey | null;
  onHover: (k: FlowNodeKey | null) => void;
  onSelect: (k: FlowNodeKey) => void;
  chips: RefObject<Partial<Record<FlowNodeKey, HTMLElement | null>>>;
  onRecordReady?: (advance: (seconds: number) => void) => void;
};

function Scene({ failureRate, still, signal, selected, hovered, onHover, onSelect, chips, onRecordReady }: SceneProps & Extra) {
  const flash = useRef<Flash>({});
  const controls = useRef<OrbitControlsImpl>(null);
  const settled = still || !!onRecordReady;
  return (
    <>
      <color attach="background" args={[STAGE_BG]} />
      <Environment resolution={256} frames={1}>
        <color attach="background" args={["#121317"]} />
        <Lightformer form="rect" intensity={2.3} position={[0, 7, 0.5]} rotation-x={Math.PI / 2} scale={[12, 6, 1]} />
        <Lightformer form="rect" intensity={2.6} position={[-7.5, 2.6, 3]} rotation-y={Math.PI / 2.3} scale={[8, 1.2, 1]} />
        <Lightformer form="rect" intensity={1.8} position={[7.5, 2.2, -2.5]} rotation-y={-Math.PI / 2.5} scale={[8, 1, 1]} />
        <Lightformer form="rect" intensity={1.3} position={[0, 1.8, 10]} scale={[16, 2, 1]} />
      </Environment>
      <AccumulativeShadows temporal={!settled} frames={settled ? 80 : 120} alphaTest={0.8} opacity={0.62} scale={40} position={[0, 0.002, 0]} color="#2a3140" colorBlend={1.1}>
        <RandomizedLight amount={8} radius={5} ambient={0.35} intensity={2.1} position={[6, 9.5, 7.5]} bias={0.0006} mapSize={2048} size={42} near={1} far={50} />
      </AccumulativeShadows>
      <OrbitControls
        ref={controls}
        makeDefault
        enablePan={false}
        enableZoom={false}
        enableDamping
        dampingFactor={0.07}
        rotateSpeed={0.55}
        minPolarAngle={0.62}
        maxPolarAngle={1.12}
        minAzimuthAngle={-0.75}
        maxAzimuthAngle={0.75}
      />
      <CameraRig still={settled} controls={controls} />
      <Rails />
      {KEYS.map((k) => (
        <Station key={k} k={k} hovered={hovered === k} selected={selected === k} flash={flash} still={still} onHover={onHover} onSelect={onSelect} />
      ))}
      <Beads failureRate={failureRate} still={still} signal={signal} flash={flash} />
      <ChipAnchors chips={chips} />
      <Post />
      {onRecordReady && <RecordHook onReady={onRecordReady} />}
    </>
  );
}

class GlBoundary extends Component<{ fallback: ReactNode; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

export default function FlowScene(
  props: SceneProps & {
    onHoverChange?: (k: FlowNodeKey | null) => void;
    onSelect: (k: FlowNodeKey) => void;
    /** Recording only: renders on demand and hands back a clock-driven advance(seconds). */
    onRecordReady?: (advance: (seconds: number) => void) => void;
  },
) {
  const [hovered, setHovered] = useState<FlowNodeKey | null>(null);
  const [dpr, setDpr] = useState<number | [number, number]>(props.onRecordReady ? 1 : [1, 2]);
  const chips = useRef<Partial<Record<FlowNodeKey, HTMLElement | null>>>({});
  const onHover = (k: FlowNodeKey | null) => {
    setHovered(k);
    props.onHoverChange?.(k);
  };
  const fallback = <div className="flex h-full items-center justify-center text-[14px] text-slate">The 3D view needs WebGL. Every figure is also in the dashboard below.</div>;
  return (
    <GlBoundary fallback={fallback}>
      <div className="relative h-full w-full" style={{ cursor: hovered ? "pointer" : "grab", background: STAGE_BG }}>
        <Canvas
          shadows
          dpr={dpr}
          frameloop={props.onRecordReady ? "never" : props.still ? "demand" : "always"}
          camera={{ fov: 30, near: 0.5, far: 90, position: [0, 10, 14] }}
          gl={{ antialias: false, alpha: false, preserveDrawingBuffer: !!props.onRecordReady, powerPreference: "high-performance" }}
          onCreated={({ gl }) => {
            gl.toneMapping = THREE.NeutralToneMapping;
            gl.toneMappingExposure = 1.06;
          }}
          onPointerMissed={() => onHover(null)}
        >
          {!props.onRecordReady && <PerformanceMonitor onDecline={() => setDpr(1)} />}
          <Scene {...props} hovered={hovered} onHover={onHover} chips={chips} />
        </Canvas>
        <div aria-hidden="true" className="pointer-events-none absolute inset-0 overflow-hidden">
          {KEYS.map((k) => {
            const on = props.selected === k;
            return (
              <button
                key={k}
                type="button"
                tabIndex={-1}
                ref={(el) => {
                  chips.current[k] = el;
                }}
                onPointerEnter={() => onHover(k)}
                onPointerLeave={() => onHover(null)}
                onClick={() => props.onSelect(k)}
                className={`pointer-events-auto absolute left-0 top-0 whitespace-nowrap rounded-full border px-2.5 py-[5px] text-[12px] leading-none shadow-[0_1px_2px_rgba(10,10,10,0.06)] transition-colors ${
                  on ? "border-ink bg-ink text-white" : hovered === k ? "border-ink/30 bg-white text-ink" : "border-edge bg-white/92 text-ink"
                }`}
                style={{ transform: "translate3d(-9999px, 0, 0)" }}
              >
                <span className="font-semibold">{FLOW_NODES[k].label}</span>
                {(on || hovered === k) && <span className={on ? "text-white/70" : "text-slate"}> {FLOW_NODES[k].sub}</span>}
              </button>
            );
          })}
        </div>
      </div>
    </GlBoundary>
  );
}
