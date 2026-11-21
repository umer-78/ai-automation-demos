import { useMemo } from "react";
import { Html, RoundedBox } from "@react-three/drei";
import { MONITOR, SHOTS } from "./layout";
import { screenLayer } from "./Label";
import { useHub } from "../store";

/** A studio display that shows the latest website draft. 1280 x 720 CSS px maps onto the 7.2 x 4.05 screen. */
export function Monitor() {
  const preview = useHub((s) => s.preview);
  const show = useHub((s) => s.section === 3);
  const yaw = useMemo(() => Math.atan2(SHOTS[3][0].x - MONITOR.x, SHOTS[3][0].z - MONITOR.z), []);
  return (
    <group position={MONITOR} rotation-y={yaw}>
      <RoundedBox args={[7.7, 4.6, 0.28]} radius={0.16} smoothness={5} castShadow receiveShadow>
        <meshPhysicalMaterial color="#F7F9FA" roughness={0.38} clearcoat={0.6} />
      </RoundedBox>
      <mesh position={[0, 0.02, 0.145]}>
        <planeGeometry args={[7.2, 4.05]} />
        <meshStandardMaterial color="#0F2A3F" roughness={0.25} emissive="#0F2A3F" emissiveIntensity={0.25} />
      </mesh>
      <mesh position={[0, -2.8, -0.3]} castShadow>
        <boxGeometry args={[0.55, 1.1, 0.2]} />
        <meshStandardMaterial color="#EEF2F5" roughness={0.45} />
      </mesh>
      <mesh position={[0, -3.33, -0.3]} castShadow receiveShadow>
        <cylinderGeometry args={[1.5, 1.6, 0.14, 64]} />
        <meshStandardMaterial color="#F6F8FA" roughness={0.5} />
      </mesh>
      <Html portal={screenLayer} transform distanceFactor={2.25} position={[0, 0.02, 0.152]} pointerEvents="none" zIndexRange={[10, 0]}
        style={{ opacity: show ? 1 : 0, transition: "opacity .6s ease" }}>
        {preview ? (
          <iframe className="monitor-frame" title="Website draft preview" src={preview} width={1280} height={720} sandbox="" tabIndex={-1} />
        ) : (
          <div className="monitor-empty">Generate a draft and it appears here.</div>
        )}
      </Html>
    </group>
  );
}
