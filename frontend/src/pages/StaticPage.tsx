import { useState, useRef, useCallback } from "react";
import { analyzeImage, submitVideo, getVideoStatus, getVideoResult } from "../api";
import type { ImageAnalysisResult, VideoJobResult } from "../api";

export default function StaticPage() {
  return (
    <div style={styles.page}>
      <ImageSection />
      <VideoSection />
    </div>
  );
}

// ---- Image Section ----

function ImageSection() {
  const [result, setResult] = useState<ImageAnalysisResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);

  const handleFile = useCallback(async (file: File) => {
    setError(null);
    setLoading(true);
    try {
      const res = await analyzeImage(file);
      setResult(res.data);
    } catch (e: unknown) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files[0];
    if (file) handleFile(file);
  };

  return (
    <section style={styles.section}>
      <h2 style={styles.h2}>📷 画像解析</h2>

      <div
        style={{ ...styles.dropzone, ...(dragging ? styles.dropzoneDrag : {}) }}
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
      >
        <p>画像をここにドラッグ&ドロップ (jpg / png)</p>
        <input
          type="file"
          accept="image/jpeg,image/png"
          onChange={(e) => { const f = e.target.files?.[0]; if (f) handleFile(f); }}
          style={{ color: "#cdd6f4" }}
        />
      </div>

      {loading && <p style={styles.info}>⏳ 解析中...</p>}
      {error && <p style={styles.error}>❌ {error}</p>}

      {result && (
        <div style={styles.resultBox}>
          <img
            src={`data:image/jpeg;base64,${result.annotated_image}`}
            alt="annotated"
            style={styles.resultImg}
          />
          <div style={styles.resultText}>
            <p><b>検出数:</b> {result.detection_count}</p>
            <p><b>VLM 結果:</b> {result.vlm_result}</p>
            <details>
              <summary>検出詳細 ({result.detections.length}件)</summary>
              <ul>
                {result.detections.map((d, i) => (
                  <li key={i}>
                    {d.label} ({(d.confidence * 100).toFixed(1)}%)
                  </li>
                ))}
              </ul>
            </details>
          </div>
        </div>
      )}
    </section>
  );
}

// ---- Video Section ----

function VideoSection() {
  const [_jobId, setJobId] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const [status, setStatus] = useState<string>("");
  const [videoResult, setVideoResult] = useState<VideoJobResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const handleFile = async (file: File) => {
    setError(null);
    setLoading(true);
    setVideoResult(null);
    setProgress(0);
    setStatus("queued");

    try {
      const res = await submitVideo(file);
      const id = res.data.job_id;
      setJobId(id);

      intervalRef.current = setInterval(async () => {
        try {
          const statusRes = await getVideoStatus(id);
          setProgress(statusRes.data.progress);
          setStatus(statusRes.data.status);

          if (statusRes.data.status === "done") {
            clearInterval(intervalRef.current!);
            const resultRes = await getVideoResult(id);
            setVideoResult(resultRes.data);
            setLoading(false);
          } else if (statusRes.data.status === "error") {
            clearInterval(intervalRef.current!);
            setError("動画解析中にエラーが発生しました");
            setLoading(false);
          }
        } catch (e: unknown) {
          clearInterval(intervalRef.current!);
          setError(String(e));
          setLoading(false);
        }
      }, 2000);
    } catch (e: unknown) {
      setError(String(e));
      setLoading(false);
    }
  };

  return (
    <section style={styles.section}>
      <h2 style={styles.h2}>🎬 動画解析</h2>

      <input
        type="file"
        accept="video/mp4,video/avi,video/quicktime"
        onChange={(e) => { const f = e.target.files?.[0]; if (f) handleFile(f); }}
        style={{ color: "#cdd6f4" }}
        disabled={loading}
      />

      {loading && (
        <div style={{ marginTop: 12 }}>
          <p style={styles.info}>⏳ {status} ({progress}%)</p>
          <div style={styles.progressBg}>
            <div style={{ ...styles.progressBar, width: `${progress}%` }} />
          </div>
        </div>
      )}

      {error && <p style={styles.error}>❌ {error}</p>}

      {videoResult && (
        <div>
          <p style={styles.info}>✅ 解析完了 — {videoResult.frames.length} フレーム</p>
          <div style={styles.framesGrid}>
            {videoResult.frames.map((f, i) => (
              <div key={i} style={styles.frameCard}>
                <img
                  src={`data:image/jpeg;base64,${f.annotated_image}`}
                  alt={`frame-${i}`}
                  style={styles.frameImg}
                />
                <p style={{ fontSize: 11 }}>
                  {f.timestamp.toFixed(2)}s | {f.detections.length} det.
                </p>
                <p style={{ fontSize: 11 }}>{f.vlm_result}</p>
              </div>
            ))}
          </div>
        </div>
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
  dropzone: {
    border: "2px dashed #45475a",
    borderRadius: 8,
    padding: 20,
    textAlign: "center",
    color: "#a6adc8",
    cursor: "pointer",
    transition: "border-color .2s",
  },
  dropzoneDrag: { borderColor: "#89b4fa" },
  info: { color: "#a6e3a1", marginTop: 8 },
  error: { color: "#f38ba8" },
  resultBox: {
    display: "flex",
    gap: 20,
    marginTop: 16,
    flexWrap: "wrap",
  },
  resultImg: { maxWidth: 480, borderRadius: 6, border: "1px solid #45475a" },
  resultText: { flex: 1, color: "#cdd6f4", minWidth: 200 },
  progressBg: {
    background: "#313244",
    borderRadius: 4,
    height: 12,
    width: "100%",
    marginTop: 4,
  },
  progressBar: {
    background: "#89b4fa",
    height: "100%",
    borderRadius: 4,
    transition: "width .4s",
  },
  framesGrid: {
    display: "flex",
    flexWrap: "wrap",
    gap: 12,
    marginTop: 16,
  },
  frameCard: {
    background: "#313244",
    borderRadius: 6,
    padding: 8,
    width: 180,
    color: "#cdd6f4",
  },
  frameImg: { width: "100%", borderRadius: 4 },
};
