import { useMemo, useRef, useState } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { Environment, Lightformer, PerformanceMonitor } from "@react-three/drei";
import { Bloom, EffectComposer, N8AO, Vignette } from "@react-three/postprocessing";
import { DirectionalLight, Object3D, Vector3 } from "three";
import { CameraRig } from "./CameraRig";
import { Agent } from "./Agent";
import { CrmChips, LeadPins, Letters, Table } from "./Desk";
import { BG, FOCUS } from "./layout";
import { tagLayer } from "./Label";
import { store } from "../store";

const KEY_OFFSET = new Vector3(-6, 14, 8);

/** Warm desk-lamp key light that follows the area in view, so shadows stay crisp. */
function KeyLight() {
  const light = useRef<DirectionalLight>(null);
  const target = useMemo(() => new Object3D(), []);
  useFrame((_, dt) => {
    if (!light.current) return;
    target.position.lerp(FOCUS[store.get().section] ?? FOCUS[0], 1 - Math.exp(-dt * 2));
    light.current.position.copy(target.position).add(KEY_OFFSET);
  });
  return (
    <>
      <primitive object={target} />
      <directionalLight ref={light} target={target} castShadow intensity={2.4} color="#FFE6C2" position={KEY_OFFSET.toArray()}
        shadow-mapSize={[2048, 2048]} shadow-bias={-0.0003} shadow-normalBias={0.025}>
        <orthographicCamera attach="shadow-camera" args={[-13, 13, 13, -13, 1, 50]} />
      </directionalLight>
    </>
  );
}

export default function Scene() {
  tagLayer.current = document.querySelector<HTMLElement>(".scene-layer") ?? document.body;
  const [rich, setRich] = useState(true);
  const [dpr, setDpr] = useState(() => Math.min(1.75, window.devicePixelRatio || 1));
  return (
    <Canvas
      shadows="percentage"
      dpr={dpr}
      gl={{ antialias: false, powerPreference: "high-performance", stencil: false }}
      camera={{ fov: 40, near: 0.1, far: 120, position: [0, 16, 34] }}
      eventSource={document.getElementById("root") ?? undefined}
      eventPrefix="client"
    >
      <color attach="background" args={[BG]} />
      <fog attach="fog" args={[BG, 24, 58]} />
      <PerformanceMonitor onDecline={() => { setRich(false); setDpr(1); }} />
      <hemisphereLight args={["#3E6B60", "#0B1F1B", 0.9]} />
      <KeyLight />
      <directionalLight position={[10, 6, -10]} intensity={0.8} color="#9CC9E8" />
      <Environment resolution={256} frames={1}>
        <Lightformer form="rect" intensity={1.6} color="#FFE0B0" position={[-6, 8, 6]} rotation-x={Math.PI / 2} scale={[10, 6, 1]} />
        <Lightformer form="rect" intensity={0.9} color="#9CC9E8" position={[10, 3, -6]} rotation-y={-Math.PI / 2} scale={[10, 3, 1]} />
        <Lightformer form="ring" intensity={1.2} color="#F2A541" position={[0, 4, 8]} scale={3} />
      </Environment>
      <mesh rotation-x={-Math.PI / 2} position={[0, 0, 0]} receiveShadow>
        <planeGeometry args={[140, 140]} />
        <meshStandardMaterial color="#0F2925" roughness={1} />
      </mesh>
      <Table />
      <Agent />
      <LeadPins />
      <CrmChips />
      <Letters />
      <CameraRig />
      {rich ? (
        <EffectComposer multisampling={4}>
          <N8AO halfRes aoRadius={1} intensity={2} distanceFalloff={0.8} />
          <Bloom mipmapBlur luminanceThreshold={0.95} intensity={0.75} />
          <Vignette offset={0.3} darkness={0.55} />
        </EffectComposer>
      ) : (
        <EffectComposer multisampling={0}>
          <Bloom mipmapBlur luminanceThreshold={0.95} intensity={0.6} />
        </EffectComposer>
      )}
    </Canvas>
  );
}
