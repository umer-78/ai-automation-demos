import { useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import { Group, Mesh, MeshBasicMaterial, MeshStandardMaterial, PointLight, Quaternion, Vector3 } from "three";
import { CORE, TOOL_POS, TOOLS } from "./layout";
import { Label } from "./Label";
import { TOOL_LABELS } from "../api";
import { prefersReducedMotion, store, useAgent } from "../store";

const BRASS = { color: "#C9A15A", metalness: 1, roughness: 0.28 };
const BEAM_MS = 1100;

/** 0..1 for how recently this tool fired (1 = just now). */
function heat(tool: string, now: number) {
  let v = 0;
  for (const b of store.get().beams) {
    if (b.tool !== tool) continue;
    const t = now - b.at;
    if (t >= 0 && t < BEAM_MS) v = Math.max(v, 1 - t / BEAM_MS);
  }
  return v;
}

function ToolToken({ i, labels }: { i: number; labels: boolean }) {
  const tool = TOOLS[i];
  const p = TOOL_POS[i];
  const ring = useRef<MeshStandardMaterial>(null);
  const beam = useRef<Mesh>(null);
  const token = useRef<Group>(null);
  // A thin beam from the agent to this token, oriented once.
  const { mid, len, quat } = useMemo(() => {
    const from = CORE.clone().add(new Vector3(0, -0.4, 0));
    const dir = p.clone().sub(from);
    return {
      mid: from.clone().add(dir.clone().multiplyScalar(0.5)), len: dir.length(),
      quat: new Quaternion().setFromUnitVectors(new Vector3(0, 1, 0), dir.clone().normalize()),
    };
  }, [p]);
  useFrame(() => {
    const h = heat(tool, performance.now());
    if (ring.current) ring.current.emissiveIntensity = 0.25 + 3.2 * h;
    if (beam.current) (beam.current.material as MeshBasicMaterial).opacity = 0.85 * h;
    if (token.current) token.current.position.y = p.y + 0.12 * h;
  });
  return (
    <group>
      <mesh ref={beam} position={mid} quaternion={quat}>
        <cylinderGeometry args={[0.035, 0.035, len, 8]} />
        <meshBasicMaterial color={[2.6, 1.7, 0.7]} transparent opacity={0} toneMapped={false} depthWrite={false} />
      </mesh>
      <group ref={token} position={p}>
        <mesh castShadow>
          <cylinderGeometry args={[0.42, 0.46, 0.16, 48]} />
          <meshStandardMaterial {...BRASS} />
        </mesh>
        <mesh position={[0, 0.085, 0]} rotation-x={-Math.PI / 2}>
          <ringGeometry args={[0.2, 0.3, 48]} />
          <meshStandardMaterial ref={ring} color="#F2A541" emissive="#F2A541" emissiveIntensity={0.25} toneMapped={false} />
        </mesh>
        <mesh position={[0, -0.55, 0]}>
          <cylinderGeometry args={[0.03, 0.03, 1.0, 8]} />
          <meshStandardMaterial {...BRASS} />
        </mesh>
        <Label title={TOOL_LABELS[tool]} visible={labels} position={[0, 0.5, 0]} size={8} />
      </group>
    </group>
  );
}

/** The agent: a brass armillary around an amber core that flares on every tool call. */
export function Agent() {
  const labels = useAgent((s) => s.section === 1);
  const live = useAgent((s) => !!s.status?.live_model);
  const rings = useRef<Group>(null);
  const core = useRef<MeshStandardMaterial>(null);
  const light = useRef<PointLight>(null);
  const reduced = useMemo(prefersReducedMotion, []);
  useFrame(({ clock }, dt) => {
    const now = performance.now();
    const h = Math.max(0, ...TOOLS.map((t) => heat(t, now)));
    const running = !!store.get().live && !store.get().live?.done;
    if (core.current) core.current.emissiveIntensity += (1.4 + 2.4 * h + (running ? 0.5 : 0) - core.current.emissiveIntensity) * 0.15;
    if (light.current) light.current.intensity = 6 + 18 * h;
    if (!reduced && rings.current) {
      const speed = running ? 1.8 : 0.35;
      rings.current.children.forEach((c, k) => {
        c.rotation.x += dt * speed * (0.3 + k * 0.17);
        c.rotation.y += dt * speed * (0.2 + k * 0.11);
      });
      rings.current.position.y = CORE.y + Math.sin(clock.getElapsedTime() * 0.8) * 0.05;
    }
  });
  return (
    <group>
      <group ref={rings} position={CORE}>
        {[1.25, 1.05, 0.85].map((r, k) => (
          <mesh key={r} rotation={[k * 0.9, k * 0.5, 0]} castShadow>
            <torusGeometry args={[r, 0.045, 16, 128]} />
            <meshStandardMaterial {...BRASS} />
          </mesh>
        ))}
      </group>
      <mesh position={CORE}>
        <sphereGeometry args={[0.42, 48, 48]} />
        <meshStandardMaterial ref={core} color="#8A4B0E" emissive="#F2A541" emissiveIntensity={1.4} roughness={0.35} toneMapped={false} />
      </mesh>
      <pointLight ref={light} position={CORE} color="#F2A541" intensity={6} distance={9} decay={2} />
      <mesh position={[0, 0.75, 0]} castShadow receiveShadow>
        <cylinderGeometry args={[0.7, 0.95, 0.9, 64]} />
        <meshStandardMaterial color="#1E453D" roughness={0.6} />
      </mesh>
      <mesh position={[0, 1.6, 0]}>
        <cylinderGeometry args={[0.05, 0.05, 0.9, 8]} />
        <meshStandardMaterial {...BRASS} />
      </mesh>
      <Label title="The agent" sub={live ? "Claude with nine tools" : "Offline agent, same nine tools"} visible={labels} position={[0, 4.45, 0]} size={9} />
      {TOOLS.map((_, i) => <ToolToken key={i} i={i} labels={labels} />)}
    </group>
  );
}
