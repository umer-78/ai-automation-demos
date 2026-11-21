import { useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import { RoundedBox } from "@react-three/drei";
import { Group, MeshStandardMaterial } from "three";
import { RAIL } from "./layout";
import { Label } from "./Label";
import { prefersReducedMotion, useHub } from "../store";

export const FAILED = new Set(["failure", "failed", "error"]);
const STEP = 0.74;

function Marker({ x, status, pulse }: { x: number; status: string; pulse: boolean }) {
  const g = useRef<Group>(null);
  const mat = useRef<MeshStandardMaterial>(null);
  const reduced = useMemo(prefersReducedMotion, []);
  const failed = FAILED.has(status);
  const color = failed ? "#E4572E" : status === "alert" ? "#F2B134" : "#12968A";
  useFrame(({ clock }, dt) => {
    if (!g.current) return;
    g.current.scale.setScalar(reduced ? 1 : g.current.scale.x + (1 - g.current.scale.x) * (1 - Math.exp(-dt * 5)));
    if (pulse && mat.current && !reduced) mat.current.emissiveIntensity = 1.7 + 1.2 * Math.sin(clock.getElapsedTime() * 4);
  });
  return (
    <group ref={g} position={[x, 1.03, 0]} scale={0.001}>
      <mesh castShadow>
        <capsuleGeometry args={[0.24, 0.55, 8, 16]} />
        <meshStandardMaterial ref={mat} color={color} emissive={color} emissiveIntensity={failed ? 1.7 : 0.15} toneMapped={!failed} roughness={0.4} />
      </mesh>
    </group>
  );
}

/** The activity log as a row of markers, oldest on the left. New entries grow in; the latest failure pulses. */
export function LogRail() {
  const log = useHub((s) => s.log);
  const show = useHub((s) => s.section === 4);
  const slack = useHub((s) => !!s.status?.integrations.slack);
  const items = useMemo(() => log.slice(0, 14).reverse(), [log]);
  const latestFail = useMemo(() => log.slice(0, 14).find((r) => FAILED.has(r.status)), [log]);
  const xAt = (i: number) => (i - (items.length - 1) / 2) * STEP;
  const failIndex = latestFail ? items.findIndex((r) => r.id === latestFail.id) : -1;
  return (
    <group position={RAIL}>
      <RoundedBox args={[11.4, 0.5, 3.2]} radius={0.16} smoothness={4} position={[0, 0.25, 0]} castShadow receiveShadow>
        <meshStandardMaterial color="#163A55" roughness={0.35} metalness={0.1} />
      </RoundedBox>
      <mesh position={[0, 0.506, 0]} rotation-x={-Math.PI / 2}>
        <planeGeometry args={[10.6, 0.05]} />
        <meshBasicMaterial color="#2E5A78" />
      </mesh>
      {items.map((r, i) => (
        <Marker key={r.id} x={xAt(i)} status={r.status} pulse={r.id === latestFail?.id} />
      ))}
      {latestFail && failIndex >= 0 && (
        <Label title={`${latestFail.workflow.charAt(0).toUpperCase()}${latestFail.workflow.slice(1).replace(/_/g, " ")} failed`}
          sub={slack ? "Alert sent to Slack" : "Slack isn't set up, so it stays in the log"} visible={show} tone="alert"
          position={[xAt(failIndex), 2.35, 0]} />
      )}
    </group>
  );
}
