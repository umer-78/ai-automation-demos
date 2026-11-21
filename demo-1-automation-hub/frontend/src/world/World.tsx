import { Environment, Lightformer, PerformanceMonitor } from "@react-three/drei";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import clsx from "clsx";
import { Component, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import * as THREE from "three";
import { FLOW_CHIP_Y, FLOW_FLOOR, FlowModel, Post } from "../components/FlowScene";
import { FLOW_NODES, type FlowNodeKey } from "../components/flowNodes";
import type { Alert, AutomationStats, ChannelRow, Cube, LogRow, Overview, SiteDraft, Status } from "../lib/api";
import { count, money, shortDate, timeAgo, workflowName } from "../lib/format";
import { useApi, useOnDataChanged, usePrefersReducedMotion } from "../lib/hooks";
import { SHOTS, ZONES, world, useWorld, type Shot, type Vec3, type Zone } from "./store";
import { ChannelsZone, ClientsZone, RunsZone, SettingsZone, SitesZone, SpendZone } from "./zones";
import {
  SITE_SECTIONS,
  SLAB,
  SOCKETS,
  arcLabelPos,
  barHeight,
  barX,
  channelArcs,
  clientOrder,
  pedestalHeight,
  pedestalPos,
  rowZ,
  runPoint,
  slabY,
  slotTheta,
  socketPos,
  sortedRows,
} from "./layout";

export const WORLD_BG = "#eef0f3";

// ------------------------------------------------------------------ camera director
/** Where the camera is looking and which zone it has reached, shared with the light and the labels. */
export const director = { target: new THREE.Vector3(...SHOTS.home.target), zone: "flow" as Zone, arrived: 1 };
const easeInOut = (k: number) => (k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2);

function CameraDirector({ still }: { still: boolean }) {
  const camera = useThree((s) => s.camera) as THREE.PerspectiveCamera;
  const size = useThree((s) => s.size);
  const invalidate = useThree((s) => s.invalidate);
  const shotName = useWorld((s) => s.shot);
  const focus = useWorld((s) => s.focus);
  const a = useRef({
    init: false,
    start: -1,
    dur: 0.001,
    arc: 0,
    fromPos: new THREE.Vector3(),
    fromTarget: new THREE.Vector3(),
    fromShift: 0,
    toPos: new THREE.Vector3(),
    toTarget: new THREE.Vector3(),
    toShift: 0,
    pos: new THREE.Vector3(),
    target: new THREE.Vector3(),
    shift: 0,
    off: new THREE.Vector3(),
  });
  useEffect(() => {
    const s = a.current;
    const shot: Shot = focus ?? SHOTS[shotName];
    s.toPos.set(...shot.pos);
    s.toTarget.set(...shot.target);
    s.toShift = shot.shift;
    if (!s.init) {
      s.pos.copy(s.toPos);
      s.target.copy(s.toTarget);
      s.shift = s.toShift;
    }
    s.fromPos.copy(s.pos);
    s.fromTarget.copy(s.target);
    s.fromShift = s.shift;
    const d = s.fromPos.distanceTo(s.toPos);
    s.dur = still || !s.init ? 0.001 : THREE.MathUtils.clamp(0.9 + d / 15, 1.1, 2.6);
    s.arc = Math.min(4, d * 0.12);
    s.start = -1;
    s.init = true;
    director.zone = shot.zone;
    invalidate();
  }, [shotName, focus, still, invalidate]);
  useFrame((state) => {
    const s = a.current;
    const t = state.clock.elapsedTime;
    if (s.start < 0) s.start = t;
    const k = Math.min(1, (t - s.start) / s.dur);
    const e = easeInOut(k);
    director.arrived = k;
    s.pos.lerpVectors(s.fromPos, s.toPos, e);
    s.pos.y += Math.sin(Math.PI * e) * s.arc;
    s.target.lerpVectors(s.fromTarget, s.toTarget, e);
    s.shift = s.fromShift + (s.toShift - s.fromShift) * e;
    const aspect = size.width / Math.max(1, size.height);
    s.off.copy(s.pos).sub(s.target).multiplyScalar(Math.max(1, 1.55 / aspect));
    if (!still) {
      s.off.x += Math.sin(t * 0.11) * 0.45 + state.pointer.x * 0.35;
      s.off.y += Math.sin(t * 0.09 + 1) * 0.22 + state.pointer.y * 0.2;
    }
    camera.position.copy(s.target).add(s.off);
    camera.lookAt(s.target);
    const narrow = size.width < 900;
    camera.setViewOffset(size.width, size.height, narrow ? 0 : -s.shift * size.width, narrow ? size.height * 0.14 : 0, size.width, size.height);
    camera.updateProjectionMatrix();
    director.target.copy(s.target);
  }, -1);
  return null;
}

/** The key light follows the camera's subject, so shadows stay sharp wherever the camera goes. */
function KeyLight() {
  const light = useRef<THREE.DirectionalLight>(null);
  const target = useMemo(() => new THREE.Object3D(), []);
  useFrame(() => {
    const c = director.target;
    light.current?.position.set(c.x + 7, 14, c.z + 8);
    target.position.copy(c);
    target.updateMatrixWorld();
  });
  return (
    <>
      <primitive object={target} />
      <directionalLight
        ref={light}
        target={target}
        intensity={2.1}
        castShadow
        shadow-mapSize={[2048, 2048]}
        shadow-bias={-0.0004}
        shadow-normalBias={0.03}
        shadow-radius={9}
        shadow-blurSamples={16}
        shadow-camera-left={-15}
        shadow-camera-right={15}
        shadow-camera-top={15}
        shadow-camera-bottom={-15}
        shadow-camera-near={1}
        shadow-camera-far={60}
      />
    </>
  );
}

// ------------------------------------------------------------------ labels pinned to 3D points
type Anchor = { el: HTMLElement; pos: THREE.Vector3; zone: Zone };
const anchors = new Map<string, Anchor>();
function anchor(id: string, pos: Vec3, zone: Zone) {
  return (el: HTMLElement | null) => {
    if (el) anchors.set(id, { el, pos: new THREE.Vector3(...pos), zone });
    else anchors.delete(id);
  };
}

function AnchorProjector() {
  const camera = useThree((s) => s.camera);
  const size = useThree((s) => s.size);
  const v = useMemo(() => new THREE.Vector3(), []);
  useFrame(() => {
    const zone = director.arrived > 0.72 ? director.zone : null;
    anchors.forEach((a) => {
      v.copy(a.pos).project(camera);
      const on = zone === a.zone && v.z < 1 && Math.abs(v.x) < 1.05 && Math.abs(v.y) < 1.05;
      const tr = `translate3d(${Math.round(((v.x + 1) / 2) * size.width)}px, ${Math.round(((1 - v.y) / 2) * size.height)}px, 0) translate(-50%, -100%)`;
      if (a.el.dataset.at !== tr) {
        a.el.dataset.at = tr;
        a.el.style.transform = tr;
      }
      const op = on ? "1" : "0";
      if (a.el.style.opacity !== op) {
        a.el.style.opacity = op;
        a.el.style.pointerEvents = on ? "auto" : "none";
      }
    });
  });
  return null;
}

const chip = "absolute left-0 top-0 whitespace-nowrap rounded-full border border-black/[0.06] bg-white/92 px-2.5 py-[5px] text-[12px] leading-none text-black shadow-[0_2px_8px_-2px_rgba(0,0,0,0.12)] backdrop-blur transition-opacity duration-300";
const card = "absolute left-0 top-0 min-w-[180px] rounded-xl border border-black/[0.06] bg-white/95 px-3.5 py-2.5 text-[12.5px] leading-snug text-black shadow-[0_12px_30px_-12px_rgba(0,0,0,0.3)] backdrop-blur transition-opacity duration-200";

function Labels({
  overview,
  cube,
  channels,
  alerts,
  logs,
  draft,
  live,
}: {
  overview: Overview | null;
  cube: Cube | null;
  channels: ChannelRow[] | null;
  alerts: Alert[] | null;
  logs: LogRow[] | null;
  draft: SiteDraft | null;
  live: Record<string, boolean>;
}) {
  const step = useWorld((s) => s.step);
  const hoveredStep = useWorld((s) => s.hoveredStep);
  const hoverBar = useWorld((s) => s.hoverBar);
  const focusClient = useWorld((s) => s.focusClient);
  const rows = sortedRows(cube);
  const arcs = channelArcs(channels ?? []);
  const clients = clientOrder(overview?.clients ?? null);
  const maxSpend = Math.max(1, ...clients.map((c) => c.spend));
  const hb = hoverBar && rows[hoverBar.row] ? { row: rows[hoverBar.row], day: rows[hoverBar.row].days[hoverBar.day], date: cube?.dates[hoverBar.day] } : null;
  const alertRow = alerts?.length ? rows.findIndex((r) => r.client_id === alerts[0].client_id) : -1;
  const alertSpot = (() => {
    if (alertRow < 0 || !alerts || !cube) return null;
    const days = cube.dates.flatMap((d, i) => (d >= alerts[0].week.start && d <= alerts[0].week.end ? [i] : []));
    if (!days.length) return null;
    const mid = days.reduce((a, b) => a + b, 0) / days.length;
    const top = Math.max(...days.map((i) => barHeight(rows[alertRow].days[i]?.spend ?? 0, cube.max_spend)));
    return [barX(mid), top + 0.45, rowZ(alertRow)] as Vec3;
  })();
  return (
    <>
      {(Object.keys(FLOW_NODES) as FlowNodeKey[]).map((k) => {
        const on = step === k;
        const open = on || hoveredStep === k;
        return (
          <button
            key={`flow-${k}`}
            type="button"
            tabIndex={-1}
            ref={anchor(`flow-${k}`, [FLOW_FLOOR[k][0], FLOW_CHIP_Y, FLOW_FLOOR[k][1]], "flow")}
            onPointerEnter={() => world.set({ hoveredStep: k })}
            onPointerLeave={() => world.set({ hoveredStep: null })}
            onClick={() => world.set({ step: on ? null : k })}
            className={clsx(chip, on && "!border-black !bg-black !text-white")}
          >
            <span className="font-semibold">{FLOW_NODES[k].label}</span>
            {open && <span className={on ? "text-white/70" : "text-[#5B616B]"}> {FLOW_NODES[k].sub}</span>}
          </button>
        );
      })}

      {rows.map((r, ri) => (
        <div key={`row-${r.client_id}`} ref={anchor(`row-${r.client_id}`, [barX(0) - 0.55, 0.62, rowZ(ri)], "spend")} className={clsx(chip, "!translate-x-0")} style={{ marginLeft: -8 }}>
          <span className="font-semibold">{r.client}</span>
        </div>
      ))}
      {alertSpot && alerts && (
        <div ref={anchor("alert", alertSpot, "spend")} className={clsx(chip, "!border-[#e5484d]/30 !bg-[#fef3f2] !text-[#b42318]")}>
          <span className="font-semibold">Cost alert</span> {alerts[0].channel} {alerts[0].change != null ? `+${Math.round(alerts[0].change * 100)}%` : ""}
        </div>
      )}
      {hb && hb.day && cube && hoverBar && (
        <div ref={anchor("bar-tip", [barX(hoverBar.day), barHeight(hb.day.spend, cube.max_spend) + 0.25, rowZ(hoverBar.row)], "spend")} className={card}>
          <div className="font-semibold">{hb.row.client}</div>
          <div className="text-[#5B616B]">{hb.date ? shortDate(hb.date) : ""}</div>
          <div className="mt-1 flex justify-between gap-4">
            <span>Spend</span>
            <span className="font-medium">{money(hb.day.spend)}</span>
          </div>
          <div className="flex justify-between gap-4">
            <span>Conversions</span>
            <span className="font-medium">{count(hb.day.conversions)}</span>
          </div>
          <div className="flex justify-between gap-4">
            <span>Per conversion</span>
            <span className="font-medium">{money(hb.day.cpa, true)}</span>
          </div>
        </div>
      )}

      {arcs.map((a) => {
        const c = channels?.[a.i];
        if (!c) return null;
        return (
          <div key={`arc-${a.name}`} ref={anchor(`arc-${a.name}`, arcLabelPos(a.mid, a.h), "channels")} className={card}>
            <div className="flex items-baseline justify-between gap-4">
              <span className="font-semibold">{a.name}</span>
              <span className="font-semibold">{Math.round(a.share * 100)}%</span>
            </div>
            <div className="text-[#5B616B]">
              {money(c.spend)}, {money(c.cpa, true)} per conversion
            </div>
          </div>
        );
      })}

      {clients.map((c, i) => {
        const [x, , z] = pedestalPos(i, clients.length);
        const H = pedestalHeight(c.spend, maxSpend);
        const on = focusClient === c.client_id;
        return (
          <button
            key={`client-${c.client_id}`}
            type="button"
            tabIndex={-1}
            onClick={() => world.set({ focusClient: c.client_id })}
            ref={anchor(`client-${c.client_id}`, [x, H + 0.32, z], "clients")}
            className={clsx(card, "text-left", on && "!border-black")}
          >
            <div className="flex items-center gap-1.5 font-semibold">
              {c.client}
              {c.alerts > 0 && <span aria-label="Open alert" className="inline-block size-1.5 rounded-full bg-[#e5484d]" />}
            </div>
            <div className="text-[#5B616B]">
              {money(c.spend)}, {money(c.cpa, true)} per conv.
            </div>
          </button>
        );
      })}

      {(logs ?? []).slice(0, 1).map((l) => (
        <div key={`run-${l.id}`} ref={anchor(`run-${l.id}`, runPoint(slotTheta(0, Math.min(14, logs?.length ?? 1)), 0.55), "runs")} className={card}>
          <div className="flex items-center gap-1.5 font-semibold">
            <span className={clsx("inline-block size-1.5 rounded-full", l.status === "success" ? "bg-[#0f9f88]" : "bg-[#e5484d]")} />
            {workflowName[l.workflow] ?? l.workflow}
          </div>
          <div className="text-[#5B616B]">
            Latest run, {l.status === "success" ? "worked" : "failed"} {timeAgo(l.created_at)}
          </div>
        </div>
      ))}

      {draft &&
        SITE_SECTIONS.map((k, i) => {
          const rot = 0.32;
          const lx = SLAB.w / 2 + 0.25;
          const pos: Vec3 = [ZONES.sites[0] + Math.cos(rot) * lx, slabY(i) + 0.08, ZONES.sites[2] - Math.sin(rot) * lx];
          return (
            <div key={`slab-${k}`} ref={anchor(`slab-${k}`, pos, "sites")} className={clsx(chip, "!translate-x-0")}>
              <span className="font-semibold">{{ hero: "Hero", services: "Services", proof: "Proof", cta: "Call to action" }[k]}</span>
            </div>
          );
        })}

      {SOCKETS.map((k, i) => {
        const [x, y, z] = socketPos(i);
        return (
          <div key={`socket-${k}`} ref={anchor(`socket-${k}`, [x, y + 0.55, z], "settings")} className={chip}>
            <span className="font-semibold">{SOCKET_NAMES[k]}</span> <span className={live[k] ? "text-[#0b7d6b]" : "text-[#9a6b00]"}>{live[k] ? "live" : k === "google" || k === "meta" ? "off" : "demo"}</span>
          </div>
        );
      })}
    </>
  );
}
export const SOCKET_NAMES: Record<(typeof SOCKETS)[number], string> = {
  google: "Google",
  meta: "Meta Ads",
  ai: "Claude AI",
  airtable: "Airtable",
  slack: "Slack",
  email: "Email",
  database: "Database",
  storage: "Storage",
  make: "Make",
};

class GlBoundary extends Component<{ fallback: ReactNode; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

/** The one 3D world every page sits on. Pages move the camera; the world shows the live data. */
export default function World() {
  const still = usePrefersReducedMotion();
  const [dpr, setDpr] = useState<number | [number, number]>([1, 1.75]);
  const clientId = useWorld((s) => s.clientId);
  const draftId = useWorld((s) => s.draftId);
  const only = clientId ? `&client_id=${clientId}` : "";
  const overview = useApi<Overview>("/api/metrics/overview?days=30", 30000);
  const cube = useApi<Cube>(`/api/metrics/cube?days=30&by=client${only}`, 60000);
  const channels = useApi<{ channels: ChannelRow[] }>(`/api/metrics/channels?days=30${only}`, 60000);
  const alerts = useApi<{ alerts: Alert[] }>("/api/metrics/alerts", 60000);
  const logs = useApi<LogRow[]>("/api/automation/logs?limit=14", 6000);
  const stats = useApi<AutomationStats>("/api/automation/stats?days=7", 15000);
  const sites = useApi<SiteDraft[]>("/api/sites", 30000);
  const status = useApi<Status>("/api/status", 30000);
  const reloaders = [overview.reload, cube.reload, channels.reload, alerts.reload, logs.reload, stats.reload, sites.reload, status.reload];
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const refresh = useCallback(() => reloaders.forEach((r) => void r()), reloaders);
  useOnDataChanged(refresh);

  const step = useWorld((s) => s.step);
  const hoveredStep = useWorld((s) => s.hoveredStep);
  const signal = useWorld((s) => s.signal);
  const st = stats.data;
  const failureRate = st && st.success + st.failure ? Math.min(0.3, st.failure / (st.success + st.failure)) : 0.08;
  const live = useMemo(() => {
    const ints = status.data?.integrations ?? {};
    const out: Record<string, boolean> = {};
    for (const k of SOCKETS) {
      const v = ints[k] ?? "";
      out[k] = v === "live" || v.startsWith("live") || v.startsWith("supabase") || v === "postgres";
    }
    return out;
  }, [status.data]);
  const draft = sites.data?.find((d) => d.group_id === draftId) ?? sites.data?.[0] ?? null;

  useEffect(() => () => void (document.body.style.cursor = ""), []);

  const fallback = <div className="grid h-full place-items-center text-[14px] text-[#5B616B]">The 3D world needs WebGL. All figures are still on the page.</div>;
  return (
    <div aria-hidden="true" className="fixed inset-0 z-0" style={{ background: WORLD_BG }}>
      <GlBoundary fallback={fallback}>
        <Canvas
          shadows="variance"
          dpr={dpr}
          frameloop={still ? "demand" : "always"}
          camera={{ fov: 32, near: 0.3, far: 220, position: SHOTS.home.pos }}
          gl={{ antialias: false, alpha: false, powerPreference: "high-performance" }}
          onCreated={({ gl }) => {
            gl.toneMapping = THREE.NeutralToneMapping;
            gl.toneMappingExposure = 1.04;
          }}
          onPointerMissed={() => world.set({ hoverBar: null })}
        >
          <color attach="background" args={[WORLD_BG]} />
          <fog attach="fog" args={[WORLD_BG, 34, 88]} />
          <Environment resolution={256} frames={1}>
            <color attach="background" args={["#121317"]} />
            <Lightformer form="rect" intensity={2.3} position={[0, 7, 0.5]} rotation-x={Math.PI / 2} scale={[12, 6, 1]} />
            <Lightformer form="rect" intensity={2.6} position={[-7.5, 2.6, 3]} rotation-y={Math.PI / 2.3} scale={[8, 1.2, 1]} />
            <Lightformer form="rect" intensity={1.8} position={[7.5, 2.2, -2.5]} rotation-y={-Math.PI / 2.5} scale={[8, 1, 1]} />
            <Lightformer form="rect" intensity={1.3} position={[0, 1.8, 10]} scale={[16, 2, 1]} />
          </Environment>
          <hemisphereLight args={["#ffffff", "#dfe3ea", 0.45]} />
          <KeyLight />
          <mesh rotation-x={-Math.PI / 2} receiveShadow>
            <planeGeometry args={[420, 420]} />
            <meshStandardMaterial color="#f6f7f9" roughness={0.94} />
          </mesh>
          <CameraDirector still={still} />
          <AnchorProjector />
          <FlowModel
            failureRate={failureRate}
            still={still}
            signal={signal}
            selected={step}
            hovered={hoveredStep}
            onHover={(k) => world.set({ hoveredStep: k })}
            onSelect={(k) => world.set({ step: world.get().step === k ? null : k })}
          />
          <SpendZone cube={cube.data} alerts={alerts.data?.alerts ?? null} still={still} />
          <ChannelsZone channels={channels.data?.channels ?? null} still={still} />
          <ClientsZone clients={overview.data?.clients ?? null} still={still} />
          <RunsZone logs={logs.data} still={still} />
          <SitesZone draft={draft} still={still} />
          <SettingsZone live={live} />
          <Post />
          {!still && <PerformanceMonitor onDecline={() => setDpr(1)} />}
        </Canvas>
      </GlBoundary>
      <div className="pointer-events-none absolute inset-0 overflow-hidden">
        <Labels
          overview={overview.data}
          cube={cube.data}
          channels={channels.data?.channels ?? null}
          alerts={alerts.data?.alerts ?? null}
          logs={logs.data}
          draft={draft}
          live={live}
        />
      </div>
    </div>
  );
}
