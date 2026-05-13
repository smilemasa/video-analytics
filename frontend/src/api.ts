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
  camera_index?: number;
  fps?: number;
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
export const startCamera = (camera_index: number) =>
  api.post<CameraStatus>("/api/live/camera/start", { camera_index });
export const stopCamera = () =>
  api.post<CameraStatus>("/api/live/camera/stop");
