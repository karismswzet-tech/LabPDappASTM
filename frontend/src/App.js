import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Toaster } from "@/components/ui/sonner";
import { AuthProvider } from "@/context/AuthContext";
import RequireAuth from "@/components/RequireAuth";
import Login from "@/pages/Login";
import { Layout } from "@/components/Layout";
import Landing from "@/pages/Landing";
import ModulePage from "@/pages/ModulePage";
import KhtLayout from "@/pages/kht/KhtLayout";
import KhtDashboard from "@/pages/kht/Dashboard";
import KhtNewTest from "@/pages/kht/NewTest";
import KhtHistory from "@/pages/kht/History";
import KhtTrend from "@/pages/kht/Trend";
import KhtResult from "@/pages/kht/Result";
import KhtColorScale from "@/pages/kht/ColorScale";
import DkaLayout from "@/pages/dka/DkaLayout";
import DkaDashboard from "@/pages/dka/Dashboard";
import DkaNewTest from "@/pages/dka/NewTest";
import DkaHistory from "@/pages/dka/History";
import DkaTrend from "@/pages/dka/Trend";
import DkaResult from "@/pages/dka/Result";
import DkaScale from "@/pages/dka/Scale";
import CopperLayout from "@/pages/copper/CopperLayout";
import CopperDashboard from "@/pages/copper/Dashboard";
import CopperNewTest from "@/pages/copper/NewTest";
import CopperHistory from "@/pages/copper/History";
import CopperTrend from "@/pages/copper/Trend";
import CopperResult from "@/pages/copper/Result";
import CopperBatchResult from "@/pages/copper/BatchResult";
import CopperScale from "@/pages/copper/Scale";
import HtcbtLayout from "@/pages/htcbt/HtcbtLayout";
import HtcbtMonitor from "@/pages/htcbt/Monitor";
import HtcbtNewSample from "@/pages/htcbt/NewSample";
import HtcbtHistory from "@/pages/htcbt/History";
import DkacecLayout from "@/pages/dkacec/DkacecLayout";
import DkacecMonitor from "@/pages/dkacec/Monitor";
import DkacecNewSample from "@/pages/dkacec/NewSample";
import DkacecHistory from "@/pages/dkacec/History";
import RustLayout from "@/pages/rust/RustLayout";
import RustDashboard from "@/pages/rust/Dashboard";
import RustNewTest from "@/pages/rust/NewTest";
import RustHistory from "@/pages/rust/History";
import RustTrend from "@/pages/rust/Trend";
import RustResult from "@/pages/rust/Result";
import RustScale from "@/pages/rust/Scale";
import SaltLayout from "@/pages/saltspray/SaltLayout";
import SaltDashboard from "@/pages/saltspray/Dashboard";
import SaltNewTest from "@/pages/saltspray/NewTest";
import SaltHistory from "@/pages/saltspray/History";
import SaltTrend from "@/pages/saltspray/Trend";
import SaltResult from "@/pages/saltspray/Result";
import SaltScale from "@/pages/saltspray/Scale";
import SaltObservations from "@/pages/saltspray/Observations";
import HumidityLayout from "@/pages/humidity/HumidityLayout";
import HumidityDashboard from "@/pages/humidity/Dashboard";
import HumidityNewTest from "@/pages/humidity/NewTest";
import HumidityHistory from "@/pages/humidity/History";
import HumidityTrend from "@/pages/humidity/Trend";
import HumidityResult from "@/pages/humidity/Result";
import HumidityScale from "@/pages/humidity/Scale";
import DipLayout from "@/pages/diptest/DipLayout";
import DipDashboard from "@/pages/diptest/Dashboard";
import DipNewTest from "@/pages/diptest/NewTest";
import DipHistory from "@/pages/diptest/History";
import DipTrend from "@/pages/diptest/Trend";
import DipResult from "@/pages/diptest/Result";
import DipScale from "@/pages/diptest/Scale";

function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<Login />} />
          {/* Public landing page — no authentication required */}
          <Route path="/" element={<Landing />} />
          <Route element={<RequireAuth />}>
            <Route element={<Layout />}>
              <Route path="/khtt" element={<KhtLayout />}>
                <Route index element={<KhtDashboard />} />
                <Route path="new" element={<KhtNewTest />} />
                <Route path="history" element={<KhtHistory />} />
                <Route path="trend" element={<KhtTrend />} />
              </Route>
              <Route path="/khtt/result/:id" element={<KhtResult />} />
              <Route path="/khtt/color-scale" element={<KhtColorScale />} />
              <Route path="/rating-dka" element={<DkaLayout />}>
                <Route index element={<DkaDashboard />} />
                <Route path="new" element={<DkaNewTest />} />
                <Route path="history" element={<DkaHistory />} />
                <Route path="trend" element={<DkaTrend />} />
              </Route>
              <Route path="/rating-dka/result/:id" element={<DkaResult />} />
              <Route path="/rating-dka/scale" element={<DkaScale />} />
              <Route path="/copper-strip" element={<CopperLayout />}>
                <Route index element={<CopperDashboard />} />
                <Route path="new" element={<CopperNewTest />} />
                <Route path="history" element={<CopperHistory />} />
                <Route path="trend" element={<CopperTrend />} />
              </Route>
              <Route path="/copper-strip/result/:id" element={<CopperResult />} />
              <Route path="/copper-strip/batch/:batchId" element={<CopperBatchResult />} />
              <Route path="/copper-strip/scale" element={<CopperScale />} />
              <Route path="/htcbt" element={<HtcbtLayout />}>
                <Route index element={<HtcbtMonitor />} />
                <Route path="new" element={<HtcbtNewSample />} />
                <Route path="history" element={<HtcbtHistory />} />
              </Route>
              <Route path="/dka-cec" element={<DkacecLayout />}>
                <Route index element={<DkacecMonitor />} />
                <Route path="new" element={<DkacecNewSample />} />
                <Route path="history" element={<DkacecHistory />} />
              </Route>
              <Route path="/rust-preventing" element={<RustLayout />}>
                <Route index element={<RustDashboard />} />
                <Route path="new" element={<RustNewTest />} />
                <Route path="history" element={<RustHistory />} />
                <Route path="trend" element={<RustTrend />} />
                <Route path="grid-scale" element={<RustScale />} />
              </Route>
              <Route path="/rust-preventing/result/:id" element={<RustResult />} />
              <Route path="/salt-spray" element={<SaltLayout />}>
                <Route index element={<SaltDashboard />} />
                <Route path="new" element={<SaltNewTest />} />
                <Route path="observations" element={<SaltObservations />} />
                <Route path="history" element={<SaltHistory />} />
                <Route path="trend" element={<SaltTrend />} />
                <Route path="grid-scale" element={<SaltScale />} />
              </Route>
              <Route path="/salt-spray/result/:id" element={<SaltResult />} />
              <Route path="/humidity-cabinet" element={<HumidityLayout />}>
                <Route index element={<HumidityDashboard />} />
                <Route path="new" element={<HumidityNewTest />} />
                <Route path="history" element={<HumidityHistory />} />
                <Route path="trend" element={<HumidityTrend />} />
                <Route path="grid-scale" element={<HumidityScale />} />
              </Route>
              <Route path="/humidity-cabinet/result/:id" element={<HumidityResult />} />
              <Route path="/dip-test" element={<DipLayout />}>
                <Route index element={<DipDashboard />} />
                <Route path="new" element={<DipNewTest />} />
                <Route path="history" element={<DipHistory />} />
                <Route path="trend" element={<DipTrend />} />
                <Route path="grid-scale" element={<DipScale />} />
              </Route>
              <Route path="/dip-test/result/:id" element={<DipResult />} />
              <Route path="/:module" element={<ModulePage />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
          </Route>
        </Routes>
        <Toaster position="top-right" theme="dark" richColors />
      </AuthProvider>
    </BrowserRouter>
  );
}

export default App;
