import axios from "axios";

const api = axios.create({
  baseURL: "",
});

export default api;

// ---- Types ----

export interface ModelStatus {
  model_id: string;
  status: "loaded" | "loading" | "error";
}

export interface YoloClasses {
  mode: string;
  classes: number[];
}

export interface Detection {
  class_id: number;
  label: string;
  confidence: number;
  bbox: [number, number, number, number];
}

export interface ImageAnalysisResult {
  annotated_image: string;
  detections: Detection[];
  vlm_result: string;
  detection_count: number;
}

export interface VideoJob {
  job_id: string;
  status: string;
}

export interface VideoJobStatus {
  job_id: string;
  status: "queued" | "processing" | "done" | "error";
  progress: number;
}

export interface FrameResult {
  timestamp: number;
  annotated_image: string;
  detections: Detection[];
  vlm_result: string;
}

export interface VideoJobResult {
  job_id: string;
  status: string;
  frames: FrameResult[];
}

export interface CameraStatus {
  active: boolean;
  source_type?: string;
  source_label?: string;
  fps?: number;
}

export interface CameraStartResult {
  active: boolean;
  source_type: string;
  source_label: string;
}

export type CameraSourceType = "usb" | "rtsp" | "onvif";

export interface CameraStartParams {
  source_type: CameraSourceType;
  // USB
  camera_index?: number;
  // RTSP
  rtsp_url?: string;
  // ONVIF
  onvif_host?: string;
  onvif_port?: number;
  onvif_user?: string;
  onvif_password?: string;
  onvif_profile?: number;
}

// ---- API helpers ----

export const getHealth = () => api.get<{ status: string }>("/api/health");
export const getModels = () => api.get<{ models: string[] }>("/api/models");

export const getModelStatus = () => api.get<ModelStatus>("/api/settings/model");
export const switchModel = (model_id: string) =>
  api.post<ModelStatus>("/api/settings/model", { model_id });

export const getYoloClasses = () =>
  api.get<YoloClasses>("/api/settings/yolo-classes");
export const setYoloClasses = (mode: string, classes: number[]) =>
  api.post<YoloClasses>("/api/settings/yolo-classes", { mode, classes });

export const getPrompt = () =>
  api.get<{ prompt: string }>("/api/settings/prompt");
export const setPrompt = (prompt: string) =>
  api.put<{ prompt: string }>("/api/settings/prompt", { prompt });

export const analyzeImage = (file: File) => {
  const form = new FormData();
  form.append("file", file);
  return api.post<ImageAnalysisResult>("/api/static/image", form);
};

export const submitVideo = (file: File) => {
  const form = new FormData();
  form.append("file", file);
  return api.post<VideoJob>("/api/static/video", form);
};

export const getVideoStatus = (job_id: string) =>
  api.get<VideoJobStatus>(`/api/static/video/${job_id}/status`);

export const getVideoResult = (job_id: string) =>
  api.get<VideoJobResult>(`/api/static/video/${job_id}/result`);

export const getCameraStatus = () =>
  api.get<CameraStatus>("/api/live/camera/status");
export const startCamera = (params: CameraStartParams) =>
  api.post<CameraStartResult>("/api/live/camera/start", params);
export const stopCamera = () =>
  api.post<CameraStatus>("/api/live/camera/stop");

// ---- Security ----

export type SecurityLabel =
  | "forced_entry_attempt"
  | "vandalism"
  | "tampering"
  | "peering"
  | "approach_fast"
  | "circling"
  | "stay_near_vehicle"
  | "unknown_behavior";

export interface SecurityDetection {
  track_id: number;
  class_id: number;
  class_name: "person" | "vehicle";
  bbox: [number, number, number, number];
  confidence: number;
  owner_excluded: boolean;
}

export interface SecurityDistance {
  person_track_id: number;
  vehicle_track_id: number;
  distance_m: number | null;
}

export interface ActiveCondition {
  person_track_id: number;
  vehicle_track_id: number;
  stay_sec: number;
  triggered: boolean;
}

export interface SecurityTriggerEvent {
  person_track_id: number;
  vehicle_track_id: number;
  distance_m: number;
  stay_duration_sec: number;
  triggered_at: number;
  repeat_count: number;
}

export interface SecurityValidatedOutput {
  label: SecurityLabel;
  reason: string;
  is_fallback: boolean;
  raw_output: string;
}

export interface SecurityScoringResult {
  risk_score: number;
  behavior_score: number;
  context_score: number;
  persistence_score: number;
  action: "notify" | "discard";
  label: SecurityLabel;
  reason: string;
}

export interface LatencyInfo {
  trigger_at_ms: number;
  submitted_at_ms: number;
  vlm_start_ms: number;
  vlm_end_ms: number;
  scoring_at_ms: number;
  queue_wait_ms: number;
  vlm_latency_ms: number;
  total_latency_ms: number;
}

export interface OfflineResult {
  source: "image" | "video";
  annotated_image: string | null;
  detections: SecurityDetection[];
  distances: SecurityDistance[];
  vlm_result: SecurityValidatedOutput | null;
  scoring: SecurityScoringResult | null;
  job_id?: string;
  timestamp_sec?: number;
  frame_id?: number;
  total_events?: number;
}

export interface SecurityPipelineState {
  timestamp_ms: number;
  detections: SecurityDetection[];
  distances: SecurityDistance[];
  active_conditions: ActiveCondition[];
  active_triggers: SecurityTriggerEvent[];
  owner_candidates: number[];
  latest_vlm: SecurityValidatedOutput | null;
  latest_scoring: SecurityScoringResult | null;
  latest_latency: LatencyInfo | null;
  scoring_history: SecurityScoringResult[];
  annotated_image: string | null;
  latest_offline: OfflineResult | null;
}

export interface SecurityConfig {
  threshold: number;
  distance_threshold_m: number;
  stay_duration_sec: number;
}

export const getSecurityStatus = () =>
  api.get<SecurityPipelineState>("/api/security/status");
export const getSecurityConfig = () =>
  api.get<SecurityConfig>("/api/security/config");
export const updateSecurityConfig = (cfg: Partial<SecurityConfig>) =>
  api.put<SecurityConfig>("/api/security/config", cfg);

// ---- Security: Offline Analysis ----

export interface SecurityImageAnalysisResult {
  annotated_image: string;
  detections: SecurityDetection[];
  distances: SecurityDistance[];
  vlm_result: SecurityValidatedOutput | null;
  scoring: SecurityScoringResult | null;
}

export interface SecurityVideoJob {
  job_id: string;
  status: string;
}

export interface SecurityVideoJobStatus {
  job_id: string;
  status: "queued" | "processing" | "done" | "error" | "not_found";
  progress: number;
  error?: string;
}

export interface SecurityVideoEvent {
  frame_id: number;
  timestamp_sec: number;
  trigger: SecurityTriggerEvent;
  vlm_result: SecurityValidatedOutput;
  scoring: SecurityScoringResult;
  annotated_image: string | null;
}

export interface SecurityVideoJobResult {
  job_id: string;
  status: string;
  events: SecurityVideoEvent[];
  total_frames_processed: number;
  notify_count: number;
  error?: string;
}

export const analyzeSecurityImage = (file: File) => {
  const form = new FormData();
  form.append("file", file);
  return api.post<SecurityImageAnalysisResult>("/api/security/analyze/image", form);
};

export const submitSecurityVideo = (file: File) => {
  const form = new FormData();
  form.append("file", file);
  return api.post<SecurityVideoJob>("/api/security/analyze/video", form);
};

export const getSecurityVideoStatus = (job_id: string) =>
  api.get<SecurityVideoJobStatus>(`/api/security/analyze/video/${job_id}/status`);

export const getSecurityVideoResult = (job_id: string) =>
  api.get<SecurityVideoJobResult>(`/api/security/analyze/video/${job_id}/result`);
