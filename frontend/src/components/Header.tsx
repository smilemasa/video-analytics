import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  getModels,
  getModelStatus,
  switchModel,
  getYoloClasses,
  setYoloClasses,
  getPrompt,
  setPrompt,
} from "../api";

const YOLO_PRESETS: { label: string; mode: string; classes: number[] }[] = [
  { label: "Person", mode: "Person", classes: [0] },
  { label: "Vehicles", mode: "Vehicles", classes: [2, 3, 5, 7] },
  { label: "Animals", mode: "Animals", classes: [14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24] },
  { label: "Furniture", mode: "Furniture", classes: [56, 57, 58, 59, 60, 61, 62, 72] },
  { label: "All", mode: "All", classes: Array.from({ length: 80 }, (_, i) => i) },
];

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

  const { data: yoloData } = useQuery({
    queryKey: ["yoloClasses"],
    queryFn: () => getYoloClasses().then((r) => r.data),
  });

  const { data: promptData } = useQuery({
    queryKey: ["prompt"],
    queryFn: () => getPrompt().then((r) => r.data),
  });

  const switchModelMut = useMutation({
    mutationFn: (id: string) => switchModel(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["modelStatus"] }),
  });

  const setYoloMut = useMutation({
    mutationFn: ({ mode, classes }: { mode: string; classes: number[] }) =>
      setYoloClasses(mode, classes),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["yoloClasses"] }),
  });

  const setPromptMut = useMutation({
    mutationFn: (p: string) => setPrompt(p),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["prompt"] }),
  });

  const [promptInput, setPromptInput] = useState("");
  useEffect(() => {
    if (promptData?.prompt !== undefined) setPromptInput(promptData.prompt);
  }, [promptData?.prompt]);

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

        {/* YOLO preset */}
        <label style={styles.label}>
          YOLO クラス&nbsp;
          <select
            value={yoloData?.mode ?? ""}
            onChange={(e) => {
              const preset = YOLO_PRESETS.find((p) => p.mode === e.target.value);
              if (preset) setYoloMut.mutate({ mode: preset.mode, classes: preset.classes });
            }}
            style={styles.select}
          >
            {YOLO_PRESETS.map((p) => (
              <option key={p.mode} value={p.mode}>
                {p.label}
              </option>
            ))}
          </select>
        </label>

        {/* Prompt */}
        <label style={styles.label}>
          プロンプト&nbsp;
          <input
            value={promptInput}
            onChange={(e) => setPromptInput(e.target.value)}
            style={{ ...styles.select, width: 260 }}
          />
          <button
            onClick={() => setPromptMut.mutate(promptInput)}
            style={styles.btn}
          >
            保存
          </button>
        </label>
      </div>
    </header>
  );
}

const styles: Record<string, React.CSSProperties> = {
  header: {
    background: "#1e1e2e",
    color: "#cdd6f4",
    padding: "10px 20px",
    display: "flex",
    alignItems: "center",
    gap: 24,
    flexWrap: "wrap",
    borderBottom: "2px solid #313244",
  },
  title: { fontSize: 20, fontWeight: "bold", whiteSpace: "nowrap" },
  controls: { display: "flex", gap: 16, flexWrap: "wrap", alignItems: "center" },
  label: { display: "flex", alignItems: "center", gap: 4, fontSize: 13 },
  select: {
    background: "#313244",
    color: "#cdd6f4",
    border: "1px solid #45475a",
    borderRadius: 4,
    padding: "2px 6px",
    fontSize: 13,
  },
  btn: {
    background: "#89b4fa",
    color: "#1e1e2e",
    border: "none",
    borderRadius: 4,
    padding: "2px 10px",
    cursor: "pointer",
    fontWeight: "bold",
    fontSize: 13,
  },
};
