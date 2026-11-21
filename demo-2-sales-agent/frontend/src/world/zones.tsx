import { useFrame, type ThreeEvent } from "@react-three/fiber";
import { useEffect, useLayoutEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import { QUADRANTS } from "../components/radarMeta";
import type { Account, LeadCard, Learning, Report } from "../lib/api";
import { AMBER, mats, paperTexture, rb } from "./studio";
import { ZONES, world, type Vec3 } from "./store";
import {
  DISH_R,
  GATE_POS,
  STATION_POS,
  TRAYS,
  accountPos,
  pinHeight,
  placeLead,
  ringRadius,
  SOCKETS,
  socketPos,
  stationU,
  trayPos,
  type TrayKey,
} from "./layout";
import type { StationKey } from "../components/flowMeta";

const TAU = Math.PI * 2;
const over = (fn: () => void) => (e: ThreeEvent<PointerEvent>) => {
  e.stopPropagation();
  document.body.style.cursor = "pointer";
  fn();
};
const out = (fn: () => void) => () => {
  document.body.style.cursor = "";
  fn();
};

// ================================================================== radar: every researched company
/** The sweep's angle, shared so a pin can light up the moment the beam passes it. */
const sweep = { angle: 0 };

function Ticks() {
  const ref = useRef<THREE.InstancedMesh>(null);
  useLayoutEffect(() => {
    const mesh = ref.current;
    if (!mesh) return;
    const m = new THREE.Object3D();
    for (let i = 0; i < 72; i++) {
      const a = (i / 72) * TAU;
      const long = i % 6 === 0;
      m.position.set(Math.cos(a) * (DISH_R + 0.16), 0.395, -Math.sin(a) * (DISH_R + 0.16));
      m.rotation.set(0, a, 0);
      m.scale.set(long ? 0.2 : 0.11, 1, 1);
      m.updateMatrix();
      mesh.setMatrixAt(i, m.matrix);
    }
    mesh.instanceMatrix.needsUpdate = true;
  }, []);
  return (
    <instancedMesh ref={ref} args={[undefined, undefined, 72]} material={mats.graphite}>
      <boxGeometry args={[1, 0.012, 0.022]} />
    </instancedMesh>
  );
}

function Dish() {
  const face = useMemo(() => new THREE.MeshPhysicalMaterial({ color: "#f3f4f6", roughness: 0.55, clearcoat: 0.2 }), []);
  const sector = useMemo(() => new THREE.MeshBasicMaterial({ color: "#e9ecf1", transparent: true, opacity: 1 }), []);
  return (
    <group>
      <mesh material={mats.ceramic} position-y={0.18} castShadow receiveShadow>
        <cylinderGeometry args={[DISH_R + 0.42, DISH_R + 0.5, 0.36, 128]} />
      </mesh>
      <mesh material={mats.metal} position-y={0.365} rotation-x={Math.PI / 2}>
        <torusGeometry args={[DISH_R + 0.42, 0.035, 16, 160]} />
      </mesh>
      <mesh material={face} position-y={0.372} receiveShadow>
        <cylinderGeometry args={[DISH_R, DISH_R, 0.02, 128]} />
      </mesh>
      {/* alternate quadrants are a shade darker so the four signal types read at a glance */}
      {[1, 3].map((q) => (
        <mesh key={q} material={sector} rotation-x={-Math.PI / 2} position-y={0.384}>
          <circleGeometry args={[DISH_R, 48, (q * Math.PI) / 2, Math.PI / 2]} />
        </mesh>
      ))}
      {[85, 75, 65, 55, 45].map((s) => (
        <mesh key={s} material={mats.grey} rotation-x={Math.PI / 2} position-y={0.388}>
          <torusGeometry args={[ringRadius(s), s === 75 ? 0.016 : 0.009, 8, 160]} />
        </mesh>
      ))}
      {[0, Math.PI / 2].map((a) => (
        <mesh key={a} material={mats.grey} position-y={0.389} rotation-y={a}>
          <boxGeometry args={[DISH_R * 2, 0.006, 0.018]} />
        </mesh>
      ))}
      <Ticks />
      <mesh material={mats.white} position-y={0.47} castShadow>
        <cylinderGeometry args={[0.36, 0.42, 0.18, 48]} />
      </mesh>
      <mesh material={mats.glass} position-y={0.6}>
        <sphereGeometry args={[0.3, 48, 24, 0, TAU, 0, Math.PI / 2]} />
      </mesh>
    </group>
  );
}

function SweepBeam({ scanning, still }: { scanning: boolean; still: boolean }) {
  const group = useRef<THREE.Group>(null);
  const wedge = useMemo(() => new THREE.MeshBasicMaterial({ color: AMBER, transparent: true, opacity: 0.13, depthWrite: false, blending: THREE.AdditiveBlending, side: THREE.DoubleSide }), []);
  useFrame((_, delta) => {
    if (still) return;
    sweep.angle = (sweep.angle + delta * (scanning ? 1.7 : 0.45)) % TAU;
    if (group.current) group.current.rotation.y = sweep.angle;
    wedge.opacity = scanning ? 0.22 : 0.12;
  });
  return (
    <group ref={group} position-y={0.392}>
      <mesh material={wedge} rotation-x={-Math.PI / 2}>
        <circleGeometry args={[DISH_R, 40, -0.55, 0.55]} />
      </mesh>
      <mesh material={mats.ledAmber} position={[DISH_R / 2, 0.006, 0]}>
        <boxGeometry args={[DISH_R, 0.008, 0.02]} />
      </mesh>
    </group>
  );
}

function Pin({ lead, index, still }: { lead: LeadCard; index: number; still: boolean }) {
  const { x, z, theta } = placeLead(lead);
  const h = pinHeight(lead.score);
  const hot = lead.status !== "excluded" && lead.score >= 75;
  const head = useRef<THREE.Mesh>(null);
  const lift = useRef<THREE.Group>(null);
  const glow = useMemo(
    () =>
      new THREE.MeshPhysicalMaterial({
        color: lead.status === "excluded" ? "#aeb3bb" : hot ? AMBER : "#ffffff",
        roughness: 0.28,
        clearcoat: 0.9,
        emissive: new THREE.Color(hot ? "#ffb340" : "#ffffff"),
        emissiveIntensity: 0,
      }),
    [hot, lead.status],
  );
  const grow = useRef(0);
  useEffect(() => () => glow.dispose(), [glow]);
  useFrame((_, delta) => {
    const s = world.get();
    const on = s.hoverLead === lead.id || s.lead === lead.id;
    grow.current = Math.min(1, grow.current + delta * (still ? 99 : 1.6) * (index < 40 ? 1 : 0.5));
    const passed = ((sweep.angle - (theta < 0 ? theta + TAU : theta)) % TAU + TAU) % TAU;
    const ping = still ? 0 : Math.exp(-passed * 5);
    glow.emissiveIntensity = (hot ? 0.25 : 0) + ping * (hot ? 2.4 : 0.6) + (on ? 0.9 : 0);
    if (lift.current) {
      const target = on ? 0.18 : 0;
      lift.current.position.y += (target - lift.current.position.y) * Math.min(1, delta * 9);
      lift.current.scale.y = THREE.MathUtils.lerp(0.001, 1, 1 - Math.pow(1 - grow.current, 3));
    }
    if (head.current) head.current.scale.setScalar(on ? 1.25 : 1);
  });
  return (
    <group position={[x, 0.39, z]}>
      <mesh material={mats.grey} rotation-x={-Math.PI / 2} position-y={0.002}>
        <ringGeometry args={[0.07, 0.11, 32]} />
      </mesh>
      <group ref={lift}>
        <mesh material={mats.metal} position-y={h / 2} castShadow>
          <cylinderGeometry args={[0.022, 0.026, h, 12]} />
        </mesh>
        <mesh
          ref={head}
          material={glow}
          position-y={h + 0.1}
          castShadow
          onPointerOver={over(() => world.set({ hoverLead: lead.id }))}
          onPointerOut={out(() => world.set({ hoverLead: null }))}
          onClick={(e) => {
            e.stopPropagation();
            world.set({ lead: lead.id });
          }}
        >
          <sphereGeometry args={[hot ? 0.16 : 0.12, 32, 16]} />
        </mesh>
      </group>
    </group>
  );
}

export function RadarZone({ leads, scanning, still }: { leads: LeadCard[] | null; scanning: boolean; still: boolean }) {
  return (
    <group position={ZONES.radar}>
      <Dish />
      <SweepBeam scanning={scanning} still={still} />
      {(leads ?? []).map((l, i) => (
        <Pin key={l.id} lead={l} index={i} still={still} />
      ))}
    </group>
  );
}
export const quadrantLabelPos = (i: number): Vec3 => {
  const a = QUADRANTS[i].start + Math.PI / 4;
  return [Math.cos(a) * (DISH_R + 0.9), 0.5, -Math.sin(a) * (DISH_R + 0.9)];
};

// ================================================================== agent: the run as stations on a track
export type StationState = "idle" | "done" | "active" | "refused";

function Glyph({ k, accent }: { k: StationKey; accent: THREE.Material }) {
  const w = mats.white;
  const g = mats.graphite;
  switch (k) {
    case "learn":
      return (
        <group>
          {[0, 1, 2].map((i) => (
            <mesh key={i} geometry={rb(0.44, 0.035, 0.56, 0.015)} material={w} position={[i * 0.03 - 0.03, -0.1 + i * 0.07, -i * 0.03]} rotation-y={i * 0.08} />
          ))}
          <mesh geometry={rb(0.08, 0.04, 0.3, 0.01)} material={accent} position={[0.14, 0.06, 0.1]} />
        </group>
      );
    case "research":
      return (
        <group>
          {[0, Math.PI / 3, (2 * Math.PI) / 3].map((a) => (
            <mesh key={a} material={g} rotation={[Math.PI / 2, 0, a]}>
              <torusGeometry args={[0.27, 0.012, 8, 64]} />
            </mesh>
          ))}
          <mesh material={g} rotation-x={Math.PI / 2}>
            <torusGeometry args={[0.27, 0.012, 8, 64]} />
          </mesh>
          <mesh material={accent} position={[0.19, 0.17, 0.08]}>
            <sphereGeometry args={[0.055, 24, 12]} />
          </mesh>
        </group>
      );
    case "score":
      return (
        <group position-y={-0.16}>
          {[0.16, 0.26, 0.38].map((h, i) => (
            <mesh key={i} geometry={rb(0.12, h, 0.12, 0.03)} material={i === 2 ? accent : g} position={[(i - 1) * 0.17, h / 2, 0]} />
          ))}
        </group>
      );
    case "crm":
      return (
        <group position-y={-0.12}>
          {[0, 1, 2].map((i) => (
            <mesh key={i} material={i === 2 ? accent : w} position-y={i * 0.11}>
              <cylinderGeometry args={[0.2, 0.2, 0.085, 40]} />
            </mesh>
          ))}
        </group>
      );
    case "draft":
      return (
        <group rotation-x={-0.35}>
          <mesh geometry={rb(0.56, 0.38, 0.05, 0.03)} material={w} />
          <mesh material={accent} position={[0, 0.06, 0.03]} rotation-z={Math.PI}>
            <coneGeometry args={[0.28, 0.2, 3, 1]} />
          </mesh>
        </group>
      );
    case "followup":
      return (
        <group rotation-x={-0.3}>
          <mesh geometry={rb(0.5, 0.46, 0.06, 0.04)} material={w} />
          <mesh geometry={rb(0.5, 0.11, 0.07, 0.03)} material={accent} position-y={0.17} />
          {[-0.12, 0.12].map((x) => (
            <mesh key={x} material={mats.metal} position={[x, 0.25, 0]}>
              <cylinderGeometry args={[0.022, 0.022, 0.13, 12]} />
            </mesh>
          ))}
          <mesh geometry={rb(0.1, 0.08, 0.07, 0.02)} material={g} position={[0.1, -0.06, 0.01]} />
        </group>
      );
    case "report":
    default:
      return (
        <group rotation-x={-0.3}>
          <mesh geometry={rb(0.44, 0.56, 0.04, 0.02)} material={w} />
          {[0.1, 0.18, 0.26].map((h, i) => (
            <mesh key={i} geometry={rb(0.07, h, 0.05, 0.012)} material={i === 2 ? accent : g} position={[(i - 1) * 0.11, -0.16 + h / 2, 0.02]} />
          ))}
        </group>
      );
  }
}

function Station({ k, state, still }: { k: StationKey; state: StationState; still: boolean }) {
  const [x, z] = STATION_POS[k];
  const icon = useRef<THREE.Group>(null);
  const accent = useMemo(() => new THREE.MeshPhysicalMaterial({ color: AMBER, roughness: 0.3, clearcoat: 0.9, emissive: new THREE.Color("#ffb340"), emissiveIntensity: 0 }), []);
  const led = state === "done" ? mats.ledTeal : state === "refused" ? mats.ledRed : state === "active" ? mats.ledAmber : mats.ledOff;
  const phase = x * 0.7;
  useFrame((st) => {
    const t = st.clock.elapsedTime;
    accent.emissiveIntensity = state === "active" ? 0.7 + 0.6 * Math.sin(t * 6) : state === "done" ? 0.15 : 0;
    if (icon.current && !still) {
      icon.current.rotation.y = 0.28 * Math.sin(t * 0.55 + phase) + (state === "active" ? t * 0.8 : 0);
      icon.current.position.y = 0.84 + 0.025 * Math.sin(t * 0.8 + phase);
    }
  });
  return (
    <group position={[x, 0, z]}>
      <mesh geometry={rb(1.5, 0.24, 1.5, 0.09)} material={mats.ceramic} position-y={0.12} castShadow receiveShadow />
      <mesh material={led} position={[0.52, 0.12, 0.752]} scale={0.032}>
        <sphereGeometry args={[1, 16, 8]} />
      </mesh>
      <mesh geometry={rb(1.12, 0.84, 1.12, 0.14)} material={mats.glass} position-y={0.66} castShadow />
      <group ref={icon} position-y={0.84}>
        <Glyph k={k} accent={accent} />
      </group>
    </group>
  );
}

function Track({ progress, running, still }: { progress: number; running: boolean; still: boolean }) {
  const curve = useMemo(() => new THREE.CatmullRomCurve3(Object.values(STATION_POS).map(([x, z]) => new THREE.Vector3(x, 0.07, z)), false, "centripetal"), []);
  const tube = useMemo(() => new THREE.TubeGeometry(curve, 240, 0.045, 10, false), [curve]);
  const bead = useRef<THREE.Mesh>(null);
  const u = useRef(0);
  useFrame((st, delta) => {
    if (!bead.current) return;
    const target = progress;
    u.current += (target - u.current) * Math.min(1, delta * (still ? 99 : 2.2));
    const wobble = running && !still ? 0.006 * Math.sin(st.clock.elapsedTime * 7) : 0;
    const p = curve.getPointAt(THREE.MathUtils.clamp(u.current + wobble, 0, 1));
    bead.current.position.set(p.x, 0.17, p.z);
    bead.current.visible = progress > 0;
  });
  return (
    <group>
      <mesh geometry={tube} material={mats.metal} castShadow receiveShadow />
      <mesh ref={bead} material={mats.ledAmber} castShadow>
        <sphereGeometry args={[0.1, 24, 12]} />
      </mesh>
    </group>
  );
}

function Gate({ pending }: { pending: number }) {
  const [x, z] = GATE_POS;
  const light = pending > 0 ? mats.ledAmber : mats.ledTeal;
  return (
    <group position={[x, 0, z]}>
      <mesh geometry={rb(1.7, 0.16, 0.9, 0.06)} material={mats.ceramic} position-y={0.08} castShadow receiveShadow />
      {[-0.66, 0.66].map((dx) => (
        <mesh key={dx} geometry={rb(0.16, 1.25, 0.16, 0.05)} material={mats.white} position={[dx, 0.78, 0]} castShadow />
      ))}
      <mesh geometry={rb(1.5, 0.16, 0.2, 0.06)} material={mats.white} position-y={1.45} castShadow />
      <mesh material={light} position={[0, 1.45, 0.11]} scale={0.05}>
        <sphereGeometry args={[1, 16, 8]} />
      </mesh>
    </group>
  );
}

export function AgentZone({ states, progress, running, pending, still }: { states: Record<StationKey, StationState>; progress: number; running: boolean; pending: number; still: boolean }) {
  return (
    <group position={ZONES.agent}>
      <mesh geometry={rb(17.2, 0.06, 6.4, 0.03)} material={mats.white} position-y={0.03} receiveShadow />
      <Track progress={progress} running={running} still={still} />
      {(Object.keys(STATION_POS) as StationKey[]).map((k) => (
        <Station key={k} k={k} state={states[k]} still={still} />
      ))}
      <Gate pending={pending} />
    </group>
  );
}
export { stationU };

// ================================================================== approval queue: four trays
function Tray({ k, count, still }: { k: TrayKey; count: number; still: boolean }) {
  const [x, z] = trayPos(k);
  const lift = useRef<THREE.Group>(null);
  const seal = k === "pending" ? mats.amber : k === "approved" ? mats.teal : k === "rejected" ? mats.red : mats.grey;
  const shown = Math.min(count, 14);
  useFrame((_, delta) => {
    if (!lift.current) return;
    const on = world.get().tray === k;
    lift.current.position.y += ((on ? 0.22 : 0) - lift.current.position.y) * Math.min(1, delta * (still ? 99 : 6));
  });
  return (
    <group position={[x, 0, z]}>
      <group ref={lift}>
        <mesh geometry={rb(2.3, 0.14, 1.8, 0.07)} material={mats.ceramic} position-y={0.07} castShadow receiveShadow />
        {[
          [0, 0.2, 0.86, 2.3, 0.12, 0.08],
          [0, 0.2, -0.86, 2.3, 0.12, 0.08],
          [1.11, 0.2, 0, 0.08, 0.12, 1.8],
          [-1.11, 0.2, 0, 0.08, 0.12, 1.8],
        ].map(([px, py, pz, w, h, d], i) => (
          <mesh key={i} geometry={rb(w, h, d, 0.035)} material={mats.white} position={[px, py, pz]} castShadow />
        ))}
        {Array.from({ length: shown }, (_, i) => (
          <group key={i} position={[((i * 37) % 7) * 0.012 - 0.036, 0.17 + i * 0.062, ((i * 53) % 5) * 0.012 - 0.024]} rotation-y={(((i * 29) % 9) - 4) * 0.02}>
            <mesh geometry={rb(1.6, 0.05, 1.08, 0.02)} material={mats.white} castShadow />
            <mesh material={seal} position={[0, 0.028, 0.1]} rotation-x={-Math.PI / 2}>
              <circleGeometry args={[0.09, 24]} />
            </mesh>
          </group>
        ))}
      </group>
    </group>
  );
}

export function QueueZone({ counts, still }: { counts: Record<TrayKey, number>; still: boolean }) {
  return (
    <group position={ZONES.queue}>
      {TRAYS.map((k) => (
        <Tray key={k} k={k} count={counts[k]} still={still} />
      ))}
    </group>
  );
}

// ================================================================== CRM: every account as a pillar
const FLAG_COLOR: Record<string, THREE.Material> = { stalled: mats.ledRed, no_contact: mats.ledAmber, upsell: mats.ledTeal };

function Pillar({ acc, i, maxValue, dim, still }: { acc: Account; i: number; maxValue: number; dim: boolean; still: boolean }) {
  const [x, z] = accountPos(i);
  const value = acc.deal_value ?? acc.arr ?? 0;
  const h = 0.22 + (maxValue ? Math.sqrt(value / maxValue) : 0) * 2.3;
  const flag = (acc.flags ?? [])[0];
  const group = useRef<THREE.Group>(null);
  const grow = useRef(0);
  const body = dim ? mats.grey : mats.white;
  useFrame((_, delta) => {
    if (!group.current) return;
    grow.current = Math.min(1, grow.current + delta * (still ? 99 : 1.3));
    const s = world.get();
    const on = s.hoverAccount === acc.id || s.account === acc.id;
    group.current.scale.y = THREE.MathUtils.lerp(0.001, 1, 1 - Math.pow(1 - grow.current, 3)) * (dim ? 0.35 : 1);
    group.current.position.y += ((on ? 0.2 : 0) - group.current.position.y) * Math.min(1, delta * 9);
  });
  return (
    <group position={[x, 0, z]}>
      <mesh material={mats.grey} rotation-x={-Math.PI / 2} position-y={0.003}>
        <ringGeometry args={[0.33, 0.37, 40]} />
      </mesh>
      <group
        ref={group}
        onPointerOver={over(() => world.set({ hoverAccount: acc.id }))}
        onPointerOut={out(() => world.set({ hoverAccount: null }))}
        onClick={(e) => {
          e.stopPropagation();
          world.set({ account: acc.id });
        }}
      >
        <mesh material={body} position-y={h / 2} castShadow receiveShadow>
          <cylinderGeometry args={[0.28, 0.31, h, 40]} />
        </mesh>
        {flag && (
          <mesh material={FLAG_COLOR[flag] ?? mats.ledOff} position-y={h + 0.012} rotation-x={Math.PI / 2}>
            <torusGeometry args={[0.2, 0.03, 10, 48]} />
          </mesh>
        )}
        {acc.stage === "Customer" && (
          <mesh material={mats.graphite} position-y={h + 0.02}>
            <cylinderGeometry args={[0.1, 0.1, 0.04, 24]} />
          </mesh>
        )}
      </group>
    </group>
  );
}

export function CrmZone({ accounts, flag, still }: { accounts: Account[] | null; flag: string | null; still: boolean }) {
  const list = accounts ?? [];
  const maxValue = Math.max(1, ...list.map((a) => a.deal_value ?? a.arr ?? 0));
  return (
    <group position={ZONES.crm}>
      <mesh geometry={rb(11.8, 0.08, 7.4, 0.04)} material={mats.white} position-y={0.04} receiveShadow />
      {list.slice(0, 60).map((a, i) => (
        <Pillar key={a.id} acc={a} i={i} maxValue={maxValue} dim={Boolean(flag) && !(a.flags ?? []).includes(flag!)} still={still} />
      ))}
    </group>
  );
}

// ================================================================== paper: learning and the weekly report
function Easel({ x, tex, w = 2.3, h = 2.98, tilt = -0.16 }: { x: number; tex: THREE.Texture | null; w?: number; h?: number; tilt?: number }) {
  const paper = useMemo(() => new THREE.MeshStandardMaterial({ color: "#ffffff", roughness: 0.82 }), []);
  useEffect(() => {
    paper.map = tex;
    paper.needsUpdate = true;
  }, [paper, tex]);
  return (
    <group position={[x, 0, 0]}>
      <mesh geometry={rb(w + 0.5, 0.14, 1.2, 0.06)} material={mats.ceramic} position-y={0.07} castShadow receiveShadow />
      <group position={[0, 0.2 + h / 2 + 0.05, 0]} rotation-x={tilt}>
        <mesh geometry={rb(w + 0.12, h + 0.12, 0.06, 0.03)} material={mats.white} position-z={-0.035} castShadow />
        <mesh material={paper} position-z={0.0}>
          <planeGeometry args={[w, h]} />
        </mesh>
      </group>
      {[-1, 1].map((s) => (
        <mesh key={s} material={mats.metal} position={[s * (w / 2 - 0.2), 0.62, -0.36]} rotation-x={0.28}>
          <cylinderGeometry args={[0.025, 0.025, 1.2, 10]} />
        </mesh>
      ))}
    </group>
  );
}

function draftLines(title: string, d: { subject: string; body: string; words: number } | null, tone: string) {
  if (!d) return [{ text: title, size: 54, weight: 650 }, { text: "Approve, edit or reject a few drafts and the next run shows what changed.", size: 34, color: "#5b616b" }];
  return [
    { text: title, size: 40, weight: 650, color: tone, gap: 18 },
    { text: d.subject, size: 46, weight: 650, gap: 22 },
    ...d.body
      .split(/\n+/)
      .filter(Boolean)
      .slice(0, 8)
      .map((p) => ({ text: p, size: 31, color: "#30343b", gap: 14 })),
    { text: `${d.words} words`, size: 28, color: "#8a9099" },
  ];
}

export function LearningZone({ learning }: { learning: Learning | null }) {
  const pair = learning?.pairs?.[0] ?? null;
  const before = useMemo(() => paperTexture(draftLines("Before", pair?.before ?? null, "#9a6b00")), [pair]);
  const after = useMemo(() => paperTexture(draftLines("After", pair?.after ?? null, "#0b7d6b")), [pair]);
  useEffect(() => () => void (before.dispose(), after.dispose()), [before, after]);
  return (
    <group position={ZONES.learning}>
      <Easel x={-1.55} tex={before} />
      <Easel x={1.55} tex={after} />
      <mesh material={mats.ledAmber} position={[0, 1.7, 0.1]} rotation-z={-Math.PI / 2}>
        <coneGeometry args={[0.12, 0.26, 24]} />
      </mesh>
    </group>
  );
}

export function ReportZone({ report }: { report: Report | null }) {
  const tex = useMemo(() => {
    if (!report) return paperTexture([{ text: "Weekly report", size: 60, weight: 650 }, { text: "Run the agent to fill it.", size: 34, color: "#5b616b" }]);
    const n = (v: number) => v.toLocaleString("en-US");
    return paperTexture([
      { text: "Weekly report", size: 64, weight: 680, gap: 10 },
      { text: report.period.label, size: 30, color: "#6b7079", gap: 30 },
      ...report.headline.slice(0, 4).map((h) => ({ text: h, size: 33, color: "#24272d", gap: 16 })),
      { text: `New leads: ${n(report.leads.new_this_week)}   Waiting for approval: ${n(report.pending_drafts.length)}`, size: 31, weight: 600, gap: 20 },
      ...report.leads.top.slice(0, 4).map((l) => ({ text: `${l.score}  ${l.company}`, size: 32, color: "#30343b", gap: 8 })),
    ]);
  }, [report]);
  useEffect(() => () => tex.dispose(), [tex]);
  return (
    <group position={ZONES.report}>
      <Easel x={0} tex={tex} w={2.6} h={3.37} />
    </group>
  );
}

// ================================================================== settings: one socket per connection
export function SettingsZone({ live }: { live: Record<string, boolean> }) {
  return (
    <group>
      <mesh geometry={rb(8.4, 0.3, 4, 0.12)} material={mats.ceramic} position={[ZONES.settings[0], 0.15, ZONES.settings[2]]} castShadow receiveShadow />
      {SOCKETS.map((k, i) => {
        const [x, y, z] = socketPos(i);
        const on = !!live[k];
        return (
          <group key={k} position={[x, y, z]}>
            <mesh material={mats.white} castShadow>
              <cylinderGeometry args={[0.46, 0.48, 0.18, 64]} />
            </mesh>
            <mesh rotation-x={Math.PI / 2} position-y={0.092} material={on ? mats.ledTeal : mats.ledAmber}>
              <torusGeometry args={[0.37, 0.018, 12, 96]} />
            </mesh>
            <mesh position-y={0.1} material={mats.graphite}>
              <cylinderGeometry args={[0.24, 0.24, 0.04, 48]} />
            </mesh>
          </group>
        );
      })}
    </group>
  );
}
