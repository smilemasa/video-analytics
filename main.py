import cv2
import os
import glob
import time
import numpy as np
import tkinter as tk
from tkinter import scrolledtext
from PIL import Image, ImageTk
from dotenv import load_dotenv

# .env から HF_TOKEN 等の環境変数を読み込む（存在しない場合は無視）
load_dotenv()

from yolo_detector import YoloDetector
from vlm_analyzer import VLMAnalyzer
from models import MODEL_REGISTRY


def get_c922_camera_index():
    try:
        video_paths = glob.glob("/sys/class/video4linux/video*")
        for path in video_paths:
            name_file = os.path.join(path, "name")
            if os.path.exists(name_file):
                with open(name_file, 'r') as f:
                    name = f.read().strip()
                if "C922" in name or "Pro Stream" in name:
                    return int(os.path.basename(path).replace("video", ""))
    except Exception as e:
        print(f"[!] Error detecting camera index: {e}")
    return 0

def main():
    # コンポーネントの初期化
    detector = YoloDetector(model_name="yolov8n.pt", target_classes=[0])
    analyzer = VLMAnalyzer(model_id="Qwen/Qwen2-VL-2B-Instruct")
    
    # VLM非同期処理の開始
    analyzer.start()

    CAMERA_INDEX = get_c922_camera_index()
    cap = cv2.VideoCapture(CAMERA_INDEX)
    if not cap.isOpened():
        print("[!] Error: Could not open camera.")
        try:
            with open("/proc/version", "r") as f:
                if "microsoft-standard-WSL2" in f.read():
                    print("[!] Note: WSL2環境で実行されています。WindowsのWebカメラはWSLからは直接見えません。")
                    print("[!] Windows側のPowerShellで 'usbipd-win' を使用してカメラをWSLにアタッチするか、WindowsネイティブのPython環境で実行してください。")
        except:
            pass
        return

    print("[*] Camera started.")

    # Tkinter 初期化
    root = tk.Tk()
    root.title("Video Analytics Dashboard (YOLO + Qwen-VL)")
    
    # 左ペイン：カメラ映像
    video_frame = tk.Frame(root)
    video_frame.pack(side=tk.LEFT, padx=10, pady=10)
    
    video_label = tk.Label(video_frame)
    video_label.pack()

    # 解析中の画像表示用プレースホルダー
    blank_image = np.zeros((240, 320, 3), dtype=np.uint8)
    blank_imgtk = ImageTk.PhotoImage(image=Image.fromarray(blank_image))

    lbl_analyzing_title = tk.Label(video_frame, text="[ Currently Analyzing ]", font=("Arial", 12, "bold"))
    lbl_analyzing_title.pack(pady=(20, 5))

    analyzing_label = tk.Label(video_frame, bg="black", image=blank_imgtk)
    analyzing_label.image = blank_imgtk  # 参照保持
    analyzing_label.pack()

    # 右ペイン：コントロールとVLM結果
    right_frame = tk.Frame(root)
    right_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=10, pady=10)
    
    # オプション設定
    lbl_mode = tk.Label(right_frame, text="[ Object Mode ]", font=("Arial", 12, "bold"))
    lbl_mode.pack(pady=(0, 5))

    active_modes = set()

    buttons = [
        {"label": "Person", "classes": [0]},
        {"label": "Vehicles", "classes": [2, 3, 5, 7]},
        {"label": "Animals", "classes": [14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24]},
        {"label": "Furniture", "classes": [56, 57, 58, 59, 60, 61, 62, 72]},
        {"label": "All", "classes": None}
    ]
    
    def toggle_mode(label, init=False):
        nonlocal active_modes
        
        if init:
            active_modes = {label}
        elif label == "All":
            active_modes = {"All"}
        else:
            if "All" in active_modes:
                active_modes.remove("All")
            
            if label in active_modes:
                active_modes.remove(label)
                if len(active_modes) == 0:
                    active_modes = {"All"}
            else:
                active_modes.add(label)
                
        # 選択されたモードのクラスのリストを作成
        if "All" in active_modes:
            combined_classes = None
        else:
            combined_classes = []
            for btn in buttons:
                if btn["label"] in active_modes and btn["classes"] is not None:
                    combined_classes.extend(btn["classes"])
                    
        detector.set_classes(combined_classes)
        
        # 選択されたボタンの色を変更
        for txt, btn in button_widgets.items():
            if txt in active_modes:
                btn.config(bg="sea green", fg="white")
            else:
                btn.config(bg="gray80", fg="black")

    button_widgets = {}
    for btn_info in buttons:
        btn_txt = btn_info["label"]
        b = tk.Button(right_frame, text=btn_txt, width=15, 
                      command=lambda l=btn_txt: toggle_mode(l))
        b.pack(pady=2)
        button_widgets[btn_txt] = b
    
    # 初期状態セット
    toggle_mode("Person", init=True)

    # VLM Model 設定エリア
    lbl_vlm_model = tk.Label(right_frame, text="[ VLM Model ]", font=("Arial", 12, "bold"))
    lbl_vlm_model.pack(pady=(20, 5))

    vlm_model_var = tk.StringVar()
    vlm_model_var.set("Qwen/Qwen2-VL-2B-Instruct")
    
    SUPPORTED_MODELS = list(MODEL_REGISTRY.keys())
    
    def on_model_change(*args):
        new_model = vlm_model_var.get()
        analyzer.set_model(new_model)
        
    vlm_model_var.trace("w", on_model_change)
    
    vlm_model_dropdown = tk.OptionMenu(right_frame, vlm_model_var, *SUPPORTED_MODELS)
    vlm_model_dropdown.config(width=25)
    vlm_model_dropdown.pack(pady=2)

    # VLM プロンプト設定エリア
    lbl_prompt = tk.Label(right_frame, text="[ VLM Prompt ]", font=("Arial", 12, "bold"))
    lbl_prompt.pack(pady=(20, 5))

    prompt_frame = tk.Frame(right_frame)
    prompt_frame.pack(fill=tk.X, padx=10)

    prompt_entry = tk.Entry(prompt_frame, font=("Arial", 10))
    prompt_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
    prompt_entry.insert(0, "画像の中の人物が何をしているか、短く能動態で説明してください。")

    def paste_prompt():
        try:
            clip_text = root.clipboard_get()
            prompt_entry.delete(0, tk.END)
            prompt_entry.insert(0, clip_text)
        except tk.TclError:
            print("[!] Clipboard is empty or inaccessible.")

    btn_paste = tk.Button(prompt_frame, text="Paste", command=paste_prompt)
    btn_paste.pack(side=tk.LEFT, padx=(0, 5))

    def apply_prompt():
        analyzer.set_prompt(prompt_entry.get())

    btn_apply_prompt = tk.Button(prompt_frame, text="Apply", command=apply_prompt)
    btn_apply_prompt.pack(side=tk.RIGHT)

    # System Status 表示エリア
    lbl_sys_status = tk.Label(right_frame, text="[ System Status ]", font=("Arial", 12, "bold"))
    lbl_sys_status.pack(pady=(20, 5))

    status_var = tk.StringVar()
    status_var.set("Initializing...")
    lbl_status_val = tk.Label(right_frame, textvariable=status_var, font=("Arial", 10), justify=tk.LEFT, bg="white", relief=tk.SUNKEN, width=45, height=5, anchor="nw")
    lbl_status_val.pack(padx=10, fill=tk.X)

    # VLM解析結果表示エリア
    lbl_vlm = tk.Label(right_frame, text="[ VLM Analysis Results ]", font=("Arial", 12, "bold"))
    lbl_vlm.pack(pady=(20, 5))

    vlm_text = scrolledtext.ScrolledText(right_frame, width=45, height=20, wrap=tk.WORD, font=("Arial", 10))
    vlm_text.pack(fill=tk.BOTH, expand=True)
    
    prev_time = time.time()
    last_vlm_res = ""

    def update_frame():
        nonlocal prev_time, last_vlm_res
        ret, frame = cap.read()
        if not ret:
            print("[!] Failed to grab frame.")
            return

        # YOLOによる物体検出
        annotated_frame, results = detector.detect(frame)
        
        # 検出されたオブジェクト数を取得
        num_objects = len(results[0].boxes) if results and len(results) > 0 else 0
        
        # 対象オブジェクトが検出されている場合のみVLMへ渡し解析させる
        if num_objects > 0:
            analyzer.push_frame(frame)
        
        # FPSの計算
        curr_time = time.time()
        fps = 1 / (curr_time - prev_time + 0.0001)
        prev_time = curr_time
        
        # FPS映像上にオーバーレイ
        cv2.putText(annotated_frame, f"FPS: {fps:.1f}", (15, 30), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2, cv2.LINE_AA)
        
        # OpenCV画像(BGR)をTkinter(RGB Image)に変換
        rgb_frame = cv2.cvtColor(annotated_frame, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(rgb_frame)
        imgtk = ImageTk.PhotoImage(image=img)
        
        # Labelウィジェットの更新
        video_label.imgtk = imgtk  # 参照保持
        video_label.configure(image=imgtk)

        # VLM結果の更新（変更があった場合のみテキストエリアに追記）
        vlm_res = analyzer.get_latest_result()
        if vlm_res != last_vlm_res:
            vlm_text.insert(tk.END, vlm_res + "\n\n")
            vlm_text.see(tk.END) # 最新行までスクロール
            last_vlm_res = vlm_res
            
        # System Status の更新
        vlm_status, current_prompt = analyzer.get_status()
        queue_size = analyzer.get_queue_size()
        prompt_display = current_prompt if current_prompt else "N/A"
        
        status_text = (
            f" 🎯 Target Mode: {', '.join(sorted(list(active_modes)))}\n"
            f" 📦 Objects Found: {num_objects}\n"
            f" ⏳ VLM State: {vlm_status}\n"
            f" 📊 Queue Size: {queue_size} / 3\n"
            f" 📝 Prompt: {prompt_display}"
        )
        status_var.set(status_text)

        # 解析中画像の更新
        a_frame = analyzer.get_current_frame()
        if a_frame is not None:
            a_frame_resized = cv2.resize(a_frame, (320, 240))
            a_rgb = cv2.cvtColor(a_frame_resized, cv2.COLOR_BGR2RGB)
            a_img = Image.fromarray(a_rgb)
            a_imgtk = ImageTk.PhotoImage(image=a_img)
            analyzing_label.imgtk = a_imgtk
            analyzing_label.configure(image=a_imgtk)
        else:
            analyzing_label.configure(image=blank_imgtk)
            analyzing_label.imgtk = blank_imgtk
            
        # 約30fps(33ms)毎にGUI更新をスケジュール
        root.after(33, update_frame)

    # アプリ終了時のクリーンアップ処理
    def on_closing():
        analyzer.stop()
        cap.release()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_closing)
    
    print("[*] Starting Tkinter dashboard...")
    update_frame()
    root.mainloop()

if __name__ == "__main__":
    main()
