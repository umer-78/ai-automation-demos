import * as THREE from "three";

/** Small canvas-drawn textures shared by the 3D scenes. No image files and no network requests. */
const cache = new Map<string, THREE.CanvasTexture>();

function paint(key: string, w: number, h: number, draw: (ctx: CanvasRenderingContext2D) => void) {
  const hit = cache.get(key);
  if (hit) return hit;
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d");
  if (ctx) draw(ctx);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = 4;
  cache.set(key, texture);
  return texture;
}

/** Soft white disc that fades to nothing. Tint it with the material colour. */
export const glowTexture = () =>
  paint("glow", 128, 128, (ctx) => {
    const g = ctx.createRadialGradient(64, 64, 0, 64, 64, 64);
    g.addColorStop(0, "rgba(255,255,255,1)");
    g.addColorStop(0.22, "rgba(255,255,255,0.6)");
    g.addColorStop(0.55, "rgba(255,255,255,0.14)");
    g.addColorStop(1, "rgba(255,255,255,0)");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, 128, 128);
  });

/**
 * Radar sweep. On the canvas the bright edge sits at angle 0 and the trail runs anticlockwise,
 * which becomes "behind the edge" once the plane is laid flat and the sweep turns clockwise.
 */
export const sweepTexture = (trail: number) =>
  paint(`sweep-${trail}`, 512, 512, (ctx) => {
    const c = 256;
    const steps = 120;
    for (let i = 0; i < steps; i++) {
      const k = 1 - i / steps;
      ctx.beginPath();
      ctx.moveTo(c, c);
      ctx.arc(c, c, c, -(trail * (i + 1)) / steps, -(trail * i) / steps + 0.003);
      ctx.closePath();
      ctx.fillStyle = `rgba(255,255,255,${(0.5 * k * k * k).toFixed(4)})`;
      ctx.fill();
    }
    ctx.strokeStyle = "rgba(255,255,255,0.95)";
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.moveTo(c, c);
    ctx.lineTo(2 * c, c);
    ctx.stroke();
    // fade the middle so the sweep does not pile up into a bright blob at the centre
    ctx.globalCompositeOperation = "destination-in";
    const mask = ctx.createRadialGradient(c, c, 0, c, c, c);
    mask.addColorStop(0, "rgba(0,0,0,0.15)");
    mask.addColorStop(0.3, "rgba(0,0,0,1)");
    mask.addColorStop(0.985, "rgba(0,0,0,1)");
    mask.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = mask;
    ctx.fillRect(0, 0, 512, 512);
  });

/** Console face: deep spruce with a lit centre, faint spokes every 15 degrees and a fine dot grain. */
export const surfaceTexture = () =>
  paint("surface", 1024, 1024, (ctx) => {
    const c = 512;
    const g = ctx.createRadialGradient(c, c, 0, c, c, c);
    g.addColorStop(0, "#245f55");
    g.addColorStop(0.45, "#17483f");
    g.addColorStop(0.9, "#0f3a33");
    g.addColorStop(1, "#0b2f29");
    ctx.fillStyle = g;
    ctx.beginPath();
    ctx.arc(c, c, c, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = "rgba(143,184,168,0.07)";
    ctx.lineWidth = 1.5;
    for (let i = 0; i < 24; i++) {
      const a = (i / 24) * Math.PI * 2;
      ctx.beginPath();
      ctx.moveTo(c + Math.cos(a) * 60, c + Math.sin(a) * 60);
      ctx.lineTo(c + Math.cos(a) * c, c + Math.sin(a) * c);
      ctx.stroke();
    }
    ctx.fillStyle = "rgba(207,224,216,0.05)";
    for (let y = 8; y < 1024; y += 16) {
      for (let x = 8; x < 1024; x += 16) {
        if ((x - c) ** 2 + (y - c) ** 2 < c * c) ctx.fillRect(x, y, 2, 2);
      }
    }
  });

/** A text label as a texture. Returns the texture and its width / height ratio for sprite sizing. */
export function labelTexture(text: string, color = "#8fb8a8", weight = 700) {
  const key = `label-${text}-${color}-${weight}`;
  let ratio = 1;
  const font = `${weight} 64px "Schibsted Grotesk Variable", system-ui, sans-serif`;
  const probe = document.createElement("canvas").getContext("2d");
  if (probe) {
    probe.font = font;
    ratio = (probe.measureText(text).width + 24) / 84;
  }
  const w = Math.max(32, Math.ceil(84 * ratio));
  const texture = paint(key, w, 84, (ctx) => {
    ctx.font = font;
    ctx.fillStyle = color;
    ctx.textBaseline = "middle";
    ctx.fillText(text, 12, 44);
  });
  return { texture, ratio: w / 84 };
}
