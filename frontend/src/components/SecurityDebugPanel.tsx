import type {
  SecurityDetection,
  ActiveCondition,
  SecurityScoringResult,
  SecurityValidatedOutput,
  SecurityTriggerEvent,
  LatencyInfo,
} from "../api";

// --------------------------------------------------------------------------
// ラベル表示ヘルパー
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

const LABEL_COLORS: Record<string, string> = {
  forced_entry_attempt: "#f38ba8",
  vandalism: "#fab387",
  tampering: "#f9e2af",
  peering: "#a6e3a1",
  approach_fast: "#89dceb",
  circling: "#89b4fa",
  stay_near_vehicle: "#b4befe",
  unknown_behavior: "#6c7086",
};

// --------------------------------------------------------------------------
// 各サブコンポーネント
// --------------------------------------------------------------------------

/** アノテーション済みフレーム */
export function AnnotatedFramePanel({ b64, label }: { b64: string | null; label?: string }) {
  if (!b64) {
    return (
      <div style={styles.placeholder}>
        カメラ映像待機中…
      </div>
    );
  }
  return (
    <div style={{ position: "relative" }}>
      {label && <div style={styles.frameLabel}>{label}</div>}
      <img
        src={`data:image/jpeg;base64,${b64}`}
        alt="annotated"
        style={{ width: "100%", borderRadius: 8, display: "block" }}
      />
    </div>
  );
}

/** 検出リスト */
export function DetectionList({ detections }: { detections: SecurityDetection[] }) {
  return (
    <div style={styles.card}>
      <h3 style={styles.cardTitle}>検出リスト</h3>
      {detections.length === 0 ? (
        <p style={styles.dimText}>検出なし</p>
      ) : (
        <table style={styles.table}>
          <thead>
            <tr>
              <th style={styles.th}>Track ID</th>
              <th style={styles.th}>クラス</th>
              <th style={styles.th}>信頼度</th>
              <th style={styles.th}>オーナー除外</th>
            </tr>
          </thead>
          <tbody>
            {detections.map((d) => (
              <tr key={d.track_id} style={{ opacity: d.owner_excluded ? 0.4 : 1 }}>
                <td style={styles.td}>{d.track_id}</td>
                <td style={styles.td}>
                  <span style={{
                    color: d.class_name === "person" ? "#f9e2af" : "#89b4fa",
                    fontWeight: "bold",
                  }}>
                    {d.class_name}
                  </span>
                </td>
                <td style={styles.td}>{(d.confidence * 100).toFixed(1)}%</td>
                <td style={styles.td}>{d.owner_excluded ? "✓ 除外" : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

/** トリガー状態パネル */
export function TriggerPanel({
  conditions,
  triggers,
  stayThreshold,
}: {
  conditions: ActiveCondition[];
  triggers: SecurityTriggerEvent[];
  stayThreshold: number;
}) {
  return (
    <div style={styles.card}>
      <h3 style={styles.cardTitle}>トリガー状態</h3>

      {conditions.length === 0 ? (
        <p style={styles.dimText}>監視中のペアなし</p>
      ) : (
        conditions.map((c) => {
          const pct = Math.min((c.stay_sec / stayThreshold) * 100, 100);
          return (
            <div key={`${c.person_track_id}-${c.vehicle_track_id}`} style={styles.triggerRow}>
              <div style={styles.triggerMeta}>
                <span>Person #{c.person_track_id} ↔ Vehicle #{c.vehicle_track_id}</span>
                <span style={{ color: c.triggered ? "#a6e3a1" : "#cdd6f4" }}>
                  {c.triggered ? "✓ 成立済" : `${c.stay_sec.toFixed(1)}s / ${stayThreshold}s`}
                </span>
              </div>
              <div style={styles.progressBg}>
                <div style={{
                  ...styles.progressFill,
                  width: `${pct}%`,
                  background: pct >= 100 ? "#a6e3a1" : "#89b4fa",
                }} />
              </div>
            </div>
          );
        })
      )}

      {triggers.length > 0 && (
        <div style={{ marginTop: 8 }}>
          <p style={{ ...styles.dimText, marginBottom: 4 }}>今フレームで成立:</p>
          {triggers.map((t) => (
            <div key={t.triggered_at} style={styles.badge}>
              Person #{t.person_track_id} (repeat: {t.repeat_count}, dist: {t.distance_m.toFixed(0)}px)
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/** VLM 解析結果パネル */
export function VLMResultPanel({ vlm }: { vlm: SecurityValidatedOutput | null }) {
  if (!vlm) {
    return (
      <div style={styles.card}>
        <h3 style={styles.cardTitle}>VLM 解析結果</h3>
        <p style={styles.dimText}>VLM 未実行（トリガー待ち）</p>
      </div>
    );
  }
  const color = LABEL_COLORS[vlm.label] ?? "#cdd6f4";
  return (
    <div style={styles.card}>
      <h3 style={styles.cardTitle}>VLM 解析結果</h3>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
        <span style={{ ...styles.labelBadge, background: color, color: "#1e1e2e" }}>
          {LABEL_NAMES[vlm.label] ?? vlm.label}
        </span>
        {vlm.is_fallback && (
          <span style={{ ...styles.labelBadge, background: "#6c7086", color: "#cdd6f4", fontSize: 11 }}>
            FALLBACK
          </span>
        )}
      </div>
      <p style={{ color: "#cdd6f4", fontSize: 13, marginBottom: 8 }}>{vlm.reason}</p>
      <details>
        <summary style={{ color: "#6c7086", fontSize: 12, cursor: "pointer" }}>生出力</summary>
        <pre style={styles.pre}>{vlm.raw_output}</pre>
      </details>
    </div>
  );
}

/** リスクスコアメーター */
export function RiskScorePanel({ scoring }: { scoring: SecurityScoringResult | null }) {
  if (!scoring) {
    return (
      <div style={styles.card}>
        <h3 style={styles.cardTitle}>リスクスコア</h3>
        <p style={styles.dimText}>スコアなし</p>
      </div>
    );
  }

  const pct = scoring.risk_score;
  const meterColor = pct >= 70 ? "#f38ba8" : pct >= 40 ? "#f9e2af" : "#a6e3a1";

  return (
    <div style={styles.card}>
      <h3 style={styles.cardTitle}>リスクスコア</h3>

      <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 12 }}>
        <span style={{ fontSize: 48, fontWeight: "bold", color: meterColor }}>
          {scoring.risk_score}
        </span>
        <div>
          <div style={{
            ...styles.labelBadge,
            background: scoring.action === "notify" ? "#f38ba8" : "#313244",
            color: scoring.action === "notify" ? "#1e1e2e" : "#cdd6f4",
            fontSize: 14,
          }}>
            {scoring.action === "notify" ? "🔔 通知" : "— 通知なし"}
          </div>
        </div>
      </div>

      {/* スコアバー */}
      <div style={styles.progressBg}>
        <div style={{ ...styles.progressFill, width: `${pct}%`, background: meterColor }} />
      </div>
      <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
        <ScoreChip label="行動" value={scoring.behavior_score} color="#89b4fa" />
        <ScoreChip label="環境" value={scoring.context_score} color="#a6e3a1" />
        <ScoreChip label="継続" value={scoring.persistence_score} color="#f9e2af" />
      </div>
      <p style={{ fontSize: 12, color: "#6c7086", marginTop: 8 }}>
        ラベル: {LABEL_NAMES[scoring.label] ?? scoring.label}
      </p>
    </div>
  );
}

function ScoreChip({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div style={{ background: "#313244", borderRadius: 6, padding: "4px 10px", textAlign: "center" }}>
      <div style={{ fontSize: 11, color: "#6c7086" }}>{label}</div>
      <div style={{ fontSize: 20, fontWeight: "bold", color }}>{value}</div>
    </div>
  );
}

/** レイテンシ計測パネル */
export function LatencyPanel({ latency }: { latency: LatencyInfo | null }) {
  if (!latency) {
    return (
      <div style={styles.card}>
        <h3 style={styles.cardTitle}>レイテンシ計測</h3>
        <p style={styles.dimText}>計測待ち（トリガー未成立）</p>
      </div>
    );
  }

  const rows: { label: string; value: string; color?: string }[] = [
    { label: "キュー待機", value: `${latency.queue_wait_ms} ms`, color: "#89b4fa" },
    { label: "VLM 推論", value: `${latency.vlm_latency_ms} ms`, color: "#f9e2af" },
    { label: "トリガー → 完了", value: `${latency.total_latency_ms} ms`, color: "#a6e3a1" },
  ];

  const totalBar = Math.min(latency.total_latency_ms, 10000); // 10秒を100%とする
  const queuePct  = (latency.queue_wait_ms / totalBar) * 100;
  const vlmPct    = (latency.vlm_latency_ms / totalBar) * 100;

  return (
    <div style={styles.card}>
      <h3 style={styles.cardTitle}>レイテンシ計測</h3>

      {/* 内訳バー */}
      <div style={{ marginBottom: 12 }}>
        <div style={{ fontSize: 11, color: "#6c7086", marginBottom: 4 }}>内訳（キュー待機 + VLM 推論）</div>
        <div style={{ display: "flex", height: 16, borderRadius: 4, overflow: "hidden", background: "#313244" }}>
          <div style={{ width: `${queuePct}%`, background: "#89b4fa", transition: "width 0.3s" }} title={`キュー待機: ${latency.queue_wait_ms}ms`} />
          <div style={{ width: `${vlmPct}%`, background: "#f9e2af", transition: "width 0.3s" }} title={`VLM推論: ${latency.vlm_latency_ms}ms`} />
        </div>
        <div style={{ display: "flex", gap: 12, marginTop: 4, fontSize: 11, color: "#6c7086" }}>
          <span style={{ color: "#89b4fa" }}>■ キュー待機</span>
          <span style={{ color: "#f9e2af" }}>■ VLM 推論</span>
        </div>
      </div>

      {/* 数値一覧 */}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        {rows.map((r) => (
          <div key={r.label} style={{ background: "#313244", borderRadius: 6, padding: "6px 12px", minWidth: 100 }}>
            <div style={{ fontSize: 11, color: "#6c7086" }}>{r.label}</div>
            <div style={{ fontSize: 20, fontWeight: "bold", color: r.color ?? "#cdd6f4" }}>{r.value}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

/** イベントログ（直近10件） */
export function EventLogPanel({ history }: { history: SecurityScoringResult[] }) {
  return (
    <div style={styles.card}>
      <h3 style={styles.cardTitle}>イベントログ（直近{history.length}件）</h3>
      {history.length === 0 ? (
        <p style={styles.dimText}>イベントなし</p>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          {[...history].reverse().map((s, i) => {
            const color = LABEL_COLORS[s.label] ?? "#cdd6f4";
            return (
              <div key={i} style={styles.logRow}>
                <span style={{ ...styles.labelBadge, background: color, color: "#1e1e2e", flexShrink: 0 }}>
                  {LABEL_NAMES[s.label] ?? s.label}
                </span>
                <span style={{ color: "#cdd6f4" }}>score: {s.risk_score}</span>
                <span style={{
                  color: s.action === "notify" ? "#f38ba8" : "#6c7086",
                  fontWeight: s.action === "notify" ? "bold" : "normal",
                }}>
                  {s.action === "notify" ? "通知" : "破棄"}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

/** 設定パネル */
export function ConfigPanel({
  config,
  onSave,
}: {
  config: { threshold: number; distance_threshold_m: number; stay_duration_sec: number };
  onSave: (v: typeof config) => void;
}) {
  return (
    <div style={styles.card}>
      <h3 style={styles.cardTitle}>設定</h3>
      <div style={{ display: "flex", gap: 24, flexWrap: "wrap" }}>
        <ConfigField
          label="通知閾値 (0-100)"
          type="number"
          defaultValue={config.threshold}
          onBlur={(v) => onSave({ ...config, threshold: Number(v) })}
        />
        <ConfigField
          label="距離閾値 (m / px)"
          type="number"
          defaultValue={config.distance_threshold_m}
          onBlur={(v) => onSave({ ...config, distance_threshold_m: Number(v) })}
        />
        <ConfigField
          label="滞在判定 (秒)"
          type="number"
          defaultValue={config.stay_duration_sec}
          onBlur={(v) => onSave({ ...config, stay_duration_sec: Number(v) })}
        />
      </div>
    </div>
  );
}

function ConfigField({
  label,
  type,
  defaultValue,
  onBlur,
}: {
  label: string;
  type: string;
  defaultValue: number;
  onBlur: (v: string) => void;
}) {
  return (
    <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <span style={{ fontSize: 12, color: "#6c7086" }}>{label}</span>
      <input
        type={type}
        defaultValue={defaultValue}
        onBlur={(e) => onBlur(e.target.value)}
        style={styles.input}
      />
    </label>
  );
}

// --------------------------------------------------------------------------
// スタイル
// --------------------------------------------------------------------------

const styles: Record<string, React.CSSProperties> = {
  card: {
    background: "rgba(15, 15, 19, 0.6)",
    backdropFilter: "blur(12px)",
    borderRadius: 16,
    padding: 20,
    border: "1px solid rgba(255, 255, 255, 0.08)",
    boxShadow: "0 8px 32px rgba(0, 0, 0, 0.2)",
  },
  cardTitle: {
    margin: "0 0 16px",
    fontSize: 13,
    fontWeight: "bold",
    color: "#94a3b8",
    textTransform: "uppercase",
    letterSpacing: 1.5,
  },
  dimText: {
    color: "#64748b",
    fontSize: 14,
    margin: 0,
  },
  table: {
    width: "100%",
    borderCollapse: "collapse",
    fontSize: 13,
  },
  th: {
    textAlign: "left",
    color: "#64748b",
    fontWeight: "bold",
    padding: "8px 12px",
    borderBottom: "1px solid rgba(255, 255, 255, 0.05)",
    textTransform: "uppercase",
    fontSize: 11,
    letterSpacing: 1,
  },
  td: {
    padding: "10px 12px",
    color: "#e2e8f0",
    borderBottom: "1px solid rgba(255, 255, 255, 0.02)",
  },
  triggerRow: {
    marginBottom: 16,
  },
  triggerMeta: {
    display: "flex",
    justifyContent: "space-between",
    fontSize: 13,
    color: "#e2e8f0",
    marginBottom: 8,
    fontWeight: 500,
  },
  progressBg: {
    background: "rgba(255, 255, 255, 0.05)",
    borderRadius: 8,
    height: 6,
    overflow: "hidden",
  },
  progressFill: {
    height: "100%",
    borderRadius: 8,
    transition: "width 0.4s cubic-bezier(0.4, 0, 0.2, 1)",
  },
  badge: {
    display: "inline-block",
    background: "rgba(255, 255, 255, 0.05)",
    border: "1px solid rgba(255, 255, 255, 0.1)",
    borderRadius: 6,
    padding: "4px 10px",
    fontSize: 12,
    color: "#fbbf24",
    marginRight: 8,
    marginBottom: 6,
  },
  labelBadge: {
    display: "inline-block",
    borderRadius: 6,
    padding: "4px 12px",
    fontSize: 12,
    fontWeight: "bold",
    textTransform: "uppercase",
    letterSpacing: 0.5,
  },
  pre: {
    background: "rgba(0, 0, 0, 0.3)",
    border: "1px solid rgba(255, 255, 255, 0.05)",
    borderRadius: 8,
    padding: 12,
    fontSize: 12,
    color: "#94a3b8",
    overflowX: "auto",
    marginTop: 8,
    maxHeight: 150,
    overflowY: "auto",
    fontFamily: "'Fira Code', monospace",
  },
  logRow: {
    display: "flex",
    alignItems: "center",
    gap: 12,
    fontSize: 13,
    padding: "8px 0",
    borderBottom: "1px solid rgba(255, 255, 255, 0.03)",
  },
  input: {
    background: "rgba(255, 255, 255, 0.05)",
    border: "1px solid rgba(255, 255, 255, 0.1)",
    borderRadius: 6,
    color: "#f8fafc",
    padding: "6px 12px",
    fontSize: 13,
    width: 120,
    outline: "none",
    transition: "border-color 0.2s",
  },
  placeholder: {
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    height: 280,
    background: "rgba(15, 15, 19, 0.4)",
    borderRadius: 12,
    color: "#64748b",
    fontSize: 14,
    border: "2px dashed rgba(255, 255, 255, 0.1)",
  },
  frameLabel: {
    position: "absolute",
    top: 12,
    left: 12,
    background: "rgba(0, 0, 0, 0.7)",
    backdropFilter: "blur(4px)",
    color: "#f8fafc",
    borderRadius: 6,
    padding: "4px 12px",
    fontSize: 12,
    fontWeight: "bold",
    border: "1px solid rgba(255, 255, 255, 0.1)",
  },
};
