import { Html } from "@react-three/drei";

/** Name tags live in the fixed 3D layer, so they stay put while the page scrolls and always sit beneath the panels. */
export const tagLayer: { current: HTMLElement } = { current: document.body };

/** Holds the monitor's CSS 3D screen; the camera rig moves it with the off-centre framing. */
export const screenLayer: { current: HTMLElement } = { current: document.body };

/** A small name tag pinned in the 3D world. Only shown while its section is on screen, so it never doubles up with a panel. */
export function Label({ title, sub, visible, position, tone, size = 15 }: {
  title: string; sub?: string; visible: boolean; position: [number, number, number]; tone?: "alert" | "focus"; size?: number;
}) {
  return (
    <Html
      portal={tagLayer}
      position={position}
      center
      distanceFactor={size}
      zIndexRange={[20, 0]}
      style={{ opacity: visible ? 1 : 0, transition: "opacity .5s ease", pointerEvents: "none" }}
    >
      <div className={`scene-label${tone ? ` is-${tone}` : ""}`}>
        <b>{title}</b>
        {sub && <span>{sub}</span>}
      </div>
    </Html>
  );
}
