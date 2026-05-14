from ultralytics import YOLO

class YoloDetector:
    def __init__(self, model_name="yolov8n.pt", target_classes=[0]):
        """
        YOLOによる物体検出クラス
        デフォルトで target_classes=[0] とし、Person（人）のみを検出対象にしています。
        """
        print(f"[*] Loading {model_name}...")
        self.model = YOLO(model_name)
        self.target_classes = target_classes
        
    def detect(self, frame):
        """
        フレームを受け取り、推論結果とアノテーション済みの画像を返します。
        """
        results = self.model(frame, classes=self.target_classes, verbose=False)
        annotated_frame = results[0].plot()
        return annotated_frame, results

    def detect_and_track(self, frame, security_classes: list[int] | None = None):
        """
        ByteTrack を使ったトラッキング付き検出。
        セキュリティ検知パイプライン向け。既存の detect() には影響しない。

        Args:
            frame: BGR フレーム (np.ndarray)
            security_classes: 検出対象クラスID一覧。None の場合は target_classes を使用。

        Returns:
            annotated_frame: アノテーション済みフレーム
            track_list: list[dict] — track_id / class_id / class_name / bbox / confidence / owner_excluded
        """
        classes = security_classes if security_classes is not None else self.target_classes
        results = self.model.track(
            frame,
            classes=classes,
            tracker="bytetrack.yaml",
            persist=True,
            verbose=False,
        )
        annotated_frame = results[0].plot()

        track_list = []
        boxes = results[0].boxes
        if boxes is not None and boxes.id is not None:
            for i in range(len(boxes)):
                tid = int(boxes.id[i])
                cls_id = int(boxes.cls[i])
                conf = float(boxes.conf[i])
                x1, y1, x2, y2 = boxes.xyxy[i].tolist()
                cls_name = self.model.names.get(cls_id, str(cls_id))
                track_list.append({
                    "track_id": tid,
                    "class_id": cls_id,
                    "class_name": cls_name,
                    "bbox": [round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1)],
                    "confidence": round(conf, 4),
                    "owner_excluded": False,
                })
        return annotated_frame, track_list

    def set_classes(self, new_classes):
        """
        検知対象のクラスを動的に変更します。
        """
        self.target_classes = new_classes
