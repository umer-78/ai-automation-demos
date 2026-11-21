import { createRoot } from "react-dom/client";
import "../index.css";
import FlowScene from "../components/FlowScene";

declare global {
  interface Window {
    __advance?: (seconds: number) => void;
  }
}

const still = new URLSearchParams(location.search).has("still");
createRoot(document.getElementById("root")!).render(
  still ? (
    <FlowScene failureRate={0.12} still signal={null} selected={null} onSelect={() => {}} />
  ) : (
    <FlowScene failureRate={0.12} still={false} signal={null} selected={null} onSelect={() => {}} onRecordReady={(advance) => (window.__advance = advance)} />
  ),
);
