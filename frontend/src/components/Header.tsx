import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  getModels,
  getModelStatus,
  switchModel,
} from "../api";

export default function Header() {
  const qc = useQueryClient();

  const { data: modelsData } = useQuery({
    queryKey: ["models"],
    queryFn: () => getModels().then((r) => r.data),
  });

  const { data: modelStatus } = useQuery({
    queryKey: ["modelStatus"],
    queryFn: () => getModelStatus().then((r) => r.data),
    refetchInterval: (query) =>
      query.state.data?.status === "loading" ? 2000 : false,
  });

  const switchModelMut = useMutation({
    mutationFn: (id: string) => switchModel(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["modelStatus"] }),
  });

  const statusColor =
    modelStatus?.status === "loaded"
      ? "#4caf50"
      : modelStatus?.status === "loading"
      ? "#ff9800"
      : "#f44336";

  return (
    <header style={styles.header}>
      <span style={styles.title}>🎥 Video Analytics</span>

      <div style={styles.controls}>
        {/* Model selector */}
        <label style={styles.label}>
          VLM モデル&nbsp;
          <span style={{ color: statusColor, fontWeight: "bold" }}>
            [{modelStatus?.status ?? "…"}]
          </span>
          &nbsp;
          <select
            value={modelStatus?.model_id ?? ""}
            onChange={(e) => switchModelMut.mutate(e.target.value)}
            style={styles.select}
          >
            {modelsData?.models.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        </label>
      </div>
    </header>
  );
}

const styles: Record<string, React.CSSProperties> = {
  header: {
    background: "rgba(15, 15, 19, 0.75)",
    backdropFilter: "blur(16px)",
    color: "#f8fafc",
    padding: "12px 24px",
    display: "flex",
    alignItems: "center",
    gap: 24,
    flexWrap: "wrap",
    borderBottom: "1px solid rgba(255, 255, 255, 0.08)",
    position: "sticky",
    top: 0,
    zIndex: 100,
  },
  title: { 
    fontSize: 20, 
    fontWeight: 800, 
    whiteSpace: "nowrap",
    background: "linear-gradient(90deg, #60a5fa, #a78bfa)",
    WebkitBackgroundClip: "text",
    WebkitTextFillColor: "transparent",
    letterSpacing: "-0.02em"
  },
  controls: { display: "flex", gap: 16, flexWrap: "wrap", alignItems: "center" },
  label: { display: "flex", alignItems: "center", gap: 6, fontSize: 13, color: "#94a3b8" },
  select: {
    background: "rgba(255, 255, 255, 0.05)",
    color: "#f8fafc",
    border: "1px solid rgba(255, 255, 255, 0.1)",
    borderRadius: 6,
    padding: "4px 8px",
    fontSize: 13,
    outline: "none",
    transition: "border-color 0.2s",
  },
  btn: {
    background: "linear-gradient(135deg, #3b82f6, #6366f1)",
    color: "#ffffff",
    border: "none",
    borderRadius: 6,
    padding: "4px 14px",
    cursor: "pointer",
    fontWeight: "bold",
    fontSize: 13,
    transition: "transform 0.1s, opacity 0.2s",
    boxShadow: "0 2px 10px rgba(59, 130, 246, 0.3)",
  },
};
