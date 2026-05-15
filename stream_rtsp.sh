#!/bin/bash

# USBカメラのデバイスファイル (環境に合わせて /dev/video1 などに変更してください)
DEVICE=${1:-"/dev/video0"}

# RTSPのポート番号
PORT="8554"

# 配信のパス
STREAM_PATH="live"

# MediaMTX (RTSPサーバー) のセットアップ
if [ ! -f "./mediamtx" ] || [ ! -f "./mediamtx.yml" ]; then
    echo "高機能RTSPサーバー(MediaMTX)が見つからないため、ダウンロードします..."
    curl -sL "https://github.com/bluenviron/mediamtx/releases/download/v1.6.0/mediamtx_v1.6.0_linux_amd64.tar.gz" | tar xz mediamtx mediamtx.yml
fi

echo "MediaMTXをバックグラウンドで起動します..."
./mediamtx &
MEDIAMTX_PID=$!

# スクリプト終了時(Ctrl+C)にMediaMTXも終了するようにトラップを設定
trap "echo 'ストリーミングとRTSPサーバーを停止します...'; kill $MEDIAMTX_PID 2>/dev/null; exit 0" SIGINT SIGTERM EXIT

# サーバー起動を少し待つ
sleep 1

echo "=================================================="
echo "USBカメラ ($DEVICE) のRTSP配信を開始します..."
echo "VLCプレーヤー等で以下のURLを開いて確認できます:"
echo "URL: rtsp://localhost:${PORT}/${STREAM_PATH}"
echo "停止するには Ctrl+C を押してください。"
echo "=================================================="

# FFmpegを使用してUSBカメラの映像をH.264でエンコードし、
# 起動したRTSPサーバー(MediaMTX)へプッシュ(送信)します。
ffmpeg -f v4l2 -framerate 30 -video_size 640x480 -i "$DEVICE" \
  -c:v libx264 -preset ultrafast -tune zerolatency \
  -b:v 1M -maxrate 1M -bufsize 2M \
  -f rtsp -rtsp_transport tcp "rtsp://localhost:${PORT}/${STREAM_PATH}"
