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

    def set_classes(self, new_classes):
        """
        検知対象のクラスを動的に変更します。
        """
        self.target_classes = new_classes
