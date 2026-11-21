import { useEffect, useMemo, useRef } from "react";
import { useFrame, useThree } from "@react-three/fiber";
import { PerspectiveCamera, Vector3 } from "three";
import { SHOTS } from "./layout";
import { prefersReducedMotion, scroll, store } from "../store";

const smooth = (a: number, b: number, x: number) => {
  const t = Math.min(1, Math.max(0, (x - a) / (b - a)));
  return t * t * (3 - 2 * t);
};

/** Scroll picks the shot: the camera holds each one, then glides to the next. */
export function CameraRig() {
  const { camera, pointer, size } = useThree();
  const reduced = useMemo(prefersReducedMotion, []);
  const look = useRef(SHOTS[0][1].clone());
  const shift = useRef({ x: 0, y: 0 });
  const pos = useMemo(() => new Vector3(), []);
  const aim = useMemo(() => new Vector3(), []);

  useEffect(() => {
    camera.position.copy(reduced ? SHOTS[0][0] : new Vector3(0, 16, 34)); // the opening move: down onto the desk
  }, [camera, reduced]);

  useFrame((_, dt) => {
    const last = SHOTS.length - 1;
    const f = Math.min(last, Math.max(0, scroll.progress));
    const i = Math.min(last - 1, Math.floor(f));
    const k = f >= last ? 1 : reduced ? (f - i >= 0.75 ? 1 : 0) : smooth(0.5, 1, f - i);
    pos.lerpVectors(SHOTS[i][0], SHOTS[i + 1][0], k);
    aim.lerpVectors(SHOTS[i][1], SHOTS[i + 1][1], k);
    const aspect = size.width / size.height;
    if (aspect < 1.2) pos.sub(aim).multiplyScalar(1 + (1.2 - aspect) * 0.9).add(aim);
    if (!reduced) {
      pos.x += pointer.x * 0.45;
      pos.y += pointer.y * 0.25;
    }
    const damp = reduced ? 1 : 1 - Math.exp(-dt * 2.4);
    camera.position.lerp(pos, damp);
    look.current.lerp(aim, damp);
    camera.lookAt(look.current);

    // Panels sit on the right, so the subject moves left of them; the hero text sits bottom left, so it moves right.
    const wide = size.width >= 960;
    const hero = store.get().section === 0;
    const sx = wide ? (hero ? 0.24 : -0.19) : 0;
    const sy = wide ? (hero ? 0.04 : 0) : hero ? 0.37 : 0.14;
    shift.current.x += (sx - shift.current.x) * damp;
    shift.current.y += (sy - shift.current.y) * damp;
    (camera as PerspectiveCamera).setViewOffset(
      size.width, size.height, -size.width * shift.current.x, size.height * shift.current.y, size.width, size.height,
    );
  });
  return null;
}
