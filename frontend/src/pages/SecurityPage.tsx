import { useState, useEffect, useCallback, useRef } from "react";
import type {
  SecurityPipelineState,
  SecurityConfig,
  SecurityImageAnalysisResult,
  SecurityVideoJobResult,
  SecurityVideoEvent,
  OfflineResult,
} from "../api";
import {
  getSecurityConfig,
  updateSecurityConfig,
  startCamera,
  stopCamera,
  getCameraStatus,
  analyzeSecurityImage,
  submitSecurityVideo,
  getSecurityVideoStatus,
  getSecurityVideoResult,
} from "../api";
import {
  AnnotatedFramePanel,
  DetectionList,
  TriggerPanel,
  VLMResultPanel,
  RiskScorePanel,
  EventLogPanel,
  LatencyPanel,
  ConfigPanel,
} from "../components/SecurityDebugPanel";

const SSE_URL = "/api/security/debug/stream";

export default function SecurityPage() {
  const [state, setState] = useState<SecurityPipelineState | null>(null);
  const [config, setConfig] = useState<SecurityConfig>({
    threshold: 70,
    distance_threshold_m: 3.0,
    stay_duration_sec: 2.0,
  });
  const [camActive, setCamActive] = useState(false);
  const [camError, setCamError] = useState<string | null>(null);
  const esRef = useRef<EventSource | null>(null);

  // ---- SSE 購読 ----
  useEffect(() => {
    const es = new EventSource(SSE_URL);
    esRef.current = es;
    es.onmessage = (evt) => {
      try {
        setState(JSON.parse(evt.data) as SecurityPipelineState);
      } catch {
        /* ignore parse error */
      }
    };
    return () => es.close();
  }, []);

  // ---- 設定ロード ----
  useEffect(() => {
    getSecurityConfig()
      .then((r) => setConfig(r.data))
      .catch(() => {/* fallback to default */});
    getCameraStatus()
      .then((r) => setCamActive(r.data.active))
      .catch(() => {});
  }, []);

  // ---- カメラ操作 ----
  const handleStartCamera = useCallback(async () => {
    setCamError(null);
    try {
      await startCamera({ source_type: "usb", camera_index: 0 });
      setCamActive(true);
    } catch (e) {
      setCamError(String(e));
    }
  }, []);

  const handleStopCamera = useCallback(async () => {
    await stopCamera();
    setCamActive(false);
  }, []);

  // ---- 設定保存 ----
  const handleSaveConfig = useCallback(async (cfg: SecurityConfig) => {
    try {
      const r = await updateSecurityConfig(cfg);
      setConfig(r.data);
    } catch {/* ignore */}
  }, []);

  const stayThreshold = config.stay_duration_sec;

  return (
    <div style={styles.page}>
      <div style={styles.header}>
        <h1 style={styles.title}>セキュリティデバッグビュー</h1>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {camError && <span style={{ color: "#f38ba8", fontSize: 13 }}>{camError}</span>}
          <button
            onClick={camActive ? handleStopCamera : handleStartCamera}
            style={{ ...styles.btn, background: camActive ? "#f38ba8" : "#a6e3a1", color: "#1e1e2e" }}
          >
            {camActive ? "■ カメラ停止" : "▶ USBカメラ開始"}
          </button>
          <div style={{
            ...styles.statusDot,
            background: state && state.timestamp_ms > 0 ? "#a6e3a1" : "#6c7086",
          }} title={state ? "パイプライン動作中" : "未接続"} />
        </div>
      </div>

      {/* メイン 2カラム (ライブ) */}
      <div style={styles.twoCol}>
        <div style={styles.col}>
          <AnnotatedFramePanel
            b64={state?.annotated_image ?? null}
            label={state ? `${state.detections.length}件検出` : undefined}
          />
          <DetectionList detections={state?.detections ?? []} />
          <TriggerPanel
            conditions={state?.active_conditions ?? []}
            triggers={state?.active_triggers ?? []}
            stayThreshold={stayThreshold}
          />
        </div>
        <div style={styles.col}>
          <RiskScorePanel scoring={state?.latest_scoring ?? null} />
          <LatencyPanel latency={state?.latest_latency ?? null} />
          <VLMResultPanel vlm={state?.latest_vlm ?? null} />
          <EventLogPanel history={state?.scoring_history ?? []} />
        </div>
      </div>

      {/* オフライン解析デバッグパネル (SSE latest_offline が届いたとき表示) */}
      {state?.latest_offline && (
        <OfflineDebugPanel offline={state.latest_offline} />
      )}

      {/* オフライン解析 (アップロード UI) */}
      <OfflineAnalysisSection />

      {/* 設定パネル */}
      <ConfigPanel config={config} onSave={handleSaveConfig} />

      {/* オーナー除外状態 */}
      {state && state.owner_candidates.length > 0 && (
        <div style={styles.ownerBar}>
          オーナー除外中 Track ID: {state.owner_candidates.join(", ")}
        </div>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------
// スタイル
// --------------------------------------------------------------------------

const styles: Record<string, React.CSSProperties> = {
  page: {
    maxWidth: 1400,
    margin: "0 auto",
    padding: "16px 20px",
    display: "flex",
    flexDirection: "column",
    gap: 16,
  },
  header: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
  },
  title: {
    margin: 0,
    fontSize: 20,
    color: "#cdd6f4",
  },
  twoCol: {
    display: "grid",
    gridTemplateColumns: "1fr 1fr",
    gap: 16,
  },
  col: {
    display: "flex",
    flexDirection: "column",
    gap: 12,
  },
  btn: {
    border: "none",
    borderRadius: 8,
    padding: "8px 16px",
    fontWeight: "bold",
    cursor: "pointer",
    fontSize: 13,
  },
  statusDot: {
    width: 12,
    height: 12,
    borderRadius: "50%",
    flexShrink: 0,
  },
  ownerBar: {
    background: "#313244",
    borderRadius: 8,
    padding: "8px 16px",
    fontSize: 13,
    color: "#a6adc8",
  },
};

// --------------------------------------------------------------------------
// オフライン解析結果デバッグパネル (SSE latest_offline を同じパネル群で表示)
// --------------------------------------------------------------------------

function OfflineDebugPanel({ offline }: { offline: OfflineResult }) {
  const sourceLabel = offline.source === "image" ? "📷 静止画" : "🎬 動画";
  const sourceBadgeColor = offline.source === "image" ? "#f9e2af" : "#cba6f7";

  return (
    <div style={{
      background: "#1e1e2e",
      borderRadius: 12,
      border: "2px solid #cba6f7",
      padding: 16,
      display: "flex",
      flexDirection: "column",
      gap: 12,
    }}>
      {/* ヘッダー */}
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <span style={{
          background: sourceBadgeColor,
          color: "#1e1e2e",
          borderRadius: 6,
          padding: "2px 10px",
          fontWeight: "bold",
          fontSize: 12,
        }}>
          {sourceLabel} OFFLINE
        </span>
        {offline.source === "video" && (
          <>
            {offline.timestamp_sec !== undefined && (
              <span style={{ color: "#a6adc8", fontSize: 12 }}>
                映像時刻: {offline.timestamp_sec.toFixed(2)}s
              </span>
            )}
            {offline.frame_id !== undefined && (
              <span style={{ color: "#a6adc8", fontSize: 12 }}>
                Frame #{offline.frame_id}
              </span>
            )}
            {offline.total_events !== undefined && (
              <span style={{ color: "#a6adc8", fontSize: 12 }}>
                累計イベント: {offline.total_events}件
              </span>
            )}
          </>
        )}
      </div>

      {/* 2カラム: フレーム＋スコア */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <AnnotatedFramePanel
            b64={offline.annotated_image}
            label={`${offline.detections.length}件検出 (オフライン)`}
          />
          {offline.detections.length > 0 && (
            <DetectionList detections={offline.detections} />
          )}
          {offline.distances.length > 0 && (
            <div style={{
              background: "#313244",
              borderRadius: 8,
              padding: "8px 12px",
              fontSize: 12,
              color: "#a6adc8",
            }}>
              <div style={{ fontWeight: "bold", marginBottom: 4 }}>距離情報</div>
              {offline.distances.map((d, i) => (
                <div key={i}>
                  Person {d.person_track_id} ↔ Vehicle {d.vehicle_track_id}: {d.distance_m.toFixed(2)}m
                </div>
              ))}
            </div>
          )}
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <RiskScorePanel scoring={offline.scoring} />
          <VLMResultPanel vlm={offline.vlm_result} />
        </div>
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------
// オフライン解析セクション
// --------------------------------------------------------------------------

const LABEL_NAMES: Record<string, string> = {
  forced_entry_attempt: "強制侵入試行",
  vandalism: "車体損傷",
  tampering: "ドア・鍵操作",
  peering: "車内のぞき",
  approach_fast: "急接近",
  circling: "周回",
  stay_near_vehicle: "長時間滞在",
  unknown_behavior: "不明",
};

function OfflineAnalysisSection() {
  const [tab, setTab] = useState<"image" | "video">("image");

  return (
    <div style={offStyles.section}>
      <div style={offStyles.sectionHeader}>
        <h2 style={offStyles.sectionTitle}>オフライン解析（静止画 / 動画）</h2>
        <div style={offStyles.tabs}>
          {(["image", "video"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              style={{
                ...offStyles.tab,
                background: tab === t ? "#89b4fa" : "#313244",
                color: tab === t ? "#1e1e2e" : "#a6adc8",
              }}
            >
              {t === "image" ? "📷 静止画" : "🎬 動画"}
            </button>
          ))}
        </div>
      </div>
      {tab === "image" ? <ImageAnalysisPanel /> : <VideoAnalysisPanel />}
    </div>
  );
}

// ---- 静止画解析パネル ----

function ImageAnalysisPanel() {
  const [result, setResult] = useState<SecurityImageAnalysisResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleFile = useCallback(async (file: File) => {
    setError(null);
    setLoading(true);
    try {
      const r = await analyzeSecurityImage(file);
      setResult(r.data);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  return (
    <div>
      <DropZone
        accept="image/jpeg,image/png"
        hint="jpg / png をドラッグ＆ドロップ"
        onFile={handleFile}
        loading={loading}
        error={error}
      />
      {result && (
        <div style={offStyles.twoCol}>
          <div>
            <img
              src={`data:image/jpeg;base64,${result.annotated_image}`}
              alt="result"
              style={{ width: "100%", borderRadius: 8 }}
            />
            <DetectionTable detections={result.detections} distances={result.distances} />
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <VLMCard vlm={result.vlm_result} />
            <ScoreCard scoring={result.scoring} />
          </div>
        </div>
      )}
    </div>
  );
}

// ---- 動画解析パネル ----

function VideoAnalysisPanel() {
  const [jobId, setJobId] = useState<string | null>(null);
  const [status, setStatus] = useState<string>("idle");
  const [progress, setProgress] = useState(0);
  const [result, setResult] = useState<SecurityVideoJobResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const startPoll = useCallback((id: string) => {
    pollRef.current = setInterval(async () => {
      try {
        const s = await getSecurityVideoStatus(id);
        setStatus(s.data.status);
        setProgress(s.data.progress);
        if (s.data.status === "done" || s.data.status === "error") {
          clearInterval(pollRef.current!);
          if (s.data.status === "done") {
            const r = await getSecurityVideoResult(id);
            setResult(r.data);
          } else {
            setError(s.data.error ?? "エラー");
          }
        }
      } catch {/* ignore */}
    }, 1500);
  }, []);

  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);

  const handleFile = useCallback(async (file: File) => {
    setError(null);
    setResult(null);
    setStatus("queued");
    setProgress(0);
    try {
      const r = await submitSecurityVideo(file);
      setJobId(r.data.job_id);
      startPoll(r.data.job_id);
    } catch (e) {
      setError(String(e));
      setStatus("idle");
    }
  }, [startPoll]);

  return (
    <div>
      <DropZone
        accept="video/mp4,video/avi,video/quicktime"
        hint="mp4 / avi / mov をドラッグ＆ドロップ"
        onFile={handleFile}
        loading={status === "queued" || status === "processing"}
        error={error}
      />
      {(status === "queued" || status === "processing") && (
        <div style={{ marginTop: 12 }}>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4, fontSize: 13, color: "#a6adc8" }}>
            <span>解析中... ({status})</span>
            <span>{progress}%</span>
          </div>
          <div style={{ background: "#313244", borderRadius: 4, height: 8 }}>
            <div style={{ background: "#89b4fa", borderRadius: 4, height: 8, width: `${progress}%`, transition: "width 0.5s" }} />
          </div>
        </div>
      )}
      {result && <VideoResultPanel result={result} />}
    </div>
  );
}

// ---- 動画結果パネル ----

function VideoResultPanel({ result }: { result: SecurityVideoJobResult }) {
  const [selected, setSelected] = useState<SecurityVideoEvent | null>(result.events[0] ?? null);

  return (
    <div style={{ marginTop: 16 }}>
      <div style={offStyles.card}>
        <div style={{ fontSize: 14, color: "#cdd6f4", marginBottom: 8 }}>
          処理フレーム数: <strong>{result.total_frames_processed}</strong>　
          検知イベント: <strong>{result.events.length}</strong>　
          通知対象: <strong style={{ color: result.notify_count > 0 ? "#f38ba8" : "#a6e3a1" }}>{result.notify_count}</strong>
        </div>
        {result.events.length === 0 ? (
          <p style={{ color: "#6c7086", fontSize: 13 }}>不審イベントは検出されませんでした</p>
        ) : (
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {result.events.map((ev, i) => (
              <button
                key={i}
                onClick={() => setSelected(ev)}
                style={{
                  ...offStyles.eventBtn,
                  background: selected === ev ? "#89b4fa" : "#313244",
                  color: selected === ev ? "#1e1e2e" : (ev.scoring.action === "notify" ? "#f38ba8" : "#a6adc8"),
                  borderColor: ev.scoring.action === "notify" ? "#f38ba8" : "transparent",
                }}
              >
                {ev.timestamp_sec.toFixed(1)}s<br />
                <span style={{ fontSize: 10 }}>{LABEL_NAMES[ev.vlm_result.label] ?? ev.vlm_result.label}</span>
              </button>
            ))}
          </div>
        )}
      </div>
      {selected && (
        <div style={{ ...offStyles.twoCol, marginTop: 12 }}>
          <div>
            {selected.annotated_image ? (
              <img
                src={`data:image/jpeg;base64,${selected.annotated_image}`}
                alt="event frame"
                style={{ width: "100%", borderRadius: 8 }}
              />
            ) : (
              <div style={{ height: 180, background: "#181825", borderRadius: 8, display: "flex", alignItems: "center", justifyContent: "center", color: "#6c7086" }}>
                フレームなし
              </div>
            )}
            <div style={{ fontSize: 12, color: "#6c7086", marginTop: 4 }}>
              {selected.timestamp_sec.toFixed(2)}s　Person #{selected.trigger.person_track_id}　距離 {selected.trigger.distance_m.toFixed(0)}px
            </div>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <VLMCard vlm={selected.vlm_result} />
            <ScoreCard scoring={selected.scoring} />
          </div>
        </div>
      )}
    </div>
  );
}

// ---- 共通サブコンポーネント ----

function DropZone({
  accept, hint, onFile, loading, error,
}: {
  accept: string;
  hint: string;
  onFile: (f: File) => void;
  loading: boolean;
  error: string | null;
}) {
  const [drag, setDrag] = useState(false);
  return (
    <div>
      <div
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); const f = e.dataTransfer.files[0]; if (f) onFile(f); }}
        style={{ ...offStyles.dropzone, borderColor: drag ? "#89b4fa" : "#45475a" }}
      >
        {loading ? <span style={{ color: "#89b4fa" }}>解析中...</span> : (
          <>
            <span style={{ color: "#6c7086" }}>{hint}</span>
            <input type="file" accept={accept} style={{ color: "#cdd6f4" }}
              onChange={(e) => { const f = e.target.files?.[0]; if (f) onFile(f); }} />
          </>
        )}
      </div>
      {error && <p style={{ color: "#f38ba8", fontSize: 13, marginTop: 4 }}>{error}</p>}
    </div>
  );
}

function VLMCard({ vlm }: { vlm: { label: string; reason: string; is_fallback: boolean; raw_output: string } | null }) {
  if (!vlm) return null;
  const COLORS: Record<string, string> = {
    forced_entry_attempt: "#f38ba8", vandalism: "#fab387", tampering: "#f9e2af",
    peering: "#a6e3a1", approach_fast: "#89dceb", circling: "#89b4fa",
    stay_near_vehicle: "#b4befe", unknown_behavior: "#6c7086",
  };
  return (
    <div style={offStyles.card}>
      <div style={{ fontSize: 12, color: "#6c7086", marginBottom: 6 }}>VLM 解析結果</div>
      <div style={{ display: "flex", gap: 8, marginBottom: 6, flexWrap: "wrap" }}>
        <span style={{ background: COLORS[vlm.label] ?? "#6c7086", color: "#1e1e2e", borderRadius: 6, padding: "2px 10px", fontWeight: "bold", fontSize: 13 }}>
          {LABEL_NAMES[vlm.label] ?? vlm.label}
        </span>
        {vlm.is_fallback && <span style={{ background: "#6c7086", color: "#cdd6f4", borderRadius: 6, padding: "2px 8px", fontSize: 11 }}>FALLBACK</span>}
      </div>
      <p style={{ fontSize: 13, color: "#cdd6f4", margin: 0 }}>{vlm.reason}</p>
    </div>
  );
}

function ScoreCard({ scoring }: { scoring: { risk_score: number; behavior_score: number; context_score: number; persistence_score: number; action: string; label: string } | null }) {
  if (!scoring) return null;
  const color = scoring.risk_score >= 70 ? "#f38ba8" : scoring.risk_score >= 40 ? "#f9e2af" : "#a6e3a1";
  return (
    <div style={offStyles.card}>
      <div style={{ fontSize: 12, color: "#6c7086", marginBottom: 6 }}>リスクスコア</div>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <span style={{ fontSize: 40, fontWeight: "bold", color }}>{scoring.risk_score}</span>
        <span style={{ background: scoring.action === "notify" ? "#f38ba8" : "#313244", color: scoring.action === "notify" ? "#1e1e2e" : "#cdd6f4", borderRadius: 6, padding: "4px 12px", fontWeight: "bold" }}>
          {scoring.action === "notify" ? "🔔 通知" : "— なし"}
        </span>
      </div>
      <div style={{ display: "flex", gap: 6, marginTop: 8, fontSize: 12, color: "#a6adc8" }}>
        <span>行動 {scoring.behavior_score}</span>
        <span>環境 {scoring.context_score}</span>
        <span>継続 {scoring.persistence_score}</span>
      </div>
    </div>
  );
}

function DetectionTable({ detections, distances }: { detections: Array<{ track_id: number; class_name: string; confidence: number; owner_excluded: boolean }>; distances: Array<{ person_track_id: number; vehicle_track_id: number; distance_m: number | null }> }) {
  return (
    <div style={{ ...offStyles.card, marginTop: 8 }}>
      <div style={{ fontSize: 12, color: "#6c7086", marginBottom: 6 }}>検出リスト</div>
      {detections.length === 0 ? <p style={{ fontSize: 13, color: "#6c7086" }}>検出なし</p> : (
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
          <thead>
            <tr>
              {["ID", "クラス", "信頼度"].map(h => <th key={h} style={{ textAlign: "left", color: "#6c7086", padding: "2px 6px", borderBottom: "1px solid #313244" }}>{h}</th>)}
            </tr>
          </thead>
          <tbody>
            {detections.map(d => (
              <tr key={d.track_id}>
                <td style={{ padding: "2px 6px", color: "#cdd6f4" }}>{d.track_id}</td>
                <td style={{ padding: "2px 6px", color: d.class_name === "person" ? "#f9e2af" : "#89b4fa" }}>{d.class_name}</td>
                <td style={{ padding: "2px 6px", color: "#cdd6f4" }}>{(d.confidence * 100).toFixed(1)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {distances.length > 0 && (
        <div style={{ marginTop: 6, fontSize: 12, color: "#6c7086" }}>
          {distances.map((d, i) => (
            <span key={i} style={{ marginRight: 12 }}>
              P#{d.person_track_id}↔V#{d.vehicle_track_id}: {d.distance_m?.toFixed(0) ?? "N/A"}px
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

const offStyles: Record<string, React.CSSProperties> = {
  section: {
    background: "#181825",
    borderRadius: 10,
    padding: 20,
    border: "1px solid #313244",
  },
  sectionHeader: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 16,
  },
  sectionTitle: {
    margin: 0,
    fontSize: 16,
    color: "#cdd6f4",
  },
  tabs: {
    display: "flex",
    gap: 4,
  },
  tab: {
    border: "none",
    borderRadius: 6,
    padding: "6px 14px",
    fontWeight: "bold",
    cursor: "pointer",
    fontSize: 13,
  },
  dropzone: {
    border: "2px dashed",
    borderRadius: 8,
    padding: "24px 16px",
    textAlign: "center" as const,
    cursor: "pointer",
    display: "flex",
    flexDirection: "column" as const,
    alignItems: "center",
    gap: 8,
  },
  twoCol: {
    display: "grid",
    gridTemplateColumns: "1fr 1fr",
    gap: 12,
  },
  card: {
    background: "#1e1e2e",
    borderRadius: 8,
    padding: 12,
    border: "1px solid #313244",
  },
  eventBtn: {
    border: "1px solid transparent",
    borderRadius: 6,
    padding: "6px 10px",
    cursor: "pointer",
    fontSize: 12,
    fontWeight: "bold",
    textAlign: "center" as const,
    minWidth: 60,
  },
};
