import { useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo } from "react";
import * as THREE from "three";
import { RoundedBoxGeometry } from "three/examples/jsm/geometries/RoundedBoxGeometry.js";
import { EffectComposer } from "three/examples/jsm/postprocessing/EffectComposer.js";
import { OutputPass } from "three/examples/jsm/postprocessing/OutputPass.js";
import { RenderPass } from "three/examples/jsm/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/examples/jsm/postprocessing/UnrealBloomPass.js";

/** The studio kit every zone is built from: ceramic, glass, brushed metal and two signal colours. */
export const AMBER = "#f5a524";
export const TEAL = "#0f9f88";
export const RED = "#e5484d";
export const COBALT = "#2f5bff";

export const mats = {
  ceramic: new THREE.MeshPhysicalMaterial({ color: "#fafafa", roughness: 0.36, clearcoat: 0.45, clearcoatRoughness: 0.3 }),
  white: new THREE.MeshPhysicalMaterial({ color: "#fbfbfc", roughness: 0.34, clearcoat: 0.7, clearcoatRoughness: 0.2 }),
  grey: new THREE.MeshPhysicalMaterial({ color: "#c9ccd3", roughness: 0.4, clearcoat: 0.4 }),
  graphite: new THREE.MeshPhysicalMaterial({ color: "#353a42", roughness: 0.45, clearcoat: 0.6, clearcoatRoughness: 0.25 }),
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
  amber: new THREE.MeshPhysicalMaterial({ color: AMBER, roughness: 0.3, clearcoat: 0.9, clearcoatRoughness: 0.14 }),
  teal: new THREE.MeshPhysicalMaterial({ color: TEAL, roughness: 0.3, clearcoat: 0.9, clearcoatRoughness: 0.14 }),
  red: new THREE.MeshPhysicalMaterial({ color: RED, roughness: 0.3, clearcoat: 0.9, clearcoatRoughness: 0.14 }),
  ledAmber: new THREE.MeshStandardMaterial({ color: AMBER, emissive: "#ffb340", emissiveIntensity: 2.2 }),
  ledTeal: new THREE.MeshStandardMaterial({ color: TEAL, emissive: "#2dd4bf", emissiveIntensity: 2.2 }),
  ledRed: new THREE.MeshStandardMaterial({ color: RED, emissive: "#ff5a5f", emissiveIntensity: 2.2 }),
  ledOff: new THREE.MeshStandardMaterial({ color: "#b9bec7", roughness: 0.4 }),
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

/** Faint bloom on the lit parts and neutral tone mapping, rendered at the canvas size. */
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

/** Text painted onto a canvas, for paper sheets standing in the world. */
export function paperTexture(lines: { text: string; size: number; weight?: number; color?: string; gap?: number }[], w = 1024, h = 1325) {
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const g = canvas.getContext("2d")!;
  g.fillStyle = "#ffffff";
  g.fillRect(0, 0, w, h);
  let y = 96;
  const pad = 88;
  for (const line of lines) {
    g.font = `${line.weight ?? 400} ${line.size}px "Geist Variable", system-ui, sans-serif`;
    g.fillStyle = line.color ?? "#1d2025";
    const words = line.text.split(" ");
    let row = "";
    for (const word of words) {
      const next = row ? `${row} ${word}` : word;
      if (g.measureText(next).width > w - pad * 2 && row) {
        g.fillText(row, pad, y);
        y += line.size * 1.32;
        row = word;
      } else row = next;
    }
    if (row) g.fillText(row, pad, y);
    y += line.size * 1.32 + (line.gap ?? line.size * 0.5);
    if (y > h - 60) break;
  }
  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 8;
  return tex;
}
