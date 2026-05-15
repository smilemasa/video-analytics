import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import Header from "./components/Header";
import SecurityPage from "./pages/SecurityPage";

const qc = new QueryClient();

export default function App() {
  return (
    <QueryClientProvider client={qc}>
      <BrowserRouter>
        <div style={{ minHeight: "100vh", background: "#0f0f12", color: "#e2e8f0", fontFamily: "'Inter', sans-serif" }}>
          <Header />
          <main>
            <Routes>
              <Route path="/" element={<SecurityPage />} />
              <Route path="*" element={<SecurityPage />} />
            </Routes>
          </main>
        </div>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
