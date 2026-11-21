import { ContactShadows, Line, RoundedBox } from "@react-three/drei";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import clsx from "clsx";
import { Lock, RotateCcw } from "lucide-react";
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode, type RefObject } from "react";
import { useNavigate } from "react-router-dom";
import * as THREE from "three";
import type { Overview, Run } from "../lib/api";
import { TOOL_LABEL } from "../lib/format";
import { usePrefersReducedMotion } from "../lib/hooks";
import { flowSteps, GATE, gateNote, STATIONS, stationIndexOf, stationNotes, type FlowStep } from "./flowMeta";

/**
 * The agent's run as a small 3D desk: seven stations on a track, the agent travelling between them
 * step by step, and an approval gate where every email waits for a person. A finished run is
 * replayed from its stored tool log; a live run is followed as it happens.
 */
const STEP_MS = 90;
const TAU = Math.PI * 2;
const C = {
  white: "#ffffff",
  rule: "#d3dbd6",
  track: "#cfdad4",
  spruce: "#0f3b35",
  spruce3: "#1f5c53",
  sage: "#8fb8a8",
  sageSoft: "#e3eee9",
  amber: "#e9a23b",
  crimson: "#c4314b",
  cobalt: "#2f56b0",
  ink3: "#6b807b",
};

type PadState = "idle" | "done" | "active" | "refused";

// ------------------------------------------------------------------ track geometry
const TRACK_OFFSET = 0.95;
const CURVE = new THREE.CatmullRomCurve3(
  STATIONS.map((s) => new THREE.Vector3(s.pos[0], 0.09, s.pos[1] + TRACK_OFFSET)),
  false,
  "catmullrom",
  0.5,
);
const TUBE_SEGMENTS = 260;
const TUBE_RADIAL = 10;

/** Arc-length position (0..1) of each station on the curve, so the orb and the lit track agree. */
const STATION_U = (() => {
  const samples = 2000;
  const p = new THREE.Vector3();
  return STATIONS.map((s) => {
    let best = 0;
    let bestD = Infinity;
    for (let i = 0; i <= samples; i++) {
      CURVE.getPointAt(i / samples, p);
      const d = (p.x - s.pos[0]) ** 2 + (p.z - s.pos[1] - TRACK_OFFSET) ** 2;
      if (d < bestD) {
        bestD = d;
        best = i / samples;
      }
    }
    return best;
  });
})();

const ANCHORS: Anchor[] = [
  ...STATIONS.map((st) => ({ key: st.key as string, pos: [st.pos[0], 1.38, st.pos[1]] as [number, number, number] })),
  { key: "gate", pos: [GATE.pos[0] + 1.55, 0.42, GATE.pos[1] + 0.75] },
];

// ------------------------------------------------------------------ replay
function useReplay(total: number, running: boolean, runId: string | undefined, still: boolean) {
  const [cursor, setCursor] = useState(Number.MAX_SAFE_INTEGER);
  const [token, setToken] = useState(0);
  const [replaying, setReplaying] = useState(false);
  const totalRef = useRef(total);
  totalRef.current = total;
  const wasRunning = useRef(running);

  useEffect(() => {
    const justFinished = wasRunning.current && !running;
    wasRunning.current = running;
    if (running || still || justFinished || !runId || totalRef.current === 0) {
      setCursor(Number.MAX_SAFE_INTEGER);
      setReplaying(false);
      return;
    }
    setCursor(0);
    setReplaying(true);
    let i = 0;
    const id = window.setInterval(() => {
      i += 1;
      setCursor(i);
      if (i >= totalRef.current) {
        window.clearInterval(id);
        setReplaying(false);
      }
    }, STEP_MS);
    return () => window.clearInterval(id);
  }, [runId, token, running, still]);

  return { cursor: Math.min(cursor, total), replaying, replay: () => setToken((t) => t + 1) };
}

function useWidth(ref: RefObject<HTMLDivElement | null>) {
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    setWidth(el.getBoundingClientRect().width);
    const ro = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    ro.observe(el);
    return () => ro.disconnect();
  }, [ref]);
  return width;
}

// ------------------------------------------------------------------ station models
const mat = (color: string, roughness = 0.6, metalness = 0) => <meshStandardMaterial color={color} roughness={roughness} metalness={metalness} />;

function NotesModel({ active }: { active: boolean }) {
  const top = useRef<THREE.Group>(null);
  useFrame(({ clock }) => {
    if (top.current) top.current.rotation.y = active ? Math.sin(clock.elapsedTime * 5) * 0.12 + 0.2 : 0.2;
  });
  const colors = [C.sage, C.sageSoft, C.white];
  return (
    <group>
      {colors.map((c, i) => (
        <group key={c} ref={i === 2 ? top : undefined} position={[0, 0.06 + i * 0.11, 0]} rotation={[0, i === 2 ? 0.2 : (i - 1) * 0.16, 0]}>
          <RoundedBox args={[0.82, 0.09, 0.6]} radius={0.03} smoothness={3}>
            {mat(c, 0.75)}
          </RoundedBox>
          {i === 2 &&
            [0.16, 0.04, -0.08].map((z, k) => (
              <mesh key={z} position={[-0.06 + (k === 2 ? -0.08 : 0), 0.047, z]}>
                <boxGeometry args={[k === 2 ? 0.4 : 0.56, 0.004, 0.035]} />
                {mat(C.ink3)}
              </mesh>
            ))}
        </group>
      ))}
      <mesh position={[0.26, 0.2, 0.3]}>
        <boxGeometry args={[0.07, 0.24, 0.012]} />
        {mat(C.amber, 0.5)}
      </mesh>
    </group>
  );
}

function globeLines(r: number) {
  const pts: number[] = [];
  const seg = 56;
  for (const lat of [-55, -25, 0, 25, 55]) {
    const y = r * Math.sin((lat * Math.PI) / 180);
    const rr = r * Math.cos((lat * Math.PI) / 180);
    for (let i = 0; i < seg; i++) {
      const a0 = (i / seg) * TAU;
      const a1 = ((i + 1) / seg) * TAU;
      pts.push(rr * Math.cos(a0), y, rr * Math.sin(a0), rr * Math.cos(a1), y, rr * Math.sin(a1));
    }
  }
  for (let m = 0; m < 6; m++) {
    const lon = (m / 6) * Math.PI;
    for (let i = 0; i < seg; i++) {
      const t0 = (i / seg) * TAU;
      const t1 = ((i + 1) / seg) * TAU;
      pts.push(
        r * Math.cos(t0) * Math.cos(lon), r * Math.sin(t0), r * Math.cos(t0) * Math.sin(lon),
        r * Math.cos(t1) * Math.cos(lon), r * Math.sin(t1), r * Math.cos(t1) * Math.sin(lon),
      );
    }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
  return g;
}

function GlobeModel({ active, still }: { active: boolean; still: boolean }) {
  const spin = useRef<THREE.Group>(null);
  const lines = useMemo(() => globeLines(0.405), []);
  useFrame((_, delta) => {
    if (spin.current && !still) spin.current.rotation.y += delta * (active ? 2.4 : 0.35);
  });
  return (
    <group>
      <mesh position={[0, 0.05, 0]}>
        <cylinderGeometry args={[0.2, 0.27, 0.1, 32]} />
        {mat(C.spruce3, 0.45, 0.2)}
      </mesh>
      <mesh position={[0, 0.2, 0]}>
        <cylinderGeometry args={[0.025, 0.025, 0.22, 8]} />
        {mat(C.spruce3, 0.45, 0.2)}
      </mesh>
      <group position={[0, 0.66, 0]} rotation={[0, 0, 0.38]}>
        <mesh rotation={[Math.PI / 2, 0, 0]}>
          <torusGeometry args={[0.47, 0.016, 8, 72]} />
          {mat(C.spruce3, 0.4, 0.3)}
        </mesh>
        <group ref={spin}>
          <mesh>
            <sphereGeometry args={[0.4, 40, 28]} />
            {mat(C.sageSoft, 0.7)}
          </mesh>
          <lineSegments geometry={lines}>
            <lineBasicMaterial color={C.sage} />
          </lineSegments>
          {[
            [0.25, 0.22, 0.24],
            [-0.3, 0.05, 0.27],
            [0.05, -0.2, -0.35],
          ].map((p) => (
            <mesh key={p.join()} position={p as [number, number, number]}>
              <sphereGeometry args={[0.04, 12, 12]} />
              <meshBasicMaterial color={C.amber} toneMapped={false} />
            </mesh>
          ))}
        </group>
      </group>
    </group>
  );
}

function BarsModel({ active }: { active: boolean }) {
  const bars = useRef<(THREE.Mesh | null)[]>([]);
  const spec: [string, number][] = [
    [C.spruce, 0.78],
    [C.amber, 0.52],
    [C.sage, 0.36],
  ];
  useFrame(({ clock }) => {
    spec.forEach(([, h], i) => {
      const m = bars.current[i];
      if (!m) return;
      const k = active ? 0.75 + 0.25 * Math.abs(Math.sin(clock.elapsedTime * 4 + i)) : 1;
      m.scale.y = k;
      m.position.y = 0.07 + (h * k) / 2;
    });
  });
  return (
    <group>
      <RoundedBox args={[0.92, 0.07, 0.44]} radius={0.025} smoothness={3} position={[0, 0.035, 0]}>
        {mat(C.white, 0.8)}
      </RoundedBox>
      {spec.map(([color, h], i) => (
        <mesh key={color} ref={(m) => void (bars.current[i] = m)} position={[-0.27 + i * 0.27, 0.07 + h / 2, 0]}>
          <boxGeometry args={[0.2, h, 0.22]} />
          {mat(color, 0.5)}
        </mesh>
      ))}
    </group>
  );
}

function DatabaseModel({ active }: { active: boolean }) {
  const lights = useRef<(THREE.MeshBasicMaterial | null)[]>([]);
  useFrame(({ clock }) => {
    lights.current.forEach((m, i) => {
      if (!m) return;
      const on = active ? Math.sin(clock.elapsedTime * 9 + i * 2.1) > 0 : i === 1;
      m.color.set(on ? C.amber : C.sage);
    });
  });
  return (
    <group>
      {[0, 1, 2].map((i) => (
        <group key={i} position={[0, 0.11 + i * 0.22, 0]}>
          <mesh>
            <cylinderGeometry args={[0.38, 0.38, 0.18, 44]} />
            {mat(i === 2 ? C.spruce3 : C.spruce, 0.45, 0.15)}
          </mesh>
          <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.091, 0]}>
            <ringGeometry args={[0.31, 0.37, 44]} />
            <meshBasicMaterial color={C.sage} />
          </mesh>
          <mesh position={[0.24, 0, 0.3]}>
            <sphereGeometry args={[0.032, 12, 12]} />
            <meshBasicMaterial ref={(m) => void (lights.current[i] = m)} color={C.sage} toneMapped={false} />
          </mesh>
        </group>
      ))}
    </group>
  );
}

function EnvelopeModel({ active, still }: { active: boolean; still: boolean }) {
  const ref = useRef<THREE.Group>(null);
  const flap = useMemo(() => {
    const s = new THREE.Shape();
    s.moveTo(-0.4, 0.27);
    s.lineTo(0.4, 0.27);
    s.lineTo(0, -0.05);
    s.closePath();
    return new THREE.ShapeGeometry(s);
  }, []);
  useFrame(({ clock }) => {
    if (!ref.current) return;
    const t = clock.elapsedTime;
    ref.current.position.y = 0.5 + (still ? 0 : Math.sin(t * (active ? 5 : 1.6)) * (active ? 0.07 : 0.035));
    ref.current.rotation.z = still ? 0 : Math.sin(t * 1.3) * 0.06;
  });
  return (
    <group>
      <mesh position={[0, 0.02, 0]}>
        <cylinderGeometry args={[0.16, 0.22, 0.04, 24]} />
        {mat(C.sageSoft, 0.8)}
      </mesh>
      <group ref={ref} rotation={[0.95, 0, 0]}>
        <RoundedBox args={[0.82, 0.05, 0.54]} radius={0.02} smoothness={3}>
          {mat(C.white, 0.7)}
        </RoundedBox>
        <mesh geometry={flap} rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.027, 0]}>
          <meshStandardMaterial color="#eef3f0" roughness={0.7} side={THREE.DoubleSide} />
        </mesh>
        <mesh position={[0, 0.034, 0.05]} rotation={[0, 0, 0]}>
          <cylinderGeometry args={[0.07, 0.07, 0.02, 24]} />
          <meshStandardMaterial color={C.amber} roughness={0.4} emissive={C.amber} emissiveIntensity={active ? 0.6 : 0.15} />
        </mesh>
      </group>
    </group>
  );
}

function CalendarModel({ active }: { active: boolean }) {
  const hot = useRef<THREE.MeshStandardMaterial>(null);
  useFrame(({ clock }) => {
    if (hot.current) hot.current.emissiveIntensity = active ? 0.4 + 0.4 * Math.sin(clock.elapsedTime * 8) : 0.15;
  });
  const cells: [number, number][] = [];
  for (let r = 0; r < 3; r++) for (let c = 0; c < 4; c++) cells.push([c, r]);
  return (
    <group rotation={[-0.25, -0.15, 0]} position={[0, 0.02, 0]}>
      <RoundedBox args={[0.72, 0.7, 0.16]} radius={0.04} smoothness={3} position={[0, 0.37, 0]}>
        {mat(C.white, 0.75)}
      </RoundedBox>
      <RoundedBox args={[0.72, 0.16, 0.17]} radius={0.04} smoothness={3} position={[0, 0.66, 0]}>
        {mat(C.spruce, 0.5)}
      </RoundedBox>
      {[-0.18, 0.18].map((x) => (
        <mesh key={x} position={[x, 0.76, 0]} rotation={[0, Math.PI / 2, 0]}>
          <torusGeometry args={[0.05, 0.014, 8, 20]} />
          {mat(C.ink3, 0.35, 0.5)}
        </mesh>
      ))}
      {cells.map(([c, r]) => {
        const special = c === 2 && r === 1;
        return (
          <mesh key={`${c}-${r}`} position={[-0.24 + c * 0.16, 0.48 - r * 0.14, 0.085]}>
            <boxGeometry args={[0.11, 0.09, 0.01]} />
            {special ? <meshStandardMaterial ref={hot} color={C.amber} emissive={C.amber} emissiveIntensity={0.15} /> : mat(C.sageSoft, 0.8)}
          </mesh>
        );
      })}
    </group>
  );
}

function ReportModel({ done }: { done: boolean }) {
  const heights = [0.16, 0.26, 0.2, 0.34];
  return (
    <group>
      <group position={[0, 0.48, 0]} rotation={[-0.32, 0, 0]}>
        <RoundedBox args={[0.66, 0.86, 0.03]} radius={0.015} smoothness={3}>
          {mat(C.white, 0.8)}
        </RoundedBox>
        <mesh position={[-0.08, 0.32, 0.018]}>
          <boxGeometry args={[0.38, 0.045, 0.005]} />
          {mat(C.spruce)}
        </mesh>
        <mesh position={[-0.13, 0.24, 0.018]}>
          <boxGeometry args={[0.28, 0.025, 0.005]} />
          {mat(C.ink3)}
        </mesh>
        {heights.map((h, i) => (
          <mesh key={i} position={[-0.21 + i * 0.14, -0.33 + h / 2, 0.02]}>
            <boxGeometry args={[0.09, h, 0.01]} />
            {mat(i === 3 ? C.amber : i % 2 ? C.spruce3 : C.sage, 0.5)}
          </mesh>
        ))}
        {done && (
          <mesh position={[0.24, 0.31, 0.03]}>
            <sphereGeometry args={[0.05, 14, 14]} />
            <meshBasicMaterial color={C.amber} toneMapped={false} />
          </mesh>
        )}
      </group>
      {[-0.22, 0.22].map((x) => (
        <mesh key={x} position={[x, 0.24, -0.2]} rotation={[0.42, 0, 0]}>
          <cylinderGeometry args={[0.018, 0.018, 0.52, 8]} />
          {mat(C.spruce3, 0.4, 0.3)}
        </mesh>
      ))}
    </group>
  );
}

function GateModel({ open, pending, sent }: { open: boolean; pending: number; sent: number }) {
  const boom = useRef<THREE.Group>(null);
  useFrame((_, delta) => {
    if (!boom.current) return;
    const target = open ? 1.2 : 0;
    boom.current.rotation.z += (target - boom.current.rotation.z) * Math.min(1, delta * 4);
  });
  const stripes = 6;
  return (
    <group>
      <mesh position={[0, 0.004, 0]} rotation={[-Math.PI / 2, 0, 0]}>
        <planeGeometry args={[2.05, 1.75]} />
        {mat(C.sageSoft, 0.9)}
      </mesh>
      {[-0.82, 0.82].map((x) => (
        <group key={x} position={[x, 0, 0]}>
          <RoundedBox args={[0.14, 0.62, 0.14]} radius={0.03} smoothness={3} position={[0, 0.31, 0]}>
            {mat(C.white, 0.7)}
          </RoundedBox>
          <mesh position={[0, 0.64, 0]}>
            <boxGeometry args={[0.16, 0.06, 0.16]} />
            {mat(C.spruce, 0.5)}
          </mesh>
        </group>
      ))}
      <group ref={boom} position={[-0.82, 0.55, 0.12]}>
        {Array.from({ length: stripes }, (_, i) => (
          <mesh key={i} position={[0.15 + i * 0.27, 0, 0]}>
            <boxGeometry args={[0.27, 0.075, 0.075]} />
            {mat(i % 2 ? C.white : C.amber, 0.5)}
          </mesh>
        ))}
      </group>
      {/* the letter rack: emails the agent wrote, waiting for a person */}
      <group position={[-0.05, 0, -0.5]}>
        <RoundedBox args={[0.56, 0.08, 0.52]} radius={0.02} smoothness={2} position={[0, 0.04, 0]}>
          {mat(C.spruce, 0.55)}
        </RoundedBox>
        {Array.from({ length: Math.min(pending, 8) }, (_, i) => (
          <mesh key={i} position={[i % 2 ? 0.02 : -0.02, 0.21, -0.2 + i * 0.055]} rotation={[-0.14, ((i * 37) % 7) * 0.03 - 0.09, 0]}>
            <boxGeometry args={[0.44, 0.27, 0.016]} />
            {mat(C.white, 0.7)}
          </mesh>
        ))}
      </group>
      {/* the tray beyond the barrier: what a person has already sent */}
      <group position={[0.05, 0, 0.55]}>
        <RoundedBox args={[0.64, 0.06, 0.46]} radius={0.02} smoothness={2} position={[0, 0.03, 0]}>
          {mat("#dfe7fb", 0.6)}
        </RoundedBox>
        {Array.from({ length: Math.min(sent, 5) }, (_, i) => (
          <mesh key={i} position={[0, 0.072 + i * 0.022, 0]} rotation={[0, ((i * 53) % 7) * 0.08 - 0.24, 0]}>
            <boxGeometry args={[0.44, 0.018, 0.3]} />
            {mat(C.white, 0.7)}
          </mesh>
        ))}
      </group>
    </group>
  );
}

// ------------------------------------------------------------------ scene pieces
function Pad({ state }: { state: PadState }) {
  const ring = useRef<THREE.Mesh>(null);
  const color = state === "active" ? C.amber : state === "refused" ? C.crimson : state === "done" ? C.sage : C.rule;
  useFrame(({ clock }) => {
    if (!ring.current) return;
    const k = state === "active" || state === "refused" ? 1 + Math.sin(clock.elapsedTime * 7) * 0.035 : 1;
    ring.current.scale.set(k, k, 1);
  });
  return (
    <group>
      <mesh position={[0, 0.035, 0]}>
        <cylinderGeometry args={[0.7, 0.74, 0.07, 56]} />
        {mat(C.white, 0.85)}
      </mesh>
      <mesh ref={ring} rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.072, 0]}>
        <ringGeometry args={[0.6, 0.7, 64]} />
        <meshBasicMaterial color={color} toneMapped={false} />
      </mesh>
    </group>
  );
}

function Chip({ title, note, state, hovered, onGo, onHover, icon }: {
  title: string;
  note: string;
  state: PadState;
  hovered: boolean;
  onGo: () => void;
  onHover: (on: boolean) => void;
  icon?: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onGo}
      onMouseEnter={() => onHover(true)}
      onMouseLeave={() => onHover(false)}
      onFocus={() => onHover(true)}
      onBlur={() => onHover(false)}
      className={clsx(
        "flex items-center gap-1.5 whitespace-nowrap rounded-lg border bg-sheet/95 px-2.5 py-1.5 text-left text-[12px] leading-tight shadow-[0_8px_18px_-10px_rgba(15,59,53,0.45)] transition-[border-color,transform] duration-150",
        state === "active" ? "border-amber" : state === "refused" ? "border-crimson/70" : "border-rule",
        hovered && "-translate-y-0.5 border-ink-3/60",
      )}
    >
      {icon ?? (
        <span
          aria-hidden
          className={clsx(
            "size-2 shrink-0 rounded-full",
            state === "active" ? "bg-amber" : state === "refused" ? "bg-crimson" : state === "done" ? "bg-moss" : "bg-rule",
          )}
        />
      )}
      <span>
        <span className="block font-semibold text-ink">{title}</span>
        <span className="block text-ink-3">{note}</span>
      </span>
    </button>
  );
}

function StationNode({ index, state, still, hovered, onHover, onGo }: {
  index: number;
  state: PadState;
  still: boolean;
  hovered: boolean;
  onHover: (key: string | null) => void;
  onGo: (to: string) => void;
}) {
  const station = STATIONS[index];
  const lift = useRef<THREE.Group>(null);
  const active = state === "active" || state === "refused";
  useFrame((_, delta) => {
    if (!lift.current) return;
    const target = hovered ? 0.14 : 0;
    lift.current.position.y += (target - lift.current.position.y) * Math.min(1, delta * 10);
  });
  const model = {
    learn: <NotesModel active={active} />,
    research: <GlobeModel active={active} still={still} />,
    score: <BarsModel active={active} />,
    crm: <DatabaseModel active={active} />,
    draft: <EnvelopeModel active={active} still={still} />,
    followup: <CalendarModel active={active} />,
    report: <ReportModel done={state === "done"} />,
  }[station.key];
  return (
    <group position={[station.pos[0], 0, station.pos[1]]}>
      <Pad state={state} />
      <group position={[0, 0.07, 0]}>
        <group ref={lift}>{model}</group>
      </group>
      <mesh
        position={[0, 0.7, 0]}
        onPointerOver={(e) => {
          e.stopPropagation();
          onHover(station.key);
        }}
        onPointerOut={() => onHover(null)}
        onClick={(e) => {
          e.stopPropagation();
          onGo(station.to);
        }}
      >
        <cylinderGeometry args={[0.74, 0.74, 1.4, 16]} />
        <meshBasicMaterial transparent opacity={0} depthWrite={false} colorWrite={false} />
      </mesh>
    </group>
  );
}

function Track({ progress }: { progress: RefObject<number> }) {
  const base = useMemo(() => new THREE.TubeGeometry(CURVE, TUBE_SEGMENTS, 0.05, TUBE_RADIAL, false), []);
  const lit = useMemo(() => new THREE.TubeGeometry(CURVE, TUBE_SEGMENTS, 0.06, TUBE_RADIAL, false), []);
  useFrame(() => {
    const segments = Math.floor(TUBE_SEGMENTS * Math.min(1, Math.max(0, progress.current)));
    lit.setDrawRange(0, segments * TUBE_RADIAL * 6);
  });
  return (
    <group>
      <mesh geometry={base}>{mat(C.track, 0.7)}</mesh>
      <mesh geometry={lit}>
        <meshBasicMaterial color={C.amber} toneMapped={false} />
      </mesh>
    </group>
  );
}

function Orb({ progress, target, still, dim }: { progress: RefObject<number>; target: number; still: boolean; dim: boolean }) {
  const ref = useRef<THREE.Mesh>(null);
  const p = useMemo(() => new THREE.Vector3(), []);
  useFrame(({ clock }, delta) => {
    if (still) progress.current = target;
    else progress.current += (target - progress.current) * Math.min(1, delta * 5);
    CURVE.getPointAt(Math.min(1, Math.max(0, progress.current)), p);
    ref.current?.position.set(p.x, p.y + 0.24 + (still ? 0 : Math.sin(clock.elapsedTime * 4) * 0.035), p.z);
  });
  return (
    <mesh ref={ref}>
      <sphereGeometry args={[0.16, 28, 28]} />
      <meshStandardMaterial color={dim ? C.sage : C.amber} emissive={dim ? C.sage : C.amber} emissiveIntensity={dim ? 0.2 : 0.65} roughness={0.3} />
    </mesh>
  );
}

const CAM = new THREE.Vector3(0, 5.8, 9.8);
const LOOK = new THREE.Vector3(0.05, 0.25, 0.15);
/** Pull the camera back on narrow canvases and in on wide ones so the desk always fills the frame. */
const fitFor = (aspect: number) => Math.min(2.2, Math.max(0.7, 7.1 / (3 * aspect)));

function Rig() {
  const { camera, size, pointer } = useThree();
  useFrame(() => {
    const fit = fitFor(size.width / Math.max(1, size.height));
    const tx = CAM.x * fit + pointer.x * 0.6 * fit;
    const ty = CAM.y * fit + pointer.y * 0.35 * fit;
    const tz = CAM.z * fit;
    const dx = tx - camera.position.x;
    const dy = ty - camera.position.y;
    const dz = tz - camera.position.z;
    if (Math.abs(dx) + Math.abs(dy) + Math.abs(dz) < 1e-3) return;
    camera.position.set(camera.position.x + dx * 0.07, camera.position.y + dy * 0.07, camera.position.z + dz * 0.07);
    camera.lookAt(LOOK);
  });
  return null;
}

function StillCamera() {
  const { camera, size } = useThree();
  useLayoutEffect(() => {
    camera.position.copy(CAM).multiplyScalar(fitFor(size.width / Math.max(1, size.height)));
    camera.lookAt(LOOK);
  }, [camera, size]);
  return null;
}

/**
 * Keeps the DOM chips glued to their 3D anchors. The chips live in the normal React tree (so they
 * are real, focusable buttons); this just moves them every frame after the camera has moved.
 */
type Anchor = { key: string; pos: [number, number, number] };
function ChipAnchors({ anchors, refs }: { anchors: Anchor[]; refs: RefObject<Record<string, HTMLDivElement | null>> }) {
  const v = useMemo(() => new THREE.Vector3(), []);
  useFrame(({ camera, size }) => {
    camera.updateMatrixWorld();
    for (const a of anchors) {
      const el = refs.current[a.key];
      if (!el) continue;
      v.set(a.pos[0], a.pos[1], a.pos[2]).project(camera);
      const visible = v.z < 1;
      // whole pixels, written only when they change: crisp text and no needless layout work
      const t = visible ? `translate3d(${Math.round(((v.x + 1) / 2) * size.width)}px, ${Math.round(((1 - v.y) / 2) * size.height)}px, 0) translate(-50%, -100%)` : "hidden";
      if (el.dataset.at === t) continue;
      el.dataset.at = t;
      el.style.visibility = visible ? "visible" : "hidden";
      if (visible) el.style.transform = t;
    }
  });
  return null;
}

// ------------------------------------------------------------------ small screens
function FlowList({ notes, states, gate, onGo }: { notes: Record<string, string>; states: PadState[]; gate: string; onGo: (to: string) => void }) {
  return (
    <ol className="divide-y divide-rule-soft">
      {STATIONS.map((s, i) => (
        <li key={s.key}>
          <button onClick={() => onGo(s.to)} className="flex w-full items-center gap-3 px-5 py-2.5 text-left hover:bg-spruce/[0.03]">
            <span
              className={clsx(
                "num grid size-7 shrink-0 place-items-center rounded-full border-2 text-[12px] font-bold",
                states[i] === "active" ? "border-amber bg-amber-soft text-amber-ink" : states[i] === "refused" ? "border-crimson text-crimson" : states[i] === "done" ? "border-moss text-moss" : "border-rule text-ink-3",
              )}
            >
              {i + 1}
            </span>
            <span className="min-w-0">
              <span className="block text-[14px] font-semibold">{s.label}</span>
              <span className="block text-[13px] text-ink-3">{notes[s.key]}</span>
            </span>
          </button>
        </li>
      ))}
      <li>
        <button onClick={() => onGo(GATE.to)} className="flex w-full items-center gap-3 px-5 py-2.5 text-left hover:bg-spruce/[0.03]">
          <span className="grid size-7 shrink-0 place-items-center rounded-full border-2 border-spruce bg-spruce text-sheet">
            <Lock className="size-3.5" aria-hidden />
          </span>
          <span>
            <span className="block text-[14px] font-semibold">{GATE.label}</span>
            <span className="block text-[13px] text-ink-3">{gate}</span>
          </span>
        </button>
      </li>
    </ol>
  );
}

// ------------------------------------------------------------------ panel
export default function AgentFlow3D({ run, counts, height = 380 }: { run: Run | null; counts?: Overview["counts"]; height?: number }) {
  const reduced = usePrefersReducedMotion();
  const navigate = useNavigate();
  const box = useRef<HTMLDivElement>(null);
  const width = useWidth(box);
  const progress = useRef(0);
  const chipRefs = useRef<Record<string, HTMLDivElement | null>>({});
  const [hovered, setHovered] = useState<string | null>(null);

  const steps = useMemo<FlowStep[]>(() => flowSteps(run), [run]);
  const running = run?.status === "running";
  const { cursor, replaying, replay } = useReplay(steps.length, running, run?.id, reduced);
  const shown = steps.slice(0, cursor);
  const complete = cursor >= steps.length;
  const notes = stationNotes(shown, complete ? run : null, counts?.accounts);
  const last = shown[shown.length - 1];
  const activeIndex = last ? stationIndexOf(last.tool) : -1;
  const visited = new Set(shown.map((s) => stationIndexOf(s.tool)));
  const moving = running || replaying;
  const states: PadState[] = STATIONS.map((_, i) =>
    i === activeIndex && moving ? (last && !last.ok ? "refused" : "active") : visited.has(i) ? "done" : "idle",
  );
  const target = activeIndex >= 0 ? STATION_U[activeIndex] : 0;
  const pending = counts?.pending_drafts ?? 0;
  const sent = counts?.sent_drafts ?? 0;
  const gateOpen = pending === 0 && (counts?.approved_drafts ?? 0) + sent > 0;
  const go = (to: string) => navigate(to);

  let caption: string;
  if (!run) caption = "Run the agent and each step moves along this track.";
  else if (moving && last) caption = `Step ${shown.length}${replaying ? ` of ${steps.length}` : ""}: ${TOOL_LABEL[last.tool] ?? last.tool}${last.result ? `. ${last.result}` : ""}`;
  else if (moving) caption = "Starting the run";
  else caption = `${steps.length} steps in the last run. Click a station to open its page.`;

  return (
    <section className="panel overflow-hidden" aria-label="How the agent works">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-rule-soft px-5 py-3.5">
        <h2 className="heading text-[16px]">How the agent works</h2>
        <p className="min-w-0 flex-1 truncate text-[13px] text-ink-3" aria-live="polite">
          {caption}
        </p>
        {run && !running && steps.length > 0 && !reduced && (
          <button onClick={replay} disabled={replaying} className="inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-[13px] font-semibold text-ink-2 hover:bg-spruce/[0.05] hover:text-ink disabled:opacity-50">
            <RotateCcw className="size-3.5" aria-hidden /> Replay
          </button>
        )}
      </header>
      <div ref={box} className="relative" style={{ minHeight: width && width < 760 ? undefined : height }}>
        {width > 0 && width < 760 && <FlowList notes={notes} states={states} gate={gateNote(counts)} onGo={go} />}
        {width >= 760 && (
          <div className="absolute inset-0 bg-[radial-gradient(120%_90%_at_50%_0%,#ffffff_0%,#eef2ef_70%)]" style={{ cursor: hovered ? "pointer" : "default" }}>
            <Canvas flat dpr={[1, 2]} camera={{ position: [0, 5.8, 9.8], fov: 30 }} frameloop={reduced ? "demand" : "always"}>
              <ambientLight intensity={0.85} />
              <directionalLight position={[4, 9, 6]} intensity={1.5} />
              <directionalLight position={[-6, 4, -3]} intensity={0.35} />
              {reduced ? <StillCamera /> : <Rig />}
              <ChipAnchors anchors={ANCHORS} refs={chipRefs} />
              <RoundedBox args={[13.4, 0.5, 4.7]} radius={0.24} smoothness={4} position={[0.05, -0.25, 0.15]}>
                <meshStandardMaterial color="#fbfcfb" roughness={0.95} />
              </RoundedBox>
              <ContactShadows position={[0, 0.002, 0.15]} scale={[13.4, 4.7]} far={1.8} blur={2.4} opacity={0.3} resolution={512} color={C.spruce} frames={reduced ? 1 : Infinity} />
              <Track progress={progress} />
              <Orb progress={progress} target={target} still={reduced} dim={!run} />
              {STATIONS.map((s, i) => (
                <StationNode key={s.key} index={i} state={states[i]} still={reduced} hovered={hovered === s.key} onHover={setHovered} onGo={go} />
              ))}
              <Line points={[[STATIONS[4].pos[0], 0.09, STATIONS[4].pos[1] + 0.7], [GATE.pos[0] - 0.4, 0.09, GATE.pos[1] - 0.8]]} color={C.sage} lineWidth={2} dashed dashSize={0.14} gapSize={0.1} />
              <Line points={[[STATIONS[5].pos[0] - 0.2, 0.09, STATIONS[5].pos[1] + 0.72], [GATE.pos[0] + 0.4, 0.09, GATE.pos[1] - 0.8]]} color={C.sage} lineWidth={2} dashed dashSize={0.14} gapSize={0.1} />
              <group position={[GATE.pos[0], 0, GATE.pos[1]]}>
                <GateModel open={gateOpen} pending={pending} sent={sent} />
                <mesh
                  position={[0, 0.5, 0]}
                  onPointerOver={(e) => {
                    e.stopPropagation();
                    setHovered("gate");
                  }}
                  onPointerOut={() => setHovered(null)}
                  onClick={(e) => {
                    e.stopPropagation();
                    go(GATE.to);
                  }}
                >
                  <boxGeometry args={[2.1, 1, 1.5]} />
                  <meshBasicMaterial transparent opacity={0} depthWrite={false} colorWrite={false} />
                </mesh>
              </group>
            </Canvas>
            <div className="pointer-events-none absolute inset-0 overflow-hidden">
              {STATIONS.map((st, i) => (
                <div key={st.key} ref={(el) => void (chipRefs.current[st.key] = el)} className="pointer-events-auto absolute left-0 top-0" style={{ visibility: "hidden" }}>
                  <Chip title={st.label} note={notes[st.key]} state={states[i]} hovered={hovered === st.key} onGo={() => go(st.to)} onHover={(on) => setHovered(on ? st.key : null)} />
                </div>
              ))}
              <div ref={(el) => void (chipRefs.current.gate = el)} className="pointer-events-auto absolute left-0 top-0" style={{ visibility: "hidden" }}>
                <Chip
                  title={GATE.label}
                  note={gateNote(counts)}
                  state={pending ? "active" : "done"}
                  hovered={hovered === "gate"}
                  onGo={() => go(GATE.to)}
                  onHover={(on) => setHovered(on ? "gate" : null)}
                  icon={<Lock className="size-3.5 shrink-0 text-spruce" aria-hidden />}
                />
              </div>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
