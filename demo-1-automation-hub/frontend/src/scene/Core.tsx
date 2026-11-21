import { useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import { RoundedBox } from "@react-three/drei";
import { Color, Group, InstancedMesh, Mesh, MeshStandardMaterial, Object3D, QuadraticBezierCurve3, Shape, Vector3 } from "three";
import { CORE, STATIONS } from "./layout";
import { Label } from "./Label";
import { hub, prefersReducedMotion, useHub } from "../store";

const TRAVEL_MS = 900; // one packet's trip along a tube
const IDLE = new Color("#12968A").multiplyScalar(1.25);
const OUTER = STATIONS.map((s, i) => ({ s, i })).filter(({ s }) => !s.core);
const SLOTS = 4; // per tube: one slow heartbeat packet + three for real events

/** 0..1 while one of a station's packets is arriving (offset = ms after launch when it arrives). */
function arrival(station: number, now: number, offset: number) {
  let v = 0;
  for (const p of hub.get().pulse) {
    if (p.station !== station) continue;
    const t = now - p.at - offset;
    if (t > -250 && t < 650) v = Math.max(v, 1 - Math.abs(t) / 650);
  }
  return v;
}

const clay = (color: string) => <meshPhysicalMaterial color={color} roughness={0.42} clearcoat={0.7} clearcoatRoughness={0.3} />;

const SLACK = [
  { x: -0.16, y: 0, horizontal: false, color: "#36C5F0" },
  { x: 0.16, y: 0, horizontal: false, color: "#2EB67D" },
  { x: 0, y: -0.16, horizontal: true, color: "#ECB22E" },
  { x: 0, y: 0.16, horizontal: true, color: "#E01E5A" },
];

/** Clay models of each tool's mark. */
function Icon({ i }: { i: number }) {
  const bolt = useMemo(() => {
    const s = new Shape();
    s.moveTo(0.12, 0.62); s.lineTo(-0.36, -0.06); s.lineTo(-0.03, -0.06);
    s.lineTo(-0.14, -0.62); s.lineTo(0.36, 0.08); s.lineTo(0.03, 0.08); s.closePath();
    return s;
  }, []);
  if (i === 0)
    return (
      <group>
        {["#FCB400", "#18BFFF", "#F82B60"].map((c, k) => (
          <RoundedBox key={c} args={[1.15, 0.2, 0.8]} radius={0.07} smoothness={4} position={[0, k * 0.27, 0]} castShadow>
            {clay(c)}
          </RoundedBox>
        ))}
      </group>
    );
  if (i === 1)
    return (
      <group>
        {[-0.38, 0, 0.38].map((x, k) => (
          <RoundedBox key={x} args={[0.22, 0.95, 0.22]} radius={0.08} position={[x, 0.36, 0]} rotation={[0, 0, -0.42]} castShadow>
            {clay(k === 1 ? "#9B7BFF" : "#6D4AFF")}
          </RoundedBox>
        ))}
      </group>
    );
  if (i === 3)
    return (
      <mesh position={[0, 0.55, -0.1]} castShadow>
        <extrudeGeometry args={[bolt, { depth: 0.2, bevelEnabled: true, bevelSize: 0.03, bevelThickness: 0.03, bevelSegments: 3 }]} />
        {clay("#3ECF8E")}
      </mesh>
    );
  return (
    <group position={[0, 0.5, 0]}>
      {SLACK.map((p) => (
        <mesh key={p.color} position={[p.x, p.y, p.horizontal ? -0.05 : 0.05]} rotation={[0, 0, p.horizontal ? Math.PI / 2 : 0]} castShadow>
          <capsuleGeometry args={[0.1, 0.62, 8, 16]} />
          {clay(p.color)}
        </mesh>
      ))}
    </group>
  );
}

function StationModel({ i, labels }: { i: number; labels: boolean }) {
  const s = STATIONS[i];
  const ring = useRef<MeshStandardMaterial>(null);
  const icon = useRef<Group>(null);
  useFrame(() => {
    const a = arrival(i, performance.now(), s.incoming ? 0 : TRAVEL_MS);
    if (ring.current) ring.current.emissiveIntensity += (0.35 + 3.2 * a - ring.current.emissiveIntensity) * 0.18;
    if (icon.current) icon.current.scale.setScalar(1 + 0.16 * a);
  });
  return (
    <group position={s.pos}>
      <mesh position={[0, -0.33, 0]} castShadow receiveShadow>
        <cylinderGeometry args={[1.25, 1.36, 0.38, 64]} />
        <meshStandardMaterial color="#F6F8FA" roughness={0.55} />
      </mesh>
      <mesh position={[0, -0.135, 0]} rotation-x={-Math.PI / 2}>
        <ringGeometry args={[1.06, 1.2, 64]} />
        <meshStandardMaterial ref={ring} color={s.color} emissive={s.color} emissiveIntensity={0.35} toneMapped={false} />
      </mesh>
      <group ref={icon} position={[0, -0.04, 0]}>
        <Icon i={i} />
      </group>
      <Label title={s.name} sub={s.sub} visible={labels} position={[0, -0.7, 1.45]} />
    </group>
  );
}

/** The hub: a glass shell around Claude's knot, which flares when work arrives. */
function HubCore({ labels }: { labels: boolean }) {
  const shell = useRef<Mesh>(null);
  const knot = useRef<Mesh>(null);
  const glow = useRef<MeshStandardMaterial>(null);
  const reduced = useMemo(prefersReducedMotion, []);
  useFrame((_, dt) => {
    const now = performance.now();
    const e = Math.max(arrival(2, now, 150), arrival(0, now, TRAVEL_MS), arrival(1, now, TRAVEL_MS));
    if (glow.current) glow.current.emissiveIntensity += (1.15 + 3.4 * e - glow.current.emissiveIntensity) * 0.14;
    if (!reduced && knot.current && shell.current) {
      knot.current.rotation.x += dt * 0.25;
      knot.current.rotation.y += dt * (0.4 + 2.2 * e);
      shell.current.rotation.y -= dt * 0.05;
    }
  });
  return (
    <group position={CORE}>
      <mesh ref={shell}>
        <icosahedronGeometry args={[1.6, 1]} />
        <meshPhysicalMaterial color="#ffffff" transmission={1} thickness={0.7} roughness={0.03} ior={1.45} flatShading
          clearcoat={1} attenuationColor="#c9f1ec" attenuationDistance={2.6} />
      </mesh>
      <mesh ref={knot}>
        <torusKnotGeometry args={[0.55, 0.17, 200, 24]} />
        <meshStandardMaterial ref={glow} color="#0b5f58" emissive="#16b3a4" emissiveIntensity={1.15} roughness={0.35} toneMapped={false} />
      </mesh>
      <mesh position={[0, -1.95, 0]} castShadow receiveShadow>
        <cylinderGeometry args={[1.2, 1.45, 0.4, 64]} />
        <meshStandardMaterial color="#F6F8FA" roughness={0.5} />
      </mesh>
      <mesh position={[0, -1.745, 0]} rotation-x={-Math.PI / 2}>
        <ringGeometry args={[1.0, 1.12, 64]} />
        <meshStandardMaterial color="#12968A" emissive="#12968A" emissiveIntensity={0.6} toneMapped={false} />
      </mesh>
      <Label title="Hub API" sub="Python and Claude" visible={labels} position={[0, -2.45, 1.7]} />
    </group>
  );
}

/** Glass tubes from the hub to each tool; packets run along them when the API reports real steps. */
export function Core() {
  const labels = useHub((st) => st.section <= 1);
  const packets = useRef<InstancedMesh>(null);
  const reduced = useMemo(prefersReducedMotion, []);
  const curves = useMemo(
    () =>
      OUTER.map(({ s }) => {
        const dir = new Vector3(s.pos.x - CORE.x, 0, s.pos.z - CORE.z).normalize();
        const a = CORE.clone().addScaledVector(dir, 1.35).add(new Vector3(0, -0.6, 0));
        const b = s.pos.clone().addScaledVector(dir, -1.1).add(new Vector3(0, 0.1, 0));
        const mid = a.clone().lerp(b, 0.5).add(new Vector3(0, 1.1, 0));
        return new QuadraticBezierCurve3(a, mid, b);
      }),
    [],
  );
  const bright = useMemo(() => OUTER.map(({ s }) => new Color(s.color).multiplyScalar(2.4)), []);
  const dummy = useMemo(() => new Object3D(), []);

  useFrame(({ clock }) => {
    const mesh = packets.current;
    if (!mesh) return;
    const now = performance.now();
    const t = clock.getElapsedTime();
    const pulse = hub.get().pulse;
    OUTER.forEach(({ s, i }, k) => {
      const burst = pulse.filter((p) => p.station === i && now >= p.at && now - p.at < TRAVEL_MS + 400).pop();
      for (let j = 0; j < SLOTS; j++) {
        let u = 0;
        let scale = 0;
        if (j === 0) {
          if (!reduced) { u = (t * 0.1 + k * 0.27) % 1; scale = 0.6; }
        } else if (burst) {
          const prog = (now - burst.at - (j - 1) * 110) / TRAVEL_MS;
          if (prog >= 0 && prog <= 1) { u = prog; scale = 1.3 - (j - 1) * 0.25; }
        }
        if (s.incoming) u = 1 - u; // Airtable and Make send work in; the rest receive it
        curves[k].getPoint(u, dummy.position);
        dummy.scale.setScalar(scale);
        dummy.updateMatrix();
        mesh.setMatrixAt(k * SLOTS + j, dummy.matrix);
        mesh.setColorAt(k * SLOTS + j, j === 0 ? IDLE : bright[k]);
      }
    });
    mesh.instanceMatrix.needsUpdate = true;
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
  });

  return (
    <group>
      <mesh position={[0, 0.02, -1.4]} rotation-x={-Math.PI / 2} receiveShadow>
        <circleGeometry args={[8.6, 96]} />
        <meshStandardMaterial color="#EEF2F5" roughness={0.85} />
      </mesh>
      {[3.2, 6.1, 8.6].map((r) => (
        <mesh key={r} position={[0, 0.03, -1.4]} rotation-x={-Math.PI / 2}>
          <ringGeometry args={[r - 0.025, r, 128]} />
          <meshBasicMaterial color="#C9D5DE" />
        </mesh>
      ))}
      <HubCore labels={labels} />
      {curves.map((c, k) => (
        <mesh key={k}>
          <tubeGeometry args={[c, 64, 0.065, 12, false]} />
          <meshPhysicalMaterial color="#ffffff" roughness={0.15} transmission={0.9} thickness={0.2} ior={1.3} />
        </mesh>
      ))}
      <instancedMesh ref={packets} args={[undefined, undefined, OUTER.length * SLOTS]}>
        <sphereGeometry args={[0.075, 16, 16]} />
        <meshBasicMaterial toneMapped={false} />
      </instancedMesh>
      {OUTER.map(({ i }) => <StationModel key={i} i={i} labels={labels} />)}
    </group>
  );
}
