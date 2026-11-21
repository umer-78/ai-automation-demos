import { Canvas, useFrame, useThree, type ThreeEvent } from "@react-three/fiber";
import { useLayoutEffect, useMemo, useRef, useState, type RefObject } from "react";
import * as THREE from "three";
import type { LeadCard } from "../lib/api";
import { usePrefersReducedMotion } from "../lib/hooks";
import { glowTexture, labelTexture, surfaceTexture, sweepTexture } from "../three/textures";
import { QUADRANTS } from "./radarMeta";

/**
 * Lead radar: a modelled console. Every researched company is a beacon. The closer to the centre
 * and the taller, the higher the score; the quadrant is the kind of buying signal that was found.
 * The sweep pings each beacon as it passes, and hot leads send out a ripple.
 */
const R = 4;
const TAU = Math.PI * 2;
const TRAIL = 1.15;
const RINGS = [85, 75, 65, 55, 45];

type Sweep = { angle: number; speed: number };

const quadrantOf = (signal: string | null) => QUADRANTS.find((q) => q.key === signal) ?? QUADRANTS[3];

function hash(n: number) {
  const x = Math.sin(n * 12.9898) * 43758.5453;
  return x - Math.floor(x);
}

/** Scores of 95+ sit near the centre, 35 and below on the rim; most real leads land between. */
const radiusFor = (score: number) => 0.55 + (R - 0.75) * Math.min(1, Math.max(0, (95 - score) / 60));

function placeLead(lead: LeadCard) {
  const q = quadrantOf(lead.signal);
  const theta = q.start + (0.1 + 0.8 * hash(lead.id)) * (Math.PI / 2);
  const radius = radiusFor(lead.score);
  return { x: radius * Math.cos(theta), z: -radius * Math.sin(theta), theta };
}

const colorFor = (lead: LeadCard) =>
  lead.status === "excluded" ? "#6b807b" : lead.score >= 75 ? "#e9a23b" : lead.score >= 60 ? "#d9c27f" : "#8fb8a8";

// ------------------------------------------------------------------ console body
function Ticks() {
  const ref = useRef<THREE.InstancedMesh>(null);
  useLayoutEffect(() => {
    const mesh = ref.current;
    if (!mesh) return;
    const m = new THREE.Matrix4();
    const q = new THREE.Quaternion();
    const up = new THREE.Vector3(0, 1, 0);
    for (let i = 0; i < 72; i++) {
      const a = (i / 72) * TAU;
      const major = i % 6 === 0;
      const len = major ? 0.22 : 0.1;
      const r = R + 0.14 + len / 2;
      q.setFromAxisAngle(up, a);
      m.compose(new THREE.Vector3(r * Math.cos(a), 0.012, -r * Math.sin(a)), q, new THREE.Vector3(len, 1, major ? 0.035 : 0.02));
      mesh.setMatrixAt(i, m);
    }
    mesh.instanceMatrix.needsUpdate = true;
  }, []);
  return (
    <instancedMesh ref={ref} args={[undefined, undefined, 72]}>
      <boxGeometry args={[1, 0.014, 1]} />
      <meshBasicMaterial color="#8fb8a8" transparent opacity={0.65} />
    </instancedMesh>
  );
}

function RingLabel({ score }: { score: number }) {
  const { texture, ratio } = useMemo(() => labelTexture(String(score), score === 75 ? "#f0c27a" : "#8fb8a8"), [score]);
  const r = radiusFor(score);
  const h = 0.3;
  return (
    <sprite position={[0.2 + (h * ratio) / 2, 0.16, r]} scale={[h * ratio, h, 1]}>
      <spriteMaterial map={texture} transparent opacity={0.85} depthWrite={false} />
    </sprite>
  );
}

function ConsoleBody() {
  const surface = useMemo(() => surfaceTexture(), []);
  return (
    <group>
      {/* the housing: a tapered puck with a metal lip */}
      <mesh position={[0, -0.25, 0]}>
        <cylinderGeometry args={[R + 0.5, R + 0.72, 0.48, 128]} />
        <meshStandardMaterial color="#0d3530" metalness={0.25} roughness={0.55} />
      </mesh>
      <mesh position={[0, -0.01, 0]} rotation={[Math.PI / 2, 0, 0]}>
        <torusGeometry args={[R + 0.5, 0.075, 16, 160]} />
        <meshStandardMaterial color="#1f5c53" metalness={0.5} roughness={0.32} />
      </mesh>
      {/* the face */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.002, 0]}>
        <circleGeometry args={[R, 128]} />
        <meshBasicMaterial map={surface} toneMapped={false} />
      </mesh>
      {/* glowing rim */}
      <mesh rotation={[Math.PI / 2, 0, 0]} position={[0, 0.02, 0]}>
        <torusGeometry args={[R + 0.04, 0.03, 12, 192]} />
        <meshBasicMaterial color="#a9d6c4" toneMapped={false} />
      </mesh>
      <mesh rotation={[Math.PI / 2, 0, 0]} position={[0, 0.02, 0]}>
        <torusGeometry args={[R + 0.04, 0.13, 12, 192]} />
        <meshBasicMaterial color="#8fb8a8" transparent opacity={0.1} blending={THREE.AdditiveBlending} depthWrite={false} />
      </mesh>
      <Ticks />
      {/* score rings: 75 is the hot-lead line */}
      <group rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.006, 0]}>
        {RINGS.map((s) => {
          const r = radiusFor(s);
          return (
            <mesh key={s}>
              <ringGeometry args={[r - (s === 75 ? 0.018 : 0.01), r + (s === 75 ? 0.018 : 0.01), 160]} />
              <meshBasicMaterial color={s === 75 ? "#e9a23b" : "#8fb8a8"} transparent opacity={s === 75 ? 0.55 : 0.28} />
            </mesh>
          );
        })}
        {QUADRANTS.map((q) => (
          <mesh key={q.key} position={[Math.cos(q.start) * (R / 2 + 0.25), Math.sin(q.start) * (R / 2 + 0.25), 0]} rotation={[0, 0, q.start]}>
            <planeGeometry args={[R - 0.5, 0.02]} />
            <meshBasicMaterial color="#8fb8a8" transparent opacity={0.3} />
          </mesh>
        ))}
      </group>
      {RINGS.map((s) => (
        <RingLabel key={s} score={s} />
      ))}
    </group>
  );
}

// ------------------------------------------------------------------ sweep and dish
function Dish() {
  const geometry = useMemo(() => {
    const pts: THREE.Vector2[] = [];
    for (let i = 0; i <= 14; i++) {
      const x = (i / 14) * 0.38;
      pts.push(new THREE.Vector2(x, x * x * 1.55));
    }
    return new THREE.LatheGeometry(pts, 40);
  }, []);
  return (
    <group>
      <mesh position={[0, 0.03, 0]}>
        <cylinderGeometry args={[0.2, 0.24, 0.06, 32]} />
        <meshStandardMaterial color="#123f38" metalness={0.4} roughness={0.4} />
      </mesh>
      <mesh position={[0, 0.27, 0]}>
        <cylinderGeometry args={[0.035, 0.055, 0.46, 12]} />
        <meshStandardMaterial color="#2c7366" metalness={0.35} roughness={0.4} />
      </mesh>
      <group position={[0, 0.52, 0]} rotation={[0, 0, -Math.PI / 3]}>
        <mesh geometry={geometry}>
          <meshStandardMaterial color="#e3eee9" metalness={0.2} roughness={0.35} side={THREE.DoubleSide} />
        </mesh>
        <mesh position={[0, 0.08, 0]}>
          <cylinderGeometry args={[0.009, 0.009, 0.16, 6]} />
          <meshStandardMaterial color="#cfe0d8" />
        </mesh>
        <mesh position={[0, 0.165, 0]}>
          <sphereGeometry args={[0.035, 14, 14]} />
          <meshBasicMaterial color="#ffd48c" toneMapped={false} />
        </mesh>
      </group>
    </group>
  );
}

function SweepArm({ sweep, scanning, still }: { sweep: RefObject<Sweep>; scanning: boolean; still: boolean }) {
  const group = useRef<THREE.Group>(null);
  const texture = useMemo(() => sweepTexture(TRAIL), []);
  useFrame((_, delta) => {
    const s = sweep.current;
    const target = scanning ? 1.9 : 0.4;
    s.speed += (target - s.speed) * Math.min(1, delta * 2.5);
    if (!still) s.angle = (s.angle - Math.min(delta, 0.05) * s.speed) % TAU;
    if (group.current) group.current.rotation.y = s.angle;
  });
  return (
    <group ref={group} position={[0, 0.014, 0]}>
      <mesh rotation={[-Math.PI / 2, 0, 0]}>
        <planeGeometry args={[2 * R, 2 * R]} />
        <meshBasicMaterial map={texture} color="#f2b552" transparent blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />
      </mesh>
      <Dish />
    </group>
  );
}

// ------------------------------------------------------------------ beacons
type HoverFn = (lead: LeadCard | null, e?: ThreeEvent<PointerEvent>) => void;

function Beacon({ lead, index, sweep, still, selected, onHover, onSelect }: {
  lead: LeadCard;
  index: number;
  sweep: RefObject<Sweep>;
  still: boolean;
  selected: boolean;
  onHover: HoverFn;
  onSelect?: (id: number) => void;
}) {
  const { x, z, theta } = useMemo(() => placeLead(lead), [lead]);
  const hot = lead.status !== "excluded" && lead.score >= 75;
  const color = colorFor(lead);
  const height = 0.25 + (Math.min(lead.score, 100) / 100) * 1.7;
  const glow = useMemo(() => glowTexture(), []);
  const stem = useRef<THREE.Group>(null);
  const pillar = useRef<THREE.MeshStandardMaterial>(null);
  const halo = useRef<THREE.Sprite>(null);
  const ripple = useRef<THREE.Mesh>(null);
  const born = useRef<number | null>(null);
  const phase = hash(lead.id + 7) * 2.6;

  useFrame(({ clock }) => {
    const t = clock.elapsedTime;
    if (born.current === null) born.current = t + index * 0.04;
    const rise = still ? 1 : Math.min(1, Math.max(0, (t - born.current) / 0.7));
    if (stem.current) stem.current.scale.y = Math.max(0.001, 1 - Math.pow(1 - rise, 3));
    // how far the sweep's leading edge has travelled since it crossed this beacon
    let d = (theta - sweep.current.angle) % TAU;
    if (d < 0) d += TAU;
    const ping = still ? 0 : Math.max(0, 1 - d / 0.85);
    if (pillar.current) pillar.current.emissiveIntensity = (hot ? 0.5 : 0.16) + ping * 1.2;
    if (halo.current) {
      const s = (hot ? 0.8 : 0.5) * (1 + ping * 0.9) * (selected ? 1.35 : 1);
      halo.current.scale.set(s, s, 1);
      (halo.current.material as THREE.SpriteMaterial).opacity = (hot ? 0.9 : 0.5) * (0.55 + 0.45 * ping);
    }
    if (ripple.current) {
      const k = ((t + phase) % 2.6) / 2.6;
      ripple.current.scale.setScalar(1 + k * 3.4);
      (ripple.current.material as THREE.MeshBasicMaterial).opacity = (1 - k) * 0.55;
    }
  });

  return (
    <group position={[x, 0, z]}>
      <group ref={stem}>
        <mesh position={[0, height / 2, 0]}>
          <cylinderGeometry args={[selected ? 0.085 : 0.055, selected ? 0.085 : 0.06, height, 14]} />
          <meshStandardMaterial ref={pillar} color={color} emissive={color} emissiveIntensity={hot ? 0.5 : 0.16} roughness={0.45} />
        </mesh>
        <mesh position={[0, height + 0.05, 0]}>
          <sphereGeometry args={[hot ? 0.11 : 0.08, 18, 18]} />
          <meshBasicMaterial color={color} toneMapped={false} />
        </mesh>
        <sprite ref={halo} position={[0, height + 0.05, 0]}>
          <spriteMaterial map={glow} color={color} transparent blending={THREE.AdditiveBlending} depthWrite={false} toneMapped={false} />
        </sprite>
      </group>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.008, 0]}>
        <ringGeometry args={[0.1, 0.15, 28]} />
        <meshBasicMaterial color={color} transparent opacity={0.5} />
      </mesh>
      {hot && !still && (
        <mesh ref={ripple} rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.01, 0]}>
          <ringGeometry args={[0.13, 0.16, 40]} />
          <meshBasicMaterial color={color} transparent depthWrite={false} toneMapped={false} />
        </mesh>
      )}
      {selected && (
        <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.012, 0]}>
          <ringGeometry args={[0.21, 0.26, 40]} />
          <meshBasicMaterial color="#ffffff" toneMapped={false} />
        </mesh>
      )}
      {/* a fatter invisible column so thin beacons are easy to point at */}
      <mesh
        position={[0, (height + 0.3) / 2, 0]}
        onPointerOver={(e) => {
          e.stopPropagation();
          onHover(lead, e);
        }}
        onPointerMove={(e) => onHover(lead, e)}
        onPointerOut={() => onHover(null)}
        onClick={(e) => {
          e.stopPropagation();
          onSelect?.(lead.id);
        }}
      >
        <cylinderGeometry args={[0.2, 0.2, height + 0.3, 8]} />
        <meshBasicMaterial transparent opacity={0} depthWrite={false} colorWrite={false} />
      </mesh>
    </group>
  );
}

// ------------------------------------------------------------------ camera
function Rig({ still }: { still: boolean }) {
  const { camera, size, pointer } = useThree();
  useFrame(() => {
    const aspect = size.width / Math.max(1, size.height);
    const fit = Math.max(1.06, 1.36 / aspect);
    const tx = (still ? 0 : pointer.x * 0.9) * fit;
    const ty = (8.5 + (still ? 0 : pointer.y * 0.5)) * fit;
    const tz = 8.1 * fit;
    const k = still ? 1 : 0.06;
    const d = Math.abs(tx - camera.position.x) + Math.abs(ty - camera.position.y) + Math.abs(tz - camera.position.z);
    if (d < 1e-3 && !still) return;
    camera.position.set(camera.position.x + (tx - camera.position.x) * k, camera.position.y + (ty - camera.position.y) * k, camera.position.z + (tz - camera.position.z) * k);
    camera.lookAt(0, -1.15, 0.85);
  });
  return null;
}

export default function LeadRadar({ leads, scanning, onSelect, selectedId }: { leads: LeadCard[]; scanning: boolean; onSelect?: (id: number) => void; selectedId?: number | null }) {
  const reduced = usePrefersReducedMotion();
  const box = useRef<HTMLDivElement>(null);
  const sweep = useRef<Sweep>({ angle: 0.9, speed: 0.4 });
  const [hover, setHover] = useState<{ lead: LeadCard; x: number; y: number } | null>(null);

  const onHover: HoverFn = (lead, e) => {
    if (!lead || !e || !box.current) return setHover(null);
    const rect = box.current.getBoundingClientRect();
    setHover({ lead, x: e.nativeEvent.clientX - rect.left, y: e.nativeEvent.clientY - rect.top });
  };

  return (
    <div ref={box} className="relative h-full w-full" onPointerLeave={() => setHover(null)}>
      <Canvas
        flat
        dpr={[1, 2]}
        camera={{ position: [0, 8.5, 8.1], fov: 42 }}
        frameloop={reduced ? "demand" : "always"}
        style={{ cursor: hover ? "pointer" : "default" }}
        aria-label="Lead radar. Each beacon is a researched company; taller and closer to the centre means a higher score."
        role="img"
      >
        <hemisphereLight args={["#d8ebe2", "#0b2c28", 0.7]} />
        <directionalLight position={[3, 9, 5]} intensity={1.15} />
        <pointLight position={[0, 2.2, 0]} intensity={4} distance={7} color="#f2b552" />
        <Rig still={reduced} />
        <group position={[0, -0.2, 0.25]}>
          <ConsoleBody />
          <SweepArm sweep={sweep} scanning={scanning} still={reduced} />
          {leads.map((lead, i) => (
            <Beacon key={lead.id} lead={lead} index={i} sweep={sweep} still={reduced} onHover={onHover} onSelect={onSelect} selected={selectedId === lead.id} />
          ))}
        </group>
      </Canvas>
      {hover && (
        <div
          className="pointer-events-none absolute z-10 w-64 rounded-lg bg-sheet px-3 py-2 text-[13px] text-ink shadow-xl"
          style={{ left: Math.max(8, Math.min(hover.x + 14, (box.current?.clientWidth ?? 400) - 264)), top: Math.max(8, hover.y - 76) }}
        >
          <div className="flex items-baseline justify-between gap-2">
            <span className="heading truncate text-[14px]">{hover.lead.company}</span>
            <span className="num font-bold">{hover.lead.score}</span>
          </div>
          {hover.lead.fact && <p className="mt-0.5 line-clamp-2 text-ink-2">{hover.lead.fact}</p>}
          {hover.lead.status === "excluded" ? (
            <p className="mt-0.5 text-ink-3">Excluded by the ideal customer profile</p>
          ) : (
            <p className="mt-0.5 text-ink-3">Click to open the lead</p>
          )}
        </div>
      )}
    </div>
  );
}
