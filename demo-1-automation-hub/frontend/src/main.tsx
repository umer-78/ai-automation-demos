import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import "./index.css";
import Layout from "./components/Layout";
import { ToastProvider } from "./components/ui";
import Automations from "./pages/Automations";
import Clients from "./pages/Clients";
import NotFound from "./pages/NotFound";
import Overview from "./pages/Overview";
import Reporting from "./pages/Reporting";
import Settings from "./pages/Settings";
import Sites from "./pages/Sites";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ToastProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<Overview />} />
            <Route path="clients" element={<Clients />} />
            <Route path="reporting" element={<Reporting />} />
            <Route path="automations" element={<Automations />} />
            <Route path="sites" element={<Sites />} />
            <Route path="settings" element={<Settings />} />
            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </ToastProvider>
  </StrictMode>,
);
