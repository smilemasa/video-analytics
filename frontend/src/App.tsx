import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Routes, Route, NavLink } from "react-router-dom";
import Header from "./components/Header";
import StaticPage from "./pages/StaticPage";
import LivePage from "./pages/LivePage";
import SecurityPage from "./pages/SecurityPage";

const qc = new QueryClient();

export default function App() {
  return (
    <QueryClientProvider client={qc}>
      <BrowserRouter>
        <div style={{ minHeight: "100vh", background: "#1e1e2e", color: "#cdd6f4", fontFamily: "sans-serif" }}>
          <Header />
          <nav style={navStyle}>
            <NavLink to="/" end style={({ isActive }) => linkStyle(isActive)}>
              静的解析
            </NavLink>
            <NavLink to="/live" style={({ isActive }) => linkStyle(isActive)}>
              ライブ解析
            </NavLink>
            <NavLink to="/security" style={({ isActive }) => linkStyle(isActive)}>
              セキュリティ
            </NavLink>
          </nav>
          <main>
            <Routes>
              <Route path="/" element={<StaticPage />} />
              <Route path="/live" element={<LivePage />} />
              <Route path="/security" element={<SecurityPage />} />
            </Routes>
          </main>
        </div>
      </BrowserRouter>
    </QueryClientProvider>
  );
}

const navStyle: React.CSSProperties = {
  display: "flex",
  gap: 0,
  background: "#181825",
  borderBottom: "1px solid #313244",
};

const linkStyle = (isActive: boolean): React.CSSProperties => ({
  padding: "10px 24px",
  color: isActive ? "#89b4fa" : "#a6adc8",
  textDecoration: "none",
  borderBottom: isActive ? "2px solid #89b4fa" : "2px solid transparent",
  fontWeight: isActive ? "bold" : "normal",
  fontSize: 14,
});
