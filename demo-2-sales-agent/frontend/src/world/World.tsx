import { Environment, Lightformer, PerformanceMonitor } from "@react-three/drei";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { Component, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import * as THREE from "three";
import { QUADRANTS } from "../components/radarMeta";
import { STATIONS, flowSteps, gateNote, stationIndexOf, stationNotes, type StationKey } from "../components/flowMeta";
import type { Account, Learning, Overview, Report } from "../lib/api";
import { FLAG_LABEL, moneyK } from "../lib/format";
import { useApi, useOnDataChanged, usePrefersReducedMotion } from "../lib/hooks";
import { useRun } from "../lib/run";
import { accountTop, leadTop, SOCKETS, socketPos, stationTop, gateTop, stationU, TRAYS, trayTop, type TrayKey } from "./layout";
import { SHOTS, world, useWorld, type Shot, type Vec3, type Zone } from "./store";
import { Post } from "./studio";
import { AgentZone, CrmZone, LearningZone, QueueZone, RadarZone, ReportZone, SettingsZone, quadrantLabelPos, type StationState } from "./zones";

export const WORLD_BG = "#eef0f3";

// ------------------------------------------------------------------ camera director
export const director = { target: new THREE.Vector3(...SHOTS.home.target), zone: "radar" as Zone, arrived: 1 };
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
const card = "absolute left-0 top-0 w-[260px] rounded-xl border border-black/[0.06] bg-white/95 px-3.5 py-2.5 text-[12.5px] leading-snug text-black shadow-[0_12px_30px_-12px_rgba(0,0,0,0.3)] backdrop-blur transition-opacity duration-200";
const TRAY_LABEL: Record<TrayKey, string> = { pending: "Waiting for you", approved: "Ready to send", rejected: "Rejected", sent: "Sent" };
const SOCKET_NAME: Record<(typeof SOCKETS)[number], string> = { company: "Your company", ai: "Claude AI", research: "Web research", crm: "HubSpot", slack: "Slack", database: "Database" };

function Labels({ overview, accounts, notes, states, live, counts }: {
  overview: Overview | null;
  accounts: Account[] | null;
  notes: Record<StationKey, string>;
  states: Record<StationKey, StationState>;
  live: Record<string, boolean>;
  counts: Record<TrayKey, number>;
}) {
  const hoverLead = useWorld((s) => s.hoverLead);
  const selLead = useWorld((s) => s.lead);
  const hoverAccount = useWorld((s) => s.hoverAccount);
  const leads = overview?.radar ?? [];
  const lead = leads.find((l) => l.id === (hoverLead ?? selLead)) ?? null;
  const hot = leads.filter((l) => l.status !== "excluded" && l.score >= 75).slice(0, 5);
  const accIndex = accounts?.findIndex((a) => a.id === hoverAccount) ?? -1;
  const acc = accIndex >= 0 ? accounts![accIndex] : null;
  const maxValue = Math.max(1, ...(accounts ?? []).map((a) => a.deal_value ?? a.arr ?? 0));
  return (
    <>
      {QUADRANTS.map((q, i) => (
        <div key={q.key} ref={anchor(`q-${q.key}`, quadrantLabelPos(i), "radar")} className={`${chip} !bg-transparent !shadow-none !border-transparent text-[12.5px] font-medium text-[#5B616B]`}>
          {q.label}
        </div>
      ))}
      {hot
        .filter((l) => l.id !== lead?.id)
        .map((l) => (
          <div key={l.id} ref={anchor(`hot-${l.id}`, leadTop(l), "radar")} className={chip}>
            <span className="num font-semibold">{l.score}</span> {l.company}
          </div>
        ))}
      {lead && (
        <div key={`lead-${lead.id}`} ref={anchor(`lead-${lead.id}`, leadTop(lead), "radar")} className={card}>
          <div className="flex items-baseline justify-between gap-2">
            <span className="font-semibold">{lead.company}</span>
            <span className="num font-semibold">{lead.score}</span>
          </div>
          <p className="mt-1 text-[#3f444c]">{lead.fact ?? lead.reason}</p>
        </div>
      )}
      {STATIONS.map((s) => (
        <div key={s.key} ref={anchor(`st-${s.key}`, stationTop(s.key), "agent")} className={chip}>
          <span className="font-medium">{s.label}</span>{" "}
          <span className={states[s.key] === "refused" ? "text-[#B42318]" : states[s.key] === "active" ? "text-[#9a6b00]" : "text-[#5B616B]"}>{notes[s.key]}</span>
        </div>
      ))}
      <div ref={anchor("gate", gateTop(), "agent")} className={chip}>
        <span className="font-medium">Your approval</span> <span className="text-[#5B616B]">{gateNote(overview?.counts)}</span>
      </div>
      {TRAYS.map((k) => (
        <div key={k} ref={anchor(`tray-${k}`, trayTop(k, counts[k]), "queue")} className={chip}>
          <span className="font-medium">{TRAY_LABEL[k]}</span> <span className="num text-[#5B616B]">{counts[k]}</span>
        </div>
      ))}
      {acc && (
        <div key={`acc-${acc.id}`} ref={anchor(`acc-${acc.id}`, accountTop(accIndex, 0.22 + Math.sqrt((acc.deal_value ?? acc.arr ?? 0) / maxValue) * 2.3), "crm")} className={card}>
          <div className="flex items-baseline justify-between gap-2">
            <span className="font-semibold">{acc.company}</span>
            <span className="num font-semibold">{acc.score ?? ""}</span>
          </div>
          <p className="text-[#5B616B]">
            {acc.stage}, {acc.deal_value || acc.arr ? moneyK(acc.deal_value ?? acc.arr) : "no value logged"}, {acc.owner}
          </p>
          {(acc.flags ?? []).map((f) => (
            <p key={f} className="mt-1 text-[#3f444c]">
              <span className="font-medium">{FLAG_LABEL[f] ?? f}:</span> {acc.flag_reasons?.[f]}
            </p>
          ))}
        </div>
      )}
      {SOCKETS.map((k, i) => {
        const [x, , z] = socketPos(i);
        return (
          <div key={k} ref={anchor(`sock-${k}`, [x, 0.75, z], "settings")} className={chip}>
            <span className="font-semibold">{SOCKET_NAME[k]}</span> <span className={live[k] ? "text-[#0b7d6b]" : "text-[#9a6b00]"}>{live[k] ? "live" : k === "company" ? "sample" : "demo"}</span>
          </div>
        );
      })}
    </>
  );
}

class GlBoundary extends Component<{ fallback: ReactNode; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

/** Opens the page for a lead or account clicked in the world. */
function useWorldClicks() {
  const navigate = useNavigate();
  const lead = useWorld((s) => s.lead);
  const account = useWorld((s) => s.account);
  useEffect(() => {
    if (lead !== null && !location.pathname.startsWith("/leads")) navigate(`/leads?lead=${lead}`);
  }, [lead, navigate]);
  useEffect(() => {
    if (account !== null && !location.pathname.startsWith("/accounts")) navigate(`/accounts?account=${account}`);
  }, [account, navigate]);
}

/** The one 3D world every page sits on. Pages move the camera; the world shows the live data. */
export default function World() {
  const still = usePrefersReducedMotion();
  const [dpr, setDpr] = useState<number | [number, number]>([1, 1.75]);
  const { run, busy } = useRun();
  const overview = useApi<Overview>("/api/overview", busy ? 4000 : 20000);
  const accounts = useApi<Account[]>("/api/accounts", 60000);
  const learning = useApi<Learning>("/api/learning", 60000);
  const report = useApi<Report>("/api/report/weekly", 60000);
  const health = useApi<{ integrations: Record<string, string> }>("/api/health", 30000);
  const reloaders = [overview.reload, accounts.reload, learning.reload, report.reload, health.reload];
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const refresh = useCallback(() => reloaders.forEach((r) => void r()), reloaders);
  useOnDataChanged(refresh);
  useWorldClicks();

  const flag = useWorld((s) => s.flag);
  const shown = busy && run ? run : overview.data?.latest_run ?? null;
  const steps = useMemo(() => flowSteps(shown), [shown]);
  const notes = useMemo(() => stationNotes(steps, shown, overview.data?.counts.accounts), [steps, shown, overview.data]);
  const { states, progress } = useMemo(() => {
    const out = Object.fromEntries(STATIONS.map((s) => [s.key, "idle"])) as Record<StationKey, StationState>;
    let last = -1;
    for (const st of steps) {
      const i = stationIndexOf(st.tool);
      if (i < 0) continue;
      const k = STATIONS[i].key;
      if (!st.ok) out[k] = "refused";
      else if (out[k] !== "refused") out[k] = "done";
      last = Math.max(last, i);
    }
    if (busy && last >= 0 && out[STATIONS[last].key] !== "refused") out[STATIONS[last].key] = "active";
    const finished = shown && shown.status !== "running";
    return { states: out, progress: finished && steps.length ? 1 : last >= 0 ? stationU(last) : 0 };
  }, [steps, busy, shown]);
  const c = overview.data?.counts;
  const counts: Record<TrayKey, number> = { pending: c?.pending_drafts ?? 0, approved: c?.approved_drafts ?? 0, rejected: c?.rejected_drafts ?? 0, sent: c?.sent_drafts ?? 0 };
  const live = useMemo(() => {
    const ints = health.data?.integrations ?? {};
    return {
      company: false,
      ai: (ints.ai ?? "").startsWith("live"),
      research: ints.research === "Tavily web search",
      crm: (ints.crm ?? "").startsWith("live"),
      slack: (ints.slack ?? "").startsWith("live"),
      database: (ints.database ?? "").includes("Postgres"),
    } as Record<string, boolean>;
  }, [health.data]);

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
          onPointerMissed={() => world.set({ hoverLead: null, hoverAccount: null })}
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
          <RadarZone leads={overview.data?.radar ?? null} scanning={busy} still={still} />
          <AgentZone states={states} progress={progress} running={busy} pending={counts.pending} still={still} />
          <QueueZone counts={counts} still={still} />
          <CrmZone accounts={accounts.data} flag={flag} still={still} />
          <LearningZone learning={learning.data} />
          <ReportZone report={report.data} />
          <SettingsZone live={live} />
          <Post />
          {!still && <PerformanceMonitor onDecline={() => setDpr(1)} />}
        </Canvas>
      </GlBoundary>
      <div className="pointer-events-none absolute inset-0 overflow-hidden">
        <Labels overview={overview.data} accounts={accounts.data} notes={notes} states={states} live={live} counts={counts} />
      </div>
    </div>
  );
}
