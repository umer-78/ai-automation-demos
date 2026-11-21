import { useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import { RoundedBox } from "@react-three/drei";
import { Color, Group, Mesh, MeshStandardMaterial } from "three";
import { CRM_LANES, LEAD_ARC, LETTERS, onTable, TABLE_R } from "./layout";
import { Label } from "./Label";
import { prefersReducedMotion, store, useAgent } from "../store";

const BRASS = { color: "#C9A15A", metalness: 1, roughness: 0.28 };
const STAGES = ["Prospecting", "Proposal", "Negotiation", "Customer"];

/** The round desk with its brass rim, on a dark floor. */
export function Table() {
  return (
    <group>
      <mesh position={[0, 0.15, 0]} receiveShadow castShadow>
        <cylinderGeometry args={[TABLE_R, TABLE_R, 0.3, 128]} />
        <meshStandardMaterial color="#1B3F37" roughness={0.9} />
      </mesh>
      <mesh position={[0, 0.3, 0]} rotation-x={-Math.PI / 2}>
        <torusGeometry args={[TABLE_R, 0.09, 16, 192]} />
        <meshStandardMaterial {...BRASS} />
      </mesh>
      {[3.3, 6.6].map((r) => (
        <mesh key={r} position={[0, 0.305, 0]} rotation-x={-Math.PI / 2}>
          <ringGeometry args={[r - 0.015, r + 0.015, 160]} />
          <meshBasicMaterial color="#2F5A50" />
        </mesh>
      ))}
    </group>
  );
}

function Pin({ x, z, height, drafted, focus, delay }: { x: number; z: number; height: number; drafted: boolean; focus: boolean; delay: number }) {
  const g = useRef<Group>(null);
  const head = useRef<MeshStandardMaterial>(null);
  const born = useRef(performance.now() + delay);
  const reduced = useMemo(prefersReducedMotion, []);
  const color = useMemo(() => new Color(drafted ? "#E3B04B" : "#8CCBF2"), [drafted]);
  useFrame((_, dt) => {
    if (!g.current || !head.current) return;
    const k = reduced ? 1 : performance.now() < born.current ? 0 : 1 - Math.exp(-dt * 4);
    g.current.scale.y += (1 - g.current.scale.y) * k;
    head.current.emissiveIntensity += ((focus ? 3.2 : 1.1) - head.current.emissiveIntensity) * 0.15;
  });
  return (
    <group position={[x, 0.3, z]}>
      <group ref={g} scale={[1, 0.001, 1]}>
        <mesh position={[0, height / 2, 0]} castShadow>
          <cylinderGeometry args={[0.04, 0.04, height, 8]} />
          <meshStandardMaterial {...BRASS} />
        </mesh>
        <mesh position={[0, height, 0]} castShadow>
          <sphereGeometry args={[0.14, 24, 24]} />
          <meshStandardMaterial ref={head} color={color} emissive={color} emissiveIntensity={1.1} toneMapped={false} />
        </mesh>
      </group>
      <mesh position={[0, 0.01, 0]} rotation-x={-Math.PI / 2}>
        <ringGeometry args={[0.16, 0.24, 32]} />
        <meshBasicMaterial color={drafted ? "#6E5A2E" : "#2F5A50"} />
      </mesh>
    </group>
  );
}

/** Leads as pins behind the agent: height is the 0-100 score, brass means a draft is written.
 *  The best score stands in the middle of the arc, the rest alternate outwards. */
export function LeadPins() {
  const leads = useAgent((s) => s.leads);
  const focus = useAgent((s) => s.focusLead);
  const show = useAgent((s) => s.section === 2);
  const pins = useMemo(() => {
    const list = [...leads].sort((a, b) => b.score - a.score || a.id - b.id).slice(0, 16);
    const slots = list.length;
    return list.map((l, rank) => {
      const side = rank === 0 ? 0 : (rank % 2 ? -1 : 1) * Math.ceil(rank / 2);
      const t = slots <= 1 ? 0.5 : 0.5 + side / (slots + 1);
      const p = onTable(LEAD_ARC.from + t * (LEAD_ARC.to - LEAD_ARC.from), LEAD_ARC.r + (rank % 2) * LEAD_ARC.row, 0);
      return { lead: l, rank, x: p.x, z: p.z, height: 0.35 + (l.score / 100) * 2.2, delay: rank * 60 };
    });
  }, [leads]);
  return (
    <group>
      {pins.map(({ lead, rank: _rank, ...p }) => (
        <Pin key={lead.id} {...p} drafted={!!lead.draft_status && lead.draft_status !== "rejected"} focus={focus === lead.id} />
      ))}
      {pins.filter((p) => p.rank < 3 || p.lead.id === focus).map(({ lead, x, z, height }) => (
        <Label key={lead.id} title={lead.company} sub={`${lead.score} of 100`} visible={show}
          tone={focus === lead.id ? "focus" : undefined} position={[x, height + 0.55, z]} size={9} />
      ))}
      {pins.length === 0 && <Label title="Leads appear here" sub="after a run" visible={show} position={[0, 1.2, -6.4]} size={10} />}
    </group>
  );
}

const CHIP = { stalled: "#E3B04B", untouched: "#7E97A6", upsell: "#8CCBF2", none: "#3D6158" } as const;

/** The CRM: one chip per account, in a lane per stage. Amber is stalled, grey-blue untouched, sky blue an upsell. */
export function CrmChips() {
  const accounts = useAgent((s) => s.accounts);
  const chips = useMemo(() => {
    const out: { id: string; x: number; z: number; color: string; glow: boolean }[] = [];
    STAGES.forEach((stage, lane) => {
      const list = accounts.filter((a) => a.stage === stage);
      const r = CRM_LANES.r0 + lane * CRM_LANES.step;
      list.forEach((a, i) => {
        const t = list.length === 1 ? 0.5 : i / (list.length - 1);
        const p = onTable(CRM_LANES.from + t * (CRM_LANES.to - CRM_LANES.from), r);
        const flag = (["stalled", "upsell", "untouched"] as const).find((f) => a.flags.includes(f)) ?? "none";
        out.push({ id: a.id, x: p.x, z: p.z, color: CHIP[flag], glow: flag === "stalled" || flag === "upsell" });
      });
    });
    return out;
  }, [accounts]);
  return (
    <group>
      {chips.map((c) => (
        <RoundedBox key={c.id} args={[0.34, 0.16, 0.34]} radius={0.05} position={[c.x, 0.39, c.z]} castShadow>
          <meshStandardMaterial color={c.color} emissive={c.color} emissiveIntensity={c.glow ? 0.9 : 0.05} roughness={0.5} toneMapped={!c.glow} />
        </RoundedBox>
      ))}
    </group>
  );
}

function Letter({ y, index }: { y: number; index: number }) {
  return (
    <group position={[0, y, 0]} rotation-y={0.35 + (index % 3) * 0.04 - 0.04}>
      <RoundedBox args={[1.5, 0.035, 1.0]} radius={0.012} castShadow receiveShadow>
        <meshStandardMaterial color="#EDE6D3" roughness={0.85} />
      </RoundedBox>
    </group>
  );
}

/** Drafts waiting for approval as a stack of letters. Approving stamps a brass seal and sends the letter to the tray. */
export function Letters() {
  const waiting = useAgent((s) => s.queue.length);
  const show = useAgent((s) => s.section === 4);
  const ghost = useRef<Group>(null);
  const seal = useRef<Mesh>(null);
  const tint = useRef<MeshStandardMaterial>(null);
  const reduced = useMemo(prefersReducedMotion, []);
  const count = Math.min(14, waiting);
  useFrame(() => {
    const g = ghost.current;
    if (!g || !seal.current || !tint.current) return;
    const last = store.get().sealed.at(-1);
    const t = last ? (performance.now() - last.at) / 1500 : 2;
    if (!last || t > 1 || reduced) { g.visible = false; return; }
    g.visible = true;
    g.position.set(t * 2.6, (count + 1) * 0.04 + Math.sin(t * Math.PI) * 0.9, -t * 1.4);
    seal.current.visible = last.approved;
    tint.current.color.set(last.approved ? "#EDE6D3" : "#F07C5F");
    seal.current.scale.setScalar(Math.min(1, t * 4));
  });
  return (
    <group position={LETTERS}>
      {Array.from({ length: count }, (_, i) => <Letter key={i} index={i} y={0.04 + i * 0.045} />)}
      <group ref={ghost} visible={false} rotation-y={0.35}>
        <RoundedBox args={[1.5, 0.035, 1.0]} radius={0.012}>
          <meshStandardMaterial ref={tint} color="#EDE6D3" roughness={0.85} />
        </RoundedBox>
        <mesh ref={seal} position={[0.35, 0.03, 0.18]} rotation-x={-Math.PI / 2}>
          <circleGeometry args={[0.16, 32]} />
          <meshStandardMaterial {...BRASS} emissive="#C9A15A" emissiveIntensity={0.4} />
        </mesh>
      </group>
      <Label title={waiting ? `${waiting} waiting for you` : "Nothing waiting"} sub="Sent only after you approve"
        visible={show} position={[0, 0.75 + count * 0.045, 0]} size={8} />
    </group>
  );
}
