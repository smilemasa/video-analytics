import { useState, useRef, useEffect, useCallback } from "react";
import { startCamera, stopCamera, getCameraStatus } from "../api";
import type { Detection, CameraSourceType } from "../api";

const WS_URL = `ws://${location.host}/ws/live`;
const FRAME_INTERVAL_MS = 100; // 10fps

export default function LivePage() {
  return (
    <div style={styles.page}>
      <BrowserCameraSection />
      <ServerCameraSection />
    </div>
  );
}

// ---- Browser Webcam via WebSocket ----

function BrowserCameraSection() {
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const [active, setActive] = useState(false);
  const [annotatedImg, setAnnotatedImg] = useState<string | null>(null);
  const [detections, setDetections] = useState<Detection[]>([]);
  const [vlmResult, setVlmResult] = useState("");
  const [fps, setFps] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const start = useCallback(async () => {
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: true });
      if (videoRef.current) videoRef.current.srcObject = stream;

      const ws = new WebSocket(WS_URL);
      ws.binaryType = "arraybuffer";
      wsRef.current = ws;

      ws.onopen = () => {
        setActive(true);
        timerRef.current = setInterval(() => {
          if (!canvasRef.current || !videoRef.current || ws.readyState !== WebSocket.OPEN) return;
          const ctx = canvasRef.current.getContext("2d")!;
          canvasRef.current.width = videoRef.current.videoWidth || 320;
          canvasRef.current.height = videoRef.current.videoHeight || 240;
          ctx.drawImage(videoRef.current, 0, 0);
          canvasRef.current.toBlob(
            (blob) => {
              if (!blob) return;
              blob.arrayBuffer().then((buf) => {
                if (ws.readyState === WebSocket.OPEN) {
                  // Convert to base64
                  const bytes = new Uint8Array(buf);
                  let binary = "";
                  for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
                  const b64 = btoa(binary);
                  ws.send(JSON.stringify({ frame: b64 }));
                }
              });
            },
            "image/jpeg",
            0.7
          );
        }, FRAME_INTERVAL_MS);
      };

      ws.onmessage = (evt) => {
        const data = JSON.parse(evt.data);
        setAnnotatedImg(data.annotated_image);
        setDetections(data.detections ?? []);
        setVlmResult(data.vlm_result ?? "");
        setFps(data.fps ?? 0);
      };

      ws.onerror = () => setError("WebSocket エラー");
      ws.onclose = () => setActive(false);
    } catch (e: unknown) {
      setError(String(e));
    }
  }, []);

  const stop = useCallback(() => {
    if (timerRef.current) clearInterval(timerRef.current);
    wsRef.current?.close();
    if (videoRef.current?.srcObject) {
      (videoRef.current.srcObject as MediaStream).getTracks().forEach((t) => t.stop());
      videoRef.current.srcObject = null;
    }
    setActive(false);
    setAnnotatedImg(null);
  }, []);

  useEffect(() => () => stop(), [stop]);

  return (
    <section style={styles.section}>
      <h2 style={styles.h2}>📹 ブラウザカメラ (WebSocket)</h2>

      <div style={styles.row}>
        <button onClick={active ? stop : start} style={active ? styles.btnRed : styles.btnGreen}>
          {active ? "停止" : "カメラ起動"}
        </button>
        {active && <span style={styles.badge}>FPS: {fps.toFixed(1)}</span>}
      </div>

      {error && <p style={styles.error}>❌ {error}</p>}

      <div style={styles.videoGrid}>
        <div>
          <p style={styles.caption}>カメラ映像</p>
          <video ref={videoRef} autoPlay muted style={styles.video} />
          <canvas ref={canvasRef} style={{ display: "none" }} />
        </div>

        {annotatedImg && (
          <div>
            <p style={styles.caption}>解析結果</p>
            <img
              src={`data:image/jpeg;base64,${annotatedImg}`}
              alt="annotated"
              style={styles.video}
            />
          </div>
        )}
      </div>

      {vlmResult && (
        <p style={styles.vlm}>
          <b>VLM:</b> {vlmResult}
        </p>
      )}

      {detections.length > 0 && (
        <p style={styles.info}>
          検出: {detections.map((d) => `${d.label} (${(d.confidence * 100).toFixed(0)}%)`).join(", ")}
        </p>
      )}
    </section>
  );
}

// ---- Server Camera via SSE ----

function ServerCameraSection() {
  const [sourceType, setSourceType] = useState<CameraSourceType>("usb");
  // USB
  const [cameraIndex, setCameraIndex] = useState(0);
  // RTSP
  const [rtspUrl, setRtspUrl] = useState("rtsp://");
  // ONVIF
  const [onvifHost, setOnvifHost] = useState("");
  const [onvifPort, setOnvifPort] = useState(80);
  const [onvifUser, setOnvifUser] = useState("");
  const [onvifPassword, setOnvifPassword] = useState("");
  const [onvifProfile, setOnvifProfile] = useState(0);

  const [active, setActive] = useState(false);
  const [sourceLabel, setSourceLabel] = useState("");
  const [annotatedImg, setAnnotatedImg] = useState<string | null>(null);
  const [detections, setDetections] = useState<Detection[]>([]);
  const [vlmResult, setVlmResult] = useState("");
  const [error, setError] = useState<string | null>(null);
  const esRef = useRef<EventSource | null>(null);

  // Sync with server camera status on mount
  useEffect(() => {
    getCameraStatus().then((r) => {
      setActive(r.data.active);
      if (r.data.source_type) setSourceType(r.data.source_type as CameraSourceType);
      if (r.data.source_label) setSourceLabel(r.data.source_label);
    }).catch(() => {});
  }, []);

  const start = async () => {
    setError(null);
    try {
      let res;
      if (sourceType === "usb") {
        res = await startCamera({ source_type: "usb", camera_index: cameraIndex });
      } else if (sourceType === "rtsp") {
        res = await startCamera({ source_type: "rtsp", rtsp_url: rtspUrl });
      } else {
        res = await startCamera({
          source_type: "onvif",
          onvif_host: onvifHost,
          onvif_port: onvifPort,
          onvif_user: onvifUser,
          onvif_password: onvifPassword,
          onvif_profile: onvifProfile,
        });
      }
      setActive(true);
      setSourceLabel(res.data.source_label);

      const es = new EventSource("/api/live/camera/stream");
      esRef.current = es;
      es.onmessage = (evt) => {
        const data = JSON.parse(evt.data);
        setAnnotatedImg(data.annotated_image);
        setDetections(data.detections ?? []);
        setVlmResult(data.vlm_result ?? "");
      };
      es.onerror = () => {
        setError("SSE 接続エラー");
        es.close();
      };
    } catch (e: unknown) {
      setError(String(e));
    }
  };

  const stop = async () => {
    esRef.current?.close();
    esRef.current = null;
    try { await stopCamera(); } catch { /* ignore */ }
    setActive(false);
    setAnnotatedImg(null);
    setSourceLabel("");
  };

  useEffect(() => () => { esRef.current?.close(); }, []);

  const sourceLabels: Record<CameraSourceType, string> = {
    usb: "🔌 USB カメラ",
    rtsp: "📡 RTSP",
    onvif: "🌐 ONVIF",
  };

  return (
    <section style={styles.section}>
      <h2 style={styles.h2}>🖥️ サーバーカメラ (SSE)</h2>

      {/* ソースタイプ選択タブ */}
      <div style={styles.tabs}>
        {(["usb", "rtsp", "onvif"] as CameraSourceType[]).map((t) => (
          <button
            key={t}
            onClick={() => !active && setSourceType(t)}
            disabled={active}
            style={sourceType === t ? styles.tabActive : styles.tab}
          >
            {sourceLabels[t]}
          </button>
        ))}
      </div>

      {/* USB 設定 */}
      {sourceType === "usb" && (
        <div style={styles.formRow}>
          <label style={styles.label}>
            カメラ番号&nbsp;
            <input
              type="number" min={0} value={cameraIndex}
              onChange={(e) => setCameraIndex(Number(e.target.value))}
              style={{ width: 60, ...styles.input }} disabled={active}
            />
          </label>
        </div>
      )}

      {/* RTSP 設定 */}
      {sourceType === "rtsp" && (
        <div style={styles.formRow}>
          <label style={styles.label}>
            RTSP URL&nbsp;
            <input
              type="text" value={rtspUrl}
              onChange={(e) => setRtspUrl(e.target.value)}
              placeholder="rtsp://user:pass@192.168.1.10:554/stream"
              style={{ width: 380, ...styles.input }} disabled={active}
            />
          </label>
        </div>
      )}

      {/* ONVIF 設定 */}
      {sourceType === "onvif" && (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <div style={styles.formRow}>
            <label style={styles.label}>
              ホスト&nbsp;
              <input type="text" value={onvifHost} onChange={(e) => setOnvifHost(e.target.value)}
                placeholder="192.168.1.10" style={{ width: 160, ...styles.input }} disabled={active} />
            </label>
            <label style={styles.label}>
              ポート&nbsp;
              <input type="number" value={onvifPort} onChange={(e) => setOnvifPort(Number(e.target.value))}
                style={{ width: 70, ...styles.input }} disabled={active} />
            </label>
            <label style={styles.label}>
              プロファイル&nbsp;
              <input type="number" min={0} value={onvifProfile} onChange={(e) => setOnvifProfile(Number(e.target.value))}
                style={{ width: 50, ...styles.input }} disabled={active} />
            </label>
          </div>
          <div style={styles.formRow}>
            <label style={styles.label}>
              ユーザー名&nbsp;
              <input type="text" value={onvifUser} onChange={(e) => setOnvifUser(e.target.value)}
                style={{ width: 140, ...styles.input }} disabled={active} />
            </label>
            <label style={styles.label}>
              パスワード&nbsp;
              <input type="password" value={onvifPassword} onChange={(e) => setOnvifPassword(e.target.value)}
                style={{ width: 140, ...styles.input }} disabled={active} />
            </label>
          </div>
        </div>
      )}

      <div style={{ ...styles.row, marginTop: 10 }}>
        <button onClick={active ? stop : start} style={active ? styles.btnRed : styles.btnGreen}>
          {active ? "停止" : "接続開始"}
        </button>
        {active && sourceLabel && (
          <span style={styles.badge} title={sourceLabel}>
            ▶ {sourceLabel.length > 50 ? sourceLabel.slice(0, 50) + "…" : sourceLabel}
          </span>
        )}
      </div>

      {error && <p style={styles.error}>❌ {error}</p>}

      {annotatedImg && (
        <div>
          <p style={styles.caption}>解析結果</p>
          <img
            src={`data:image/jpeg;base64,${annotatedImg}`}
            alt="server-annotated"
            style={styles.video}
          />
        </div>
      )}

      {vlmResult && (
        <p style={styles.vlm}><b>VLM:</b> {vlmResult}</p>
      )}

      {detections.length > 0 && (
        <p style={styles.info}>
          検出: {detections.map((d) => `${d.label} (${(d.confidence * 100).toFixed(0)}%)`).join(", ")}
        </p>
      )}
    </section>
  );
}

const styles: Record<string, React.CSSProperties> = {
  page: { padding: 20, display: "flex", flexDirection: "column", gap: 32 },
  section: {
    background: "#181825",
    borderRadius: 8,
    padding: 20,
    border: "1px solid #313244",
  },
  h2: { color: "#89b4fa", marginTop: 0 },
  tabs: { display: "flex", gap: 6, marginBottom: 12 },
  tab: {
    background: "#313244",
    color: "#a6adc8",
    border: "1px solid #45475a",
    borderRadius: 4,
    padding: "4px 14px",
    cursor: "pointer",
    fontSize: 13,
  },
  tabActive: {
    background: "#89b4fa",
    color: "#1e1e2e",
    border: "1px solid #89b4fa",
    borderRadius: 4,
    padding: "4px 14px",
    cursor: "default",
    fontSize: 13,
    fontWeight: "bold",
  },
  formRow: { display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap", marginBottom: 4 },
  label: { color: "#cdd6f4", fontSize: 13, display: "flex", alignItems: "center", gap: 4 },
  row: { display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap", marginBottom: 12 },
  btnGreen: {
    background: "#a6e3a1",
    color: "#1e1e2e",
    border: "none",
    borderRadius: 4,
    padding: "6px 16px",
    cursor: "pointer",
    fontWeight: "bold",
  },
  btnRed: {
    background: "#f38ba8",
    color: "#1e1e2e",
    border: "none",
    borderRadius: 4,
    padding: "6px 16px",
    cursor: "pointer",
    fontWeight: "bold",
  },
  badge: {
    background: "#313244",
    color: "#89b4fa",
    borderRadius: 4,
    padding: "2px 8px",
    fontSize: 12,
    maxWidth: 420,
    overflow: "hidden",
    whiteSpace: "nowrap",
    textOverflow: "ellipsis",
  },
  error: { color: "#f38ba8" },
  info: { color: "#a6e3a1", fontSize: 13 },
  vlm: { color: "#cdd6f4", marginTop: 8, fontSize: 14 },
  caption: { color: "#a6adc8", fontSize: 12, marginBottom: 4 },
  video: {
    maxWidth: 480,
    borderRadius: 6,
    border: "1px solid #45475a",
    display: "block",
  },
  videoGrid: { display: "flex", gap: 20, flexWrap: "wrap" },
  input: {
    background: "#313244",
    color: "#cdd6f4",
    border: "1px solid #45475a",
    borderRadius: 4,
    padding: "2px 6px",
  },
};
