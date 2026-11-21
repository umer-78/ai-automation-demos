import { useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import { RoundedBox } from "@react-three/drei";
import { Color, Group, Mesh, MeshBasicMaterial, MeshStandardMaterial } from "three";
import { CITY } from "./layout";
import { Label } from "./Label";
import { CHANNELS, pct } from "../api";
import { prefersReducedMotion, useHub } from "../store";

const BODY = new Color("#FBFCFD");
const DIM = new Color("#CDD7DF");
const CAP_OK = new Color("#12968A");
const CAP_DIM = new Color("#A9B9C5");
const STEP_X = 2.8;
const STEP_Z = 2.9;
const PLATE = 0.24;

/** Pulsing ring and light beam over the one tower whose cost per conversion jumped. */
function Beacon({ height }: { height: number }) {
  const ring = useRef<Mesh>(null);
  const reduced = useMemo(prefersReducedMotion, []);
  useFrame(({ clock }) => {
    if (!ring.current) return;
    const t = reduced ? 0.4 : (clock.getElapsedTime() * 0.8) % 1;
    ring.current.scale.setScalar(1 + t * 1.4);
    (ring.current.material as MeshBasicMaterial).opacity = 0.9 * (1 - t);
  });
  return (
    <group position={[0, height + 0.12, 0]}>
      <mesh ref={ring} rotation-x={-Math.PI / 2}>
        <ringGeometry args={[0.95, 1.05, 64]} />
        <meshBasicMaterial color={[2.4, 0.8, 0.45]} transparent toneMapped={false} depthWrite={false} />
      </mesh>
      <mesh position={[0, 0.7, 0]}>
        <cylinderGeometry args={[0.045, 0.045, 1.4, 12]} />
        <meshBasicMaterial color={[2.2, 0.7, 0.4]} transparent opacity={0.45} toneMapped={false} depthWrite={false} />
      </mesh>
    </group>
  );
}

function Tower({ x, z, height, alert, dim, delay }: { x: number; z: number; height: number; alert: boolean; dim: boolean; delay: number }) {
  const grow = useRef<Group>(null);
  const cap = useRef<Mesh>(null);
  const body = useRef<MeshStandardMaterial>(null);
  const capMat = useRef<MeshStandardMaterial>(null);
  const start = useRef(performance.now() + delay);
  const reduced = useMemo(prefersReducedMotion, []);
  useFrame((_, dt) => {
    if (!grow.current || !cap.current || !body.current) return;
    const k = reduced ? 1 : performance.now() < start.current ? 0 : 1 - Math.exp(-dt * 3.5);
    const y = grow.current.scale.y + (height - grow.current.scale.y) * k;
    grow.current.scale.y = Math.max(0.001, y);
    cap.current.position.y = y + 0.05;
    body.current.color.lerp(dim ? DIM : BODY, Math.min(1, dt * 6));
    if (capMat.current && !alert) {
      capMat.current.color.lerp(dim ? CAP_DIM : CAP_OK, Math.min(1, dt * 6));
      capMat.current.emissive.lerp(dim ? CAP_DIM : CAP_OK, Math.min(1, dt * 6));
    }
  });
  return (
    <group position={[x, 0, z]}>
      <group ref={grow} scale={[1, 0.001, 1]}>
        <mesh position={[0, 0.5, 0]} castShadow receiveShadow>
          <boxGeometry args={[1.5, 1, 1.5]} />
          <meshStandardMaterial ref={body} color={BODY} roughness={0.32} />
        </mesh>
      </group>
      <mesh ref={cap} castShadow>
        <boxGeometry args={[1.56, 0.1, 1.56]} />
        <meshStandardMaterial ref={capMat} color={alert ? "#E4572E" : "#12968A"} emissive={alert ? "#E4572E" : "#12968A"}
          emissiveIntensity={alert ? 2.2 : 0.25} toneMapped={!alert} />
      </mesh>
      {alert && <Beacon height={height} />}
    </group>
  );
}

/** One tower per client and channel: height is 30-day spend, an orange cap marks a cost-per-conversion alert. */
export function DataCity() {
  const dash = useHub((s) => s.dashboard);
  const focus = useHub((s) => s.focusClient);
  const labels = useHub((s) => s.section === 2);
  const layout = useMemo(() => {
    if (!dash) return null;
    const clients = dash.by_client;
    const max = Math.max(1, ...dash.matrix.map((m) => m.spend));
    const alerts = new Set(dash.alerts.map((a) => `${a.client_id}|${a.channel}`));
    const towers = clients.flatMap((c, ci) =>
      CHANNELS.map((ch, hi) => {
        const cell = dash.matrix.find((m) => m.client_id === c.client_id && m.channel === ch);
        return {
          id: `${c.client_id}|${ch}`, client: c.client_id,
          x: (ci - (clients.length - 1) / 2) * STEP_X, z: (hi - (CHANNELS.length - 1) / 2) * STEP_Z,
          height: 0.15 + 5.2 * ((cell?.spend ?? 0) / max), alert: alerts.has(`${c.client_id}|${ch}`), delay: (ci * 3 + hi) * 70,
        };
      }),
    );
    const alert = dash.alerts[0] ?? null;
    return { clients, towers, alert, alertTower: alert ? towers.find((t) => t.id === `${alert.client_id}|${alert.channel}`) : undefined };
  }, [dash]);
  if (!layout) return null;
  const w = layout.clients.length * STEP_X + 1.6;
  const d = CHANNELS.length * STEP_Z + 1.4;
  return (
    <group position={CITY}>
      <RoundedBox args={[w, PLATE, d]} radius={0.1} position={[0, PLATE / 2, 0]} receiveShadow castShadow>
        <meshStandardMaterial color="#F3F6F8" roughness={0.65} />
      </RoundedBox>
      <group position={[0, PLATE, 0]}>
        {layout.towers.map(({ id, client, ...t }) => (
          <Tower key={id} {...t} dim={!!focus && focus !== client} />
        ))}
      </group>
      {layout.clients.map((c, ci) => (
        <Label key={c.client_id} title={c.client} visible={labels} tone={focus === c.client_id ? "focus" : undefined} size={19}
          position={[(ci - (layout.clients.length - 1) / 2) * STEP_X, 0.3, d / 2 + 0.7]} />
      ))}
      {CHANNELS.map((ch, hi) => (
        <Label key={ch} title={ch} visible={labels} size={19} position={[w / 2 + 1.1, 0.3, (hi - (CHANNELS.length - 1) / 2) * STEP_Z]} />
      ))}
      {layout.alert && layout.alertTower && (
        <Label title={`Cost per conversion ${pct(layout.alert.change_pct)}`} sub={`${layout.alert.client}, ${layout.alert.channel}`}
          visible={labels} tone="alert" size={19} position={[layout.alertTower.x, PLATE + layout.alertTower.height + 1.7, layout.alertTower.z]} />
      )}
    </group>
  );
}
