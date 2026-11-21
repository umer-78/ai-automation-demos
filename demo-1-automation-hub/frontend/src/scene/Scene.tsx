import { useMemo, useRef, useState } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { Environment, Lightformer, PerformanceMonitor } from "@react-three/drei";
import { Bloom, EffectComposer, N8AO, Vignette } from "@react-three/postprocessing";
import { DirectionalLight, NeutralToneMapping, Object3D, Vector3 } from "three";
import { CameraRig } from "./CameraRig";
import { Core } from "./Core";
import { DataCity } from "./DataCity";
import { Monitor } from "./Monitor";
import { LogRail } from "./LogRail";
import { FOCUS, FOG } from "./layout";
import { screenLayer, tagLayer } from "./Label";
import { hub } from "../store";

const LIGHT_OFFSET = new Vector3(7, 15, 9);

/** Soft studio key light that follows whichever area the camera is looking at, so shadows stay sharp everywhere. */
function KeyLight() {
  const light = useRef<DirectionalLight>(null);
  const target = useMemo(() => {
    const o = new Object3D();
    o.position.copy(FOCUS[0]);
    return o;
  }, []);
  useFrame((_, dt) => {
    const l = light.current;
    if (!l) return;
    target.position.lerp(FOCUS[hub.get().section] ?? FOCUS[0], 1 - Math.exp(-dt * 2));
    l.position.copy(target.position).add(LIGHT_OFFSET);
  });
  return (
    <>
      <primitive object={target} />
      <directionalLight ref={light} target={target} castShadow intensity={2.1} position={LIGHT_OFFSET.toArray()}
        shadow-mapSize={[2048, 2048]} shadow-bias={-0.0003} shadow-normalBias={0.025}>
        <orthographicCamera attach="shadow-camera" args={[-15, 15, 15, -15, 1, 60]} />
      </directionalLight>
    </>
  );
}

export default function Scene() {
  tagLayer.current = document.querySelector<HTMLElement>(".scene-layer") ?? document.body;
  screenLayer.current = document.getElementById("screen-layer") ?? tagLayer.current;
  const [rich, setRich] = useState(true);
  const [dpr, setDpr] = useState(() => Math.min(1.75, window.devicePixelRatio || 1));
  return (
    <Canvas
      shadows="percentage"
      dpr={dpr}
      gl={{ antialias: false, powerPreference: "high-performance", stencil: false }}
      camera={{ fov: 42, near: 0.1, far: 160, position: [0, 10, 36] }}
      eventSource={document.getElementById("root") ?? undefined}
      eventPrefix="client"
      onCreated={({ gl }) => { gl.toneMapping = NeutralToneMapping; }}
    >
      <color attach="background" args={[FOG]} />
      <fog attach="fog" args={[FOG, 20, 46]} />
      <PerformanceMonitor onDecline={() => { setRich(false); setDpr(1); }} />
      <hemisphereLight args={["#F7FAFC", "#AFC0CC", 1.15]} />
      <KeyLight />
      <Environment resolution={256} frames={1}>
        <Lightformer form="rect" intensity={2.2} position={[0, 10, 2]} rotation-x={Math.PI / 2} scale={[20, 8, 1]} />
        <Lightformer form="rect" intensity={1.1} position={[-12, 4, 2]} rotation-y={Math.PI / 2} scale={[12, 4, 1]} />
        <Lightformer form="rect" intensity={1.1} position={[12, 4, 2]} rotation-y={-Math.PI / 2} scale={[12, 4, 1]} />
        <Lightformer form="ring" color="#bdeee7" intensity={2} position={[0, 3, -10]} scale={5} />
      </Environment>
      <mesh rotation-x={-Math.PI / 2} position={[0, 0, -26]} receiveShadow>
        <planeGeometry args={[200, 220]} />
        <meshStandardMaterial color="#DDE5EB" roughness={0.95} />
      </mesh>
      <Core />
      <DataCity />
      <Monitor />
      <LogRail />
      <CameraRig />
      {rich ? (
        <EffectComposer multisampling={4}>
          <N8AO halfRes aoRadius={1.2} intensity={2.2} distanceFalloff={0.9} />
          <Bloom mipmapBlur luminanceThreshold={1} intensity={0.55} />
          <Vignette offset={0.35} darkness={0.22} />
        </EffectComposer>
      ) : (
        <EffectComposer multisampling={0}>
          <Bloom mipmapBlur luminanceThreshold={1} intensity={0.5} />
        </EffectComposer>
      )}
    </Canvas>
  );
}
