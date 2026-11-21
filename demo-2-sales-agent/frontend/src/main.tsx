import { MotionConfig } from "motion/react";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { PREVIEW } from "./lib/api";
import PreviewRouter from "./lib/previewRouter";
import "./index.css";
import Layout from "./components/Layout";
import { ToastProvider } from "./components/ui";
import { RunProvider } from "./lib/run";
import Accounts from "./pages/Accounts";
import Approvals from "./pages/Approvals";
import Leads from "./pages/Leads";
import Learning from "./pages/Learning";
import NotFound from "./pages/NotFound";
import Overview from "./pages/Overview";
import Profile from "./pages/Profile";
import Report from "./pages/Report";
import Runs from "./pages/Runs";

const Router = PREVIEW ? PreviewRouter : BrowserRouter;

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <MotionConfig reducedMotion="user">
      <ToastProvider>
        <RunProvider>
          <Router>
            <Routes>
              <Route element={<Layout />}>
                <Route index element={<Overview />} />
                <Route path="approvals" element={<Approvals />} />
                <Route path="leads" element={<Leads />} />
                <Route path="accounts" element={<Accounts />} />
                <Route path="learning" element={<Learning />} />
                <Route path="report" element={<Report />} />
                <Route path="runs" element={<Runs />} />
                <Route path="profile" element={<Profile />} />
                <Route path="*" element={<NotFound />} />
              </Route>
            </Routes>
          </Router>
        </RunProvider>
      </ToastProvider>
    </MotionConfig>
  </StrictMode>,
);
