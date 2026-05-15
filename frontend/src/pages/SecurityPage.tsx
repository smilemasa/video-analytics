import { useState, useEffect, useCallback, useRef } from "react";
import type {
  SecurityPipelineState,
  SecurityConfig,
  SecurityImageAnalysisResult,
  SecurityVideoJobResult,
  SecurityVideoEvent,
  CameraSourceType,
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
  const [activeTab, setActiveTab] = useState<"live" | "image" | "video">("live");

  return (
    <div style={styles.page}>
      {/* Header & Navigation */}
      <div style={styles.header}>
        <div>
          <h1 style={styles.title}>Security Dashboard</h1>
          <p style={styles.subtitle}>Real-time Threat Detection & Analytics</p>
        </div>
        <div style={styles.tabContainer}>
          {(["live", "image", "video"] as const).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              style={{
                ...styles.tabBtn,
                ...(activeTab === tab ? styles.tabBtnActive : {}),
              }}
            >
              {tab === "live" ? "🔴 Live Stream" : tab === "image" ? "📷 Image Analysis" : "🎬 Video Analysis"}
            </button>
          ))}
        </div>
      </div>

      <div style={styles.content}>
        {activeTab === "live" && <LiveView />}
        {activeTab === "image" && <ImageAnalysisPanel />}
        {activeTab === "video" && <VideoAnalysisPanel />}
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------
// ライブ監視ビュー (Live Stream)
// --------------------------------------------------------------------------
function LiveView() {
  const [state, setState] = useState<SecurityPipelineState | null>(null);
  const [config, setConfig] = useState<SecurityConfig>({
    threshold: 70,
    distance_threshold_m: 3.0,
    stay_duration_sec: 2.0,
  });

  const [camActive, setCamActive] = useState(false);
  const [camError, setCamError] = useState<string | null>(null);
  const [sourceType, setSourceType] = useState<CameraSourceType>("usb");
  
  // Camera inputs
  const [cameraIndex, setCameraIndex] = useState(0);
  const [rtspUrl, setRtspUrl] = useState("rtsp://");
  const [onvifHost, setOnvifHost] = useState("");
  const [onvifPort, setOnvifPort] = useState(80);
  const [onvifUser, setOnvifUser] = useState("");
  const [onvifPassword, setOnvifPassword] = useState("");
  const [onvifProfile, setOnvifProfile] = useState(0);

  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    const es = new EventSource(SSE_URL);
    esRef.current = es;
    es.onmessage = (evt) => {
      try { setState(JSON.parse(evt.data)); } catch { /* ignore */ }
    };
    return () => es.close();
  }, []);

  useEffect(() => {
    getSecurityConfig().then((r) => setConfig(r.data)).catch(() => {});
    getCameraStatus().then((r) => {
      setCamActive(r.data.active);
      if (r.data.source_type) setSourceType(r.data.source_type as CameraSourceType);
    }).catch(() => {});
  }, []);

  const handleStartCamera = useCallback(async () => {
    setCamError(null);
    try {
      if (sourceType === "usb") {
        await startCamera({ source_type: "usb", camera_index: cameraIndex });
      } else if (sourceType === "rtsp") {
        await startCamera({ source_type: "rtsp", rtsp_url: rtspUrl });
      } else {
        await startCamera({
          source_type: "onvif", onvif_host: onvifHost, onvif_port: onvifPort,
          onvif_user: onvifUser, onvif_password: onvifPassword, onvif_profile: onvifProfile,
        });
      }
      setCamActive(true);
    } catch (e) {
      setCamError(String(e));
    }
  }, [sourceType, cameraIndex, rtspUrl, onvifHost, onvifPort, onvifUser, onvifPassword, onvifProfile]);

  const handleStopCamera = useCallback(async () => {
    await stopCamera();
    setCamActive(false);
  }, []);

  const handleSaveConfig = useCallback(async (cfg: SecurityConfig) => {
    try {
      const r = await updateSecurityConfig(cfg);
      setConfig(r.data);
    } catch { /* ignore */ }
  }, []);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      {/* カメラコントロール */}
      <div style={styles.controlPanel}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: 16 }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <div style={{ display: "flex", gap: 8 }}>
              {(["usb", "rtsp", "onvif"] as CameraSourceType[]).map((t) => (
                <button
                  key={t}
                  onClick={() => !camActive && setSourceType(t)}
                  disabled={camActive}
                  style={sourceType === t ? styles.sourceTabActive : styles.sourceTab}
                >
                  {t.toUpperCase()}
                </button>
              ))}
            </div>
            
            <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
              {sourceType === "usb" && (
                <input type="number" min={0} value={cameraIndex} onChange={(e) => setCameraIndex(Number(e.target.value))} style={styles.input} disabled={camActive} placeholder="Index" />
              )}
              {sourceType === "rtsp" && (
                <input type="text" value={rtspUrl} onChange={(e) => setRtspUrl(e.target.value)} style={{ ...styles.input, width: 300 }} disabled={camActive} />
              )}
              {sourceType === "onvif" && (
                <>
                  <input type="text" value={onvifHost} onChange={(e) => setOnvifHost(e.target.value)} style={styles.input} disabled={camActive} placeholder="Host" />
                  <input type="number" value={onvifPort} onChange={(e) => setOnvifPort(Number(e.target.value))} style={{ ...styles.input, width: 60 }} disabled={camActive} placeholder="Port" />
                  <input type="text" value={onvifUser} onChange={(e) => setOnvifUser(e.target.value)} style={styles.input} disabled={camActive} placeholder="User" />
                  <input type="password" value={onvifPassword} onChange={(e) => setOnvifPassword(e.target.value)} style={styles.input} disabled={camActive} placeholder="Pass" />
                  <input type="number" min={0} value={onvifProfile} onChange={(e) => setOnvifProfile(Number(e.target.value))} style={{ ...styles.input, width: 60 }} disabled={camActive} placeholder="Profile" />
                </>
              )}
            </div>
          </div>
          
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13, color: "#94a3b8" }}>
              <div style={{
                width: 10, height: 10, borderRadius: "50%",
                background: state && state.timestamp_ms > 0 ? "#10b981" : "#475569",
                boxShadow: state && state.timestamp_ms > 0 ? "0 0 10px #10b981" : "none"
              }} />
              {state && state.timestamp_ms > 0 ? "Stream Active" : "Disconnected"}
            </div>
            <button
              onClick={camActive ? handleStopCamera : handleStartCamera}
              style={{ ...styles.actionBtn, background: camActive ? "linear-gradient(135deg, #ef4444, #f43f5e)" : "linear-gradient(135deg, #10b981, #34d399)" }}
            >
              {camActive ? "Stop Camera" : "Start Camera"}
            </button>
          </div>
        </div>
        {camError && <div style={{ color: "#f87171", fontSize: 13, marginTop: 8 }}>{camError}</div>}
      </div>

      {/* メインダッシュボード */}
      <div style={styles.twoCol}>
        <div style={styles.col}>
          <AnnotatedFramePanel
            b64={state?.annotated_image ?? null}
            label={state ? `${state.detections.length} Detections` : undefined}
          />
          <DetectionList detections={state?.detections ?? []} />
          <TriggerPanel
            conditions={state?.active_conditions ?? []}
            triggers={state?.active_triggers ?? []}
            stayThreshold={config.stay_duration_sec}
          />
        </div>
        <div style={styles.col}>
          <RiskScorePanel scoring={state?.latest_scoring ?? null} />
          <LatencyPanel latency={state?.latest_latency ?? null} />
          <VLMResultPanel vlm={state?.latest_vlm ?? null} />
          <EventLogPanel history={state?.scoring_history ?? []} />
        </div>
      </div>

      <ConfigPanel config={config} onSave={handleSaveConfig} />

      {state && state.owner_candidates.length > 0 && (
        <div style={{ background: "rgba(59, 130, 246, 0.1)", border: "1px solid rgba(59, 130, 246, 0.2)", borderRadius: 8, padding: 12, color: "#93c5fd", fontSize: 14 }}>
          Owner Excluded Track IDs: {state.owner_candidates.join(", ")}
        </div>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------
// 静止画解析ビュー (Image Analysis)
// --------------------------------------------------------------------------
function ImageAnalysisPanel() {
  const [result, setResult] = useState<SecurityImageAnalysisResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleFile = useCallback(async (file: File) => {
    setError(null); setLoading(true);
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
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <DropZone accept="image/jpeg,image/png" hint="Drag & Drop image (jpg/png)" onFile={handleFile} loading={loading} error={error} />
      {result && (
        <div style={styles.twoCol}>
          <div style={styles.col}>
            <AnnotatedFramePanel b64={result.annotated_image} label="Static Analysis" />
            <DetectionTable detections={result.detections} distances={result.distances} />
          </div>
          <div style={styles.col}>
            <ScoreCard scoring={result.scoring} />
            <VLMCard vlm={result.vlm_result} />
          </div>
        </div>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------
// 動画解析ビュー (Video Analysis)
// --------------------------------------------------------------------------
function VideoAnalysisPanel() {
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
          } else { setError(s.data.error ?? "Error"); }
        }
      } catch {/* ignore */}
    }, 1500);
  }, []);

  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);

  const handleFile = useCallback(async (file: File) => {
    setError(null); setResult(null); setStatus("queued"); setProgress(0);
    try {
      const r = await submitSecurityVideo(file);
      startPoll(r.data.job_id);
    } catch (e) {
      setError(String(e)); setStatus("idle");
    }
  }, [startPoll]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <DropZone accept="video/mp4,video/avi,video/quicktime" hint="Drag & Drop video (mp4/avi/mov)" onFile={handleFile} loading={status === "queued" || status === "processing"} error={error} />
      
      {(status === "queued" || status === "processing") && (
        <div style={{ background: "rgba(255, 255, 255, 0.03)", padding: 16, borderRadius: 12, border: "1px solid rgba(255,255,255,0.05)" }}>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8, fontSize: 13, color: "#94a3b8" }}>
            <span>Processing... ({status})</span>
            <span>{progress}%</span>
          </div>
          <div style={{ background: "rgba(255,255,255,0.1)", borderRadius: 8, height: 6, overflow: "hidden" }}>
            <div style={{ background: "linear-gradient(90deg, #3b82f6, #8b5cf6)", height: "100%", width: `${progress}%`, transition: "width 0.5s ease" }} />
          </div>
        </div>
      )}
      
      {result && <VideoResultPanel result={result} />}
    </div>
  );
}

function VideoResultPanel({ result }: { result: SecurityVideoJobResult }) {
  const [selected, setSelected] = useState<SecurityVideoEvent | null>(result.events[0] ?? null);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ background: "rgba(15, 15, 19, 0.6)", border: "1px solid rgba(255, 255, 255, 0.08)", borderRadius: 12, padding: 16 }}>
        <div style={{ display: "flex", gap: 24, fontSize: 14, color: "#e2e8f0", marginBottom: 16 }}>
          <div>Frames: <span style={{ fontWeight: "bold", color: "#60a5fa" }}>{result.total_frames_processed}</span></div>
          <div>Events: <span style={{ fontWeight: "bold", color: "#a78bfa" }}>{result.events.length}</span></div>
          <div>Notifications: <span style={{ fontWeight: "bold", color: result.notify_count > 0 ? "#f43f5e" : "#34d399" }}>{result.notify_count}</span></div>
        </div>
        
        {result.events.length === 0 ? (
          <p style={{ color: "#64748b", fontSize: 14, margin: 0 }}>No suspicious events detected.</p>
        ) : (
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {result.events.map((ev, i) => (
              <button
                key={i}
                onClick={() => setSelected(ev)}
                style={{
                  background: selected === ev ? "rgba(59, 130, 246, 0.2)" : "rgba(255,255,255,0.03)",
                  border: `1px solid ${selected === ev ? "#3b82f6" : "rgba(255,255,255,0.05)"}`,
                  color: selected === ev ? "#60a5fa" : "#94a3b8",
                  padding: "8px 12px",
                  borderRadius: 8,
                  cursor: "pointer",
                  transition: "all 0.2s",
                }}
              >
                <div style={{ fontSize: 13, fontWeight: "bold" }}>{ev.timestamp_sec.toFixed(1)}s</div>
                <div style={{ fontSize: 11, opacity: 0.8 }}>{ev.vlm_result.label}</div>
              </button>
            ))}
          </div>
        )}
      </div>

      {selected && (
        <div style={styles.twoCol}>
          <div style={styles.col}>
            <AnnotatedFramePanel b64={selected.annotated_image} label={`Event @ ${selected.timestamp_sec.toFixed(1)}s`} />
            <div style={{ background: "rgba(255,255,255,0.02)", padding: 12, borderRadius: 8, fontSize: 13, color: "#94a3b8" }}>
              Distance: <span style={{ color: "#e2e8f0" }}>{selected.trigger.distance_m.toFixed(0)}px</span> | Person ID: <span style={{ color: "#e2e8f0" }}>{selected.trigger.person_track_id}</span>
            </div>
          </div>
          <div style={styles.col}>
            <ScoreCard scoring={selected.scoring} />
            <VLMCard vlm={selected.vlm_result} />
          </div>
        </div>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------
// 共通UIパーツ
// --------------------------------------------------------------------------
function DropZone({ accept, hint, onFile, loading, error }: any) {
  const [drag, setDrag] = useState(false);
  return (
    <div>
      <div
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); const f = e.dataTransfer.files[0]; if (f) onFile(f); }}
        style={{
          border: `2px dashed ${drag ? "#3b82f6" : "rgba(255,255,255,0.1)"}`,
          background: drag ? "rgba(59,130,246,0.05)" : "rgba(255,255,255,0.01)",
          borderRadius: 16,
          padding: "40px 20px",
          textAlign: "center",
          cursor: "pointer",
          transition: "all 0.2s ease",
          display: "flex", flexDirection: "column", alignItems: "center", gap: 12
        }}
      >
        {loading ? (
          <div style={{ color: "#60a5fa", fontWeight: "bold" }}>Processing...</div>
        ) : (
          <>
            <div style={{ fontSize: 24, opacity: 0.5 }}>📁</div>
            <div style={{ color: "#94a3b8", fontSize: 14 }}>{hint}</div>
            <input type="file" accept={accept} onChange={(e) => { const f = e.target.files?.[0]; if (f) onFile(f); }} style={{ color: "#64748b", fontSize: 12 }} />
          </>
        )}
      </div>
      {error && <div style={{ color: "#f87171", fontSize: 13, marginTop: 8 }}>{error}</div>}
    </div>
  );
}

function ScoreCard({ scoring }: any) {
  if (!scoring) return null;
  const isDanger = scoring.risk_score >= 70;
  const color = isDanger ? "#f43f5e" : scoring.risk_score >= 40 ? "#fbbf24" : "#34d399";
  
  return (
    <div style={{ background: "rgba(15, 15, 19, 0.6)", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 12, padding: 16 }}>
      <div style={{ fontSize: 12, color: "#64748b", textTransform: "uppercase", letterSpacing: 1, marginBottom: 8 }}>Risk Score</div>
      <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
        <div style={{ fontSize: 48, fontWeight: 800, color }}>{scoring.risk_score}</div>
        <div style={{ background: scoring.action === "notify" ? "rgba(244, 63, 94, 0.15)" : "rgba(255,255,255,0.05)", color: scoring.action === "notify" ? "#f43f5e" : "#94a3b8", padding: "6px 12px", borderRadius: 8, fontWeight: "bold", fontSize: 13, border: `1px solid ${scoring.action === "notify" ? "rgba(244, 63, 94, 0.3)" : "transparent"}` }}>
          {scoring.action === "notify" ? "🔔 NOTIFY" : "DISCARD"}
        </div>
      </div>
      <div style={{ display: "flex", gap: 12, marginTop: 12 }}>
        {[ { label: "Behavior", val: scoring.behavior_score }, { label: "Context", val: scoring.context_score }, { label: "Persist", val: scoring.persistence_score } ].map(s => (
          <div key={s.label} style={{ background: "rgba(255,255,255,0.03)", borderRadius: 6, padding: "4px 8px", flex: 1, textAlign: "center" }}>
            <div style={{ fontSize: 10, color: "#64748b" }}>{s.label}</div>
            <div style={{ fontSize: 14, color: "#e2e8f0", fontWeight: "bold" }}>{s.val}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function VLMCard({ vlm }: any) {
  if (!vlm) return null;
  return (
    <div style={{ background: "rgba(15, 15, 19, 0.6)", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 12, padding: 16 }}>
      <div style={{ fontSize: 12, color: "#64748b", textTransform: "uppercase", letterSpacing: 1, marginBottom: 8 }}>VLM Analysis</div>
      <div style={{ display: "flex", gap: 8, marginBottom: 8, alignItems: "center" }}>
        <span style={{ background: "rgba(96, 165, 250, 0.15)", color: "#60a5fa", border: "1px solid rgba(96, 165, 250, 0.3)", padding: "4px 10px", borderRadius: 6, fontSize: 13, fontWeight: "bold" }}>
          {vlm.label}
        </span>
        {vlm.is_fallback && <span style={{ background: "rgba(255,255,255,0.1)", color: "#94a3b8", fontSize: 11, padding: "2px 6px", borderRadius: 4 }}>FALLBACK</span>}
      </div>
      <p style={{ margin: 0, fontSize: 14, color: "#cbd5e1", lineHeight: 1.5 }}>{vlm.reason}</p>
    </div>
  );
}

function DetectionTable({ detections, distances }: any) {
  return (
    <div style={{ background: "rgba(15, 15, 19, 0.6)", border: "1px solid rgba(255,255,255,0.08)", borderRadius: 12, padding: 16, marginTop: 16 }}>
      <div style={{ fontSize: 12, color: "#64748b", textTransform: "uppercase", letterSpacing: 1, marginBottom: 12 }}>Detections</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {detections.map((d: any) => (
          <div key={d.track_id} style={{ display: "flex", justifyContent: "space-between", background: "rgba(255,255,255,0.02)", padding: "6px 12px", borderRadius: 6, fontSize: 13 }}>
            <div>
              <span style={{ color: "#94a3b8", marginRight: 8 }}>#{d.track_id}</span>
              <span style={{ color: d.class_name === "person" ? "#fbbf24" : "#60a5fa", fontWeight: "bold" }}>{d.class_name}</span>
            </div>
            <div style={{ color: "#94a3b8" }}>{(d.confidence * 100).toFixed(1)}%</div>
          </div>
        ))}
      </div>
      {distances && distances.length > 0 && (
        <div style={{ marginTop: 12, fontSize: 12, color: "#94a3b8", background: "rgba(255,255,255,0.02)", padding: 8, borderRadius: 6 }}>
          <div style={{ fontWeight: "bold", marginBottom: 4, color: "#64748b" }}>Distances</div>
          {distances.map((d: any, i: number) => (
            <div key={i}>
              Person #{d.person_track_id} ↔ Vehicle #{d.vehicle_track_id}: <span style={{ color: "#e2e8f0" }}>{d.distance_m?.toFixed(0) ?? "N/A"}px</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------
// スタイル
// --------------------------------------------------------------------------
const styles: Record<string, React.CSSProperties> = {
  page: { padding: "32px 48px", maxWidth: 1600, margin: "0 auto", display: "flex", flexDirection: "column", gap: 32 },
  header: { display: "flex", justifyContent: "space-between", alignItems: "flex-end", borderBottom: "1px solid rgba(255,255,255,0.08)", paddingBottom: 24 },
  title: { margin: 0, fontSize: 32, fontWeight: 800, color: "#f8fafc", letterSpacing: "-0.03em" },
  subtitle: { margin: "8px 0 0 0", fontSize: 15, color: "#94a3b8" },
  tabContainer: { display: "flex", gap: 8, background: "rgba(255,255,255,0.03)", padding: 6, borderRadius: 12 },
  tabBtn: { background: "transparent", border: "none", color: "#64748b", padding: "8px 16px", borderRadius: 8, fontSize: 14, fontWeight: "bold", cursor: "pointer", transition: "all 0.2s" },
  tabBtnActive: { background: "rgba(255,255,255,0.1)", color: "#f8fafc", boxShadow: "0 2px 10px rgba(0,0,0,0.1)" },
  content: { display: "flex", flexDirection: "column", gap: 24 },
  controlPanel: { background: "rgba(15, 15, 19, 0.6)", backdropFilter: "blur(12px)", border: "1px solid rgba(255, 255, 255, 0.08)", borderRadius: 16, padding: 20 },
  sourceTab: { background: "rgba(255,255,255,0.05)", border: "1px solid transparent", color: "#94a3b8", padding: "4px 12px", borderRadius: 6, fontSize: 12, fontWeight: "bold", cursor: "pointer" },
  sourceTabActive: { background: "rgba(59, 130, 246, 0.15)", border: "1px solid rgba(59, 130, 246, 0.3)", color: "#60a5fa", padding: "4px 12px", borderRadius: 6, fontSize: 12, fontWeight: "bold" },
  input: { background: "rgba(255,255,255,0.05)", border: "1px solid rgba(255,255,255,0.1)", color: "#f8fafc", borderRadius: 6, padding: "6px 12px", fontSize: 13, outline: "none" },
  actionBtn: { border: "none", color: "#fff", padding: "8px 24px", borderRadius: 8, fontSize: 14, fontWeight: "bold", cursor: "pointer", transition: "transform 0.1s, filter 0.2s", boxShadow: "0 4px 15px rgba(0,0,0,0.2)" },
  twoCol: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24 },
  col: { display: "flex", flexDirection: "column", gap: 16 },
};
