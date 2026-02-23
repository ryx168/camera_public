#!/bin/bash
export TZ="America/Vancouver"

TWITCH_URL="rtmp://live.twitch.tv/app/$TWITCH_KEY"
LOG_FILE="logs/stream.log"
DEBUG_LOG="/home/runner/work/camera/camera/logs/ffmpeg-debug.log"
LOCAL_DIR="/home/runner/work/camera/camera"
TIMESTAMP=$(date +"%Y%m%d-%H%M%S")

# Camera URLs — password from CAMERA_PASSWORD secret
CAM_PASS="${CAMERA_PASSWORD:?CAMERA_PASSWORD secret is not set}"
declare -A CAMERA_URLS=(
    ["Office"]="http://192.168.1.31/video.cgi"
    ["Front"]="http://admin:${CAM_PASS}@192.168.1.38/video.cgi"
    ["Kitchen"]="http://admin:${CAM_PASS}@192.168.1.33/video.cgi"
    ["Balcony"]="http://admin:${CAM_PASS}@192.168.1.35/video.cgi"
    ["Backyard"]="http://admin:${CAM_PASS}@192.168.1.39/video.cgi"
)

# Camera order for layout
CAMERA_ORDER=("Office" "Front" "Kitchen" "Balcony" "Backyard")

# ===== BANDWIDTH SAVING SETTINGS =====
# Reduced from 1920x1080 to save bandwidth
# Options: 1920x720 (original), 1280x480 (saves ~50%), 960x360 (saves ~65%), 640x240 (saves ~75%)
export OUTPUT_WIDTH="${OUTPUT_WIDTH:-1280}"
export OUTPUT_HEIGHT="${OUTPUT_HEIGHT:-480}"

# Reduced bitrate to match lower resolution
# Original: 3000k, New: 1500k (saves ~50% bandwidth)
VIDEO_BITRATE="1500k"
VIDEO_MAXRATE="2000k"
VIDEO_BUFSIZE="4000k"

# Reduced frame rate (optional - uncomment to save more bandwidth)
# Original: 30fps, Options: 20fps (saves ~33%), 15fps (saves ~50%)
FRAME_RATE="20"

# Increased CRF for better compression (higher = smaller file, lower quality)
# Range: 18-28, Original: not set (default ~23), New: 26
CRF_VALUE="26"

# Create directories
mkdir -p "$LOCAL_DIR"
mkdir -p "$(dirname "$LOG_FILE")"

# File retention settings
KEEP_HOURS=${KEEP_HOURS:-24}
MAX_SPACE_GB=${MAX_SPACE_GB:-20}

# Timeout and retry settings
MAX_RETRY_COUNT=${MAX_RETRY_COUNT:-3}
FFMPEG_TIMEOUT=${FFMPEG_TIMEOUT:-120}
SEGMENT_DURATION=${SEGMENT_DURATION:-60}
HEALTH_CHECK_INTERVAL=${HEALTH_CHECK_INTERVAL:-30}

# PID file
PID_FILE="/tmp/ffmpeg_stream.pid"

# Signal handler
cleanup() {
    echo "$(date) - 接收到退出信号，清理进程..." | tee -a "$LOG_FILE"
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            echo "$(date) - 终止FFmpeg进程 (PID: $PID)" | tee -a "$LOG_FILE"
            kill -TERM "$PID" 2>/dev/null
            sleep 5
            if kill -0 "$PID" 2>/dev/null; then
                echo "$(date) - 强制终止FFmpeg进程" | tee -a "$LOG_FILE"
                kill -KILL "$PID" 2>/dev/null
            fi
        fi
        rm -f "$PID_FILE"
    fi
    exit 0
}

trap cleanup SIGTERM SIGINT SIGQUIT

# Check camera connectivity (quick - 3 second timeout)
check_camera() {
    local url=$1
    if timeout 3 curl -s -I "$url" > /dev/null 2>&1; then
        return 0
    else
        return 1
    fi
}

# Get online cameras
get_online_cameras() {
    local -a online=()
    local -a names=()

    echo "$(date) - 检查摄像头连接状态..." | tee -a "$LOG_FILE"

    for name in "${CAMERA_ORDER[@]}"; do
        local url="${CAMERA_URLS[$name]}"
        if check_camera "$url"; then
            echo "$(date) - ✅ 摄像头 $name ($url) 连接正常" | tee -a "$LOG_FILE"
            online+=("$url")
            names+=("$name")
        else
            echo "$(date) - ⚠️  摄像头 $name ($url) 离线 - 跳过" | tee -a "$LOG_FILE"
        fi
    done

    # Return arrays via global variables
    ONLINE_CAMERA_URLS=("${online[@]}")
    ONLINE_CAMERA_NAMES=("${names[@]}")

    return ${#online[@]}
}

# Build FFmpeg filter for available cameras (UPDATED FOR LOWER RESOLUTION)
build_filter_complex() {
    local count=$1
    shift
    local -a names=("$@")

    local filter=""

    # All dimensions scaled down proportionally from original
    # Original was based on 1920x720, now scaled to ${OUTPUT_WIDTH}x${OUTPUT_HEIGHT}
    
    case $count in
        1)
            # Single camera - full screen
            filter="[0:v] setpts=PTS-STARTPTS, scale=${OUTPUT_WIDTH}:${OUTPUT_HEIGHT}:flags=fast_bilinear [tmp]; \
                    [tmp] drawtext=fontfile=/usr/share/fonts/freefont/FreeSans.ttf: \
                    text='${names[0]} %{localtime}':x=10:y=10:fontcolor=white:fontsize=16:box=1:boxcolor=black@0.5:boxborderw=2 [out]"
            ;;
        2)
            # Two cameras - side by side
            local half_width=$((OUTPUT_WIDTH / 2))
            filter="[0:v] setpts=PTS-STARTPTS, scale=${half_width}:${OUTPUT_HEIGHT}:flags=fast_bilinear [cam0]; \
                    [1:v] setpts=PTS-STARTPTS, scale=${half_width}:${OUTPUT_HEIGHT}:flags=fast_bilinear [cam1]; \
                    nullsrc=size=${OUTPUT_WIDTH}x${OUTPUT_HEIGHT} [base]; \
                    [base][cam0] overlay=shortest=1:x=0:y=0 [tmp1]; \
                    [tmp1][cam1] overlay=shortest=1:x=${half_width}:y=0 [tmp2]; \
                    [tmp2] drawtext=fontfile=/usr/share/fonts/freefont/FreeSans.ttf: \
                    text='${names[0]}':x=10:y=10:fontcolor=white:fontsize=16:box=1:boxcolor=black@0.5:boxborderw=2 [txt1]; \
                    [txt1] drawtext=fontfile=/usr/share/fonts/freefont/FreeSans.ttf: \
                    text='${names[1]}':x=$((half_width + 10)):y=10:fontcolor=white:fontsize=16:box=1:boxcolor=black@0.5:boxborderw=2 [out]"
            ;;
        3)
            # Three cameras - 2 top, 1 bottom
            local half_width=$((OUTPUT_WIDTH / 2))
            local half_height=$((OUTPUT_HEIGHT / 2))
            filter="[0:v] setpts=PTS-STARTPTS, scale=${half_width}:${half_height}:flags=fast_bilinear [cam0]; \
                    [1:v] setpts=PTS-STARTPTS, scale=${half_width}:${half_height}:flags=fast_bilinear [cam1]; \
                    [2:v] setpts=PTS-STARTPTS, scale=${OUTPUT_WIDTH}:${half_height}:flags=fast_bilinear [cam2]; \
                    nullsrc=size=${OUTPUT_WIDTH}x${OUTPUT_HEIGHT} [base]; \
                    [base][cam0] overlay=shortest=1:x=0:y=0 [tmp1]; \
                    [tmp1][cam1] overlay=shortest=1:x=${half_width}:y=0 [tmp2]; \
                    [tmp2][cam2] overlay=shortest=1:x=0:y=${half_height} [tmp3]; \
                    [tmp3] drawtext=fontfile=/usr/share/fonts/freefont/FreeSans.ttf: \
                    text='${names[0]}':x=10:y=10:fontcolor=white:fontsize=16:box=1:boxcolor=black@0.5:boxborderw=2 [txt1]; \
                    [txt1] drawtext=fontfile=/usr/share/fonts/freefont/FreeSans.ttf: \
                    text='${names[1]}':x=$((half_width + 10)):y=10:fontcolor=white:fontsize=16:box=1:boxcolor=black@0.5:boxborderw=2 [txt2]; \
                    [txt2] drawtext=fontfile=/usr/share/fonts/freefont/FreeSans.ttf: \
                    text='${names[2]}':x=10:y=$((half_height + 10)):fontcolor=white:fontsize=16:box=1:boxcolor=black@0.5:boxborderw=2 [out]"
            ;;
        4)
            # Four cameras - 2x2 grid
            local half_width=$((OUTPUT_WIDTH / 2))
            local half_height=$((OUTPUT_HEIGHT / 2))
            filter="[0:v] setpts=PTS-STARTPTS, scale=${half_width}:${half_height}:flags=fast_bilinear [cam0]; \
                    [1:v] setpts=PTS-STARTPTS, scale=${half_width}:${half_height}:flags=fast_bilinear [cam1]; \
                    [2:v] setpts=PTS-STARTPTS, scale=${half_width}:${half_height}:flags=fast_bilinear [cam2]; \
                    [3:v] setpts=PTS-STARTPTS, scale=${half_width}:${half_height}:flags=fast_bilinear [cam3]; \
                    nullsrc=size=${OUTPUT_WIDTH}x${OUTPUT_HEIGHT} [base]; \
                    [base][cam0] overlay=shortest=1:x=0:y=0 [tmp1]; \
                    [tmp1][cam1] overlay=shortest=1:x=${half_width}:y=0 [tmp2]; \
                    [tmp2][cam2] overlay=shortest=1:x=0:y=${half_height} [tmp3]; \
                    [tmp3][cam3] overlay=shortest=1:x=${half_width}:y=${half_height} [tmp4]; \
                    [tmp4] drawtext=fontfile=/usr/share/fonts/freefont/FreeSans.ttf: \
                    text='${names[0]}':x=10:y=10:fontcolor=white:fontsize=16:box=1:boxcolor=black@0.5:boxborderw=2 [txt1]; \
                    [txt1] drawtext=fontfile=/usr/share/fonts/freefont/FreeSans.ttf: \
                    text='${names[1]}':x=$((half_width + 10)):y=10:fontcolor=white:fontsize=16:box=1:boxcolor=black@0.5:boxborderw=2 [txt2]; \
                    [txt2] drawtext=fontfile=/usr/share/fonts/freefont/FreeSans.ttf: \
                    text='${names[2]}':x=10:y=$((half_height + 10)):fontcolor=white:fontsize=16:box=1:boxcolor=black@0.5:boxborderw=2 [txt3]; \
                    [txt3] drawtext=fontfile=/usr/share/fonts/freefont/FreeSans.ttf: \
                    text='${names[3]}':x=$((half_width + 10)):y=$((half_height + 10)):fontcolor=white:fontsize=16:box=1:boxcolor=black@0.5:boxborderw=2 [out]"
            ;;
        5)
            # Five cameras - 3 top, 2 bottom
            local third_width=$((OUTPUT_WIDTH / 3))
            local half_width=$((OUTPUT_WIDTH / 2))
            local half_height=$((OUTPUT_HEIGHT / 2))
            filter="[0:v] setpts=PTS-STARTPTS, scale=${third_width}:${half_height}:flags=fast_bilinear [cam0]; \
                    [1:v] setpts=PTS-STARTPTS, scale=${third_width}:${half_height}:flags=fast_bilinear [cam1]; \
                    [2:v] setpts=PTS-STARTPTS, scale=${third_width}:${half_height}:flags=fast_bilinear [cam2]; \
                    [3:v] setpts=PTS-STARTPTS, scale=${half_width}:${half_height}:flags=fast_bilinear [cam3]; \
                    [4:v] setpts=PTS-STARTPTS, scale=${half_width}:${half_height}:flags=fast_bilinear [cam4]; \
                    nullsrc=size=${OUTPUT_WIDTH}x${OUTPUT_HEIGHT} [base]; \
                    [base][cam0] overlay=shortest=1:x=0:y=0 [tmp1]; \
                    [tmp1][cam1] overlay=shortest=1:x=${third_width}:y=0 [tmp2]; \
                    [tmp2][cam2] overlay=shortest=1:x=$((third_width * 2)):y=0 [tmp3]; \
                    [tmp3][cam3] overlay=shortest=1:x=0:y=${half_height} [tmp4]; \
                    [tmp4][cam4] overlay=shortest=1:x=${half_width}:y=${half_height} [tmp5]; \
                    [tmp5] drawtext=fontfile=/usr/share/fonts/freefont/FreeSans.ttf: \
                    text='${names[0]} %{localtime}':x=10:y=10:fontcolor=white:fontsize=16:box=1:boxcolor=black@0.5:boxborderw=2 [txt1]; \
                    [txt1] drawtext=fontfile=/usr/share/fonts/freefont/FreeSans.ttf: \
                    text='${names[1]}':x=$((third_width + 10)):y=10:fontcolor=white:fontsize=16:box=1:boxcolor=black@0.5:boxborderw=2 [txt2]; \
                    [txt2] drawtext=fontfile=/usr/share/fonts/freefont/FreeSans.ttf: \
                    text='${names[2]}':x=$((third_width * 2 + 10)):y=10:fontcolor=white:fontsize=16:box=1:boxcolor=black@0.5:boxborderw=2 [txt3]; \
                    [txt3] drawtext=fontfile=/usr/share/fonts/freefont/FreeSans.ttf: \
                    text='${names[3]}':x=10:y=$((half_height + 10)):fontcolor=white:fontsize=16:box=1:boxcolor=black@0.5:boxborderw=2 [txt4]; \
                    [txt4] drawtext=fontfile=/usr/share/fonts/freefont/FreeSans.ttf: \
                    text='${names[4]}':x=$((half_width + 10)):y=$((half_height + 10)):fontcolor=white:fontsize=16:box=1:boxcolor=black@0.5:boxborderw=2 [out]"
            ;;
        *)
            echo "$(date) - ❌ 错误: 不支持的摄像头数量: $count" | tee -a "$LOG_FILE"
            return 1
            ;;
    esac

    echo "$filter"
}

# Cleanup old files
cleanup_old_files() {
    echo "$(date) - 开始清理旧文件..." | tee -a "$LOG_FILE"

    find "$LOCAL_DIR" -name "stream-*.flv" -type f -mmin +$((KEEP_HOURS*60)) -delete 2>/dev/null
    find "$LOCAL_DIR" -name "stream-*.mp4" -type f -mmin +$((KEEP_HOURS*60)) -delete 2>/dev/null

    USED_SPACE=$(du -s "$LOCAL_DIR" 2>/dev/null | awk '{print $1}')
    USED_SPACE_GB=$((USED_SPACE/1024/1024))

    if [ $USED_SPACE_GB -gt $MAX_SPACE_GB ]; then
        echo "$(date) - 警告: 录像空间已使用 ${USED_SPACE_GB}GB，超过阈值 ${MAX_SPACE_GB}GB，删除更多旧文件" | tee -a "$LOG_FILE"
        while [ $USED_SPACE_GB -gt $MAX_SPACE_GB ]; do
            OLDEST_FILE=$(find "$LOCAL_DIR" -type f -name "stream-*" 2>/dev/null | sort | head -n 1)
            if [ -z "$OLDEST_FILE" ]; then
                echo "$(date) - 没有更多可删除的文件" | tee -a "$LOG_FILE"
                break
            fi

            echo "$(date) - 删除最旧的文件: $OLDEST_FILE" | tee -a "$LOG_FILE"
            rm -f "$OLDEST_FILE"

            USED_SPACE=$(du -s "$LOCAL_DIR" 2>/dev/null | awk '{print $1}')
            USED_SPACE_GB=$((USED_SPACE/1024/1024))
        done
    fi

    echo "$(date) - 文件清理完成，当前使用空间: ${USED_SPACE_GB}GB" | tee -a "$LOG_FILE"
}

# Start FFmpeg process
start_ffmpeg() {
    local retry_count=0

    while [ $retry_count -lt $MAX_RETRY_COUNT ]; do
        echo "$(date) - 尝试启动FFmpeg (第 $((retry_count + 1)) 次)..." | tee -a "$LOG_FILE"

        # Get online cameras
        get_online_cameras
        local cam_count=${#ONLINE_CAMERA_URLS[@]}

        if [ $cam_count -eq 0 ]; then
            echo "$(date) - ❌ 错误: 没有可用的摄像头，等待30秒后重试..." | tee -a "$LOG_FILE"
            sleep 30
            ((retry_count++))
            continue
        fi

        echo "$(date) - 📹 使用 $cam_count 个在线摄像头录制" | tee -a "$LOG_FILE"

        # Create new timestamp for filename
        TIMESTAMP=$(date +"%Y%m%d-%H%M%S")
        LOCAL_FILE="${LOCAL_DIR}/stream-${TIMESTAMP}.mp4"

        echo "$(date) - 开始流媒体处理，保存到: $LOCAL_FILE" | tee -a "$LOG_FILE"
        echo "$(date) - 📐 输出分辨率: ${OUTPUT_WIDTH}x${OUTPUT_HEIGHT} @ ${FRAME_RATE}fps" | tee -a "$LOG_FILE"
        echo "$(date) - 📊 视频比特率: ${VIDEO_BITRATE} (最大: ${VIDEO_MAXRATE})" | tee -a "$LOG_FILE"

        # Detect encoder
        if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi > /dev/null 2>&1; then
            ENCODER="h264_nvenc"
            ENCODER_PRESET="p4"
            echo "$(date) - 使用NVIDIA GPU编码 (h264_nvenc)" | tee -a "$LOG_FILE"
        else
            ENCODER="libx264"
            ENCODER_PRESET="ultrafast"
            echo "$(date) - 使用软件编码 (libx264)，预设：ultrafast，CRF：${CRF_VALUE}" | tee -a "$LOG_FILE"
        fi

        # Build input arguments
        local input_args=""
        for url in "${ONLINE_CAMERA_URLS[@]}"; do
            input_args="$input_args -thread_queue_size 1024 -analyzeduration 5000000 -probesize 5000000 -fflags +genpts -use_wallclock_as_timestamps 1 -timeout 10000000 -i $url"
        done

        # Build filter complex
        local filter=$(build_filter_complex $cam_count "${ONLINE_CAMERA_NAMES[@]}")
        if [ -z "$filter" ]; then
            echo "$(date) - ❌ 错误: 无法构建filter_complex" | tee -a "$LOG_FILE"
            ((retry_count++))
            sleep 10
            continue
        fi

        # Start FFmpeg process with REDUCED BANDWIDTH settings
        if [ "$ENCODER" = "h264_nvenc" ]; then
            # NVIDIA GPU encoding
            timeout $FFMPEG_TIMEOUT ffmpeg -threads 4 \
                -loglevel error \
                $input_args \
                -filter_complex "$filter" \
                -map "[out]" \
                -c:v "$ENCODER" \
                -preset ${ENCODER_PRESET} \
                -b:v ${VIDEO_BITRATE} -maxrate ${VIDEO_MAXRATE} -bufsize ${VIDEO_BUFSIZE} \
                -g 60 -keyint_min 30 \
                -r ${FRAME_RATE} -pix_fmt yuv420p \
                -f mp4 -movflags +faststart \
                -t $SEGMENT_DURATION "$LOCAL_FILE" &
        else
            # Software encoding with CRF
            timeout $FFMPEG_TIMEOUT ffmpeg -threads 4 \
                -loglevel error \
                $input_args \
                -filter_complex "$filter" \
                -map "[out]" \
                -c:v "$ENCODER" \
                -preset ${ENCODER_PRESET} \
                -crf ${CRF_VALUE} \
                -b:v ${VIDEO_BITRATE} -maxrate ${VIDEO_MAXRATE} -bufsize ${VIDEO_BUFSIZE} \
                -g 60 -keyint_min 30 \
                -r ${FRAME_RATE} -pix_fmt yuv420p \
                -f mp4 -movflags +faststart \
                -t $SEGMENT_DURATION "$LOCAL_FILE" &
        fi

        # Save process ID
        FFMPEG_PID=$!
        echo "$FFMPEG_PID" > "$PID_FILE"

        # Wait for FFmpeg process
        wait $FFMPEG_PID
        EXIT_CODE=$?

        echo "$(date) - FFmpeg进程退出，代码: $EXIT_CODE" | tee -a "$LOG_FILE"

        # Cleanup PID file
        rm -f "$PID_FILE"

        # Check exit code
        if [ $EXIT_CODE -eq 0 ]; then
            echo "$(date) - ✅ FFmpeg成功完成，文件保存到: $LOCAL_FILE" | tee -a "$LOG_FILE"
            return 0
        elif [ $EXIT_CODE -eq 124 ]; then
            echo "$(date) - ⏱️  FFmpeg超时退出，这是正常的分段行为" | tee -a "$LOG_FILE"
            return 0
        else
            echo "$(date) - ❌ FFmpeg异常退出: $EXIT_CODE" | tee -a "$LOG_FILE"
            ((retry_count++))

            if [ $retry_count -lt $MAX_RETRY_COUNT ]; then
                echo "$(date) - 等待10秒后重试..." | tee -a "$LOG_FILE"
                sleep 10
            fi
        fi
    done

    echo "$(date) - ❌ 错误: FFmpeg启动失败，已达到最大重试次数" | tee -a "$LOG_FILE"
    return 1
}

# Main function
main() {
    echo "$(date) - 🚀 启动同步本地保存和直播流程序..." | tee -a "$LOG_FILE"
    echo "摄像头配置:" | tee -a "$LOG_FILE"
    for name in "${CAMERA_ORDER[@]}"; do
        echo "  $name: ${CAMERA_URLS[$name]}" | tee -a "$LOG_FILE"
    done
    echo "=== 带宽优化设置 ===" | tee -a "$LOG_FILE"
    echo "输出分辨率: ${OUTPUT_WIDTH}x${OUTPUT_HEIGHT}" | tee -a "$LOG_FILE"
    echo "帧率: ${FRAME_RATE} fps" | tee -a "$LOG_FILE"
    echo "比特率: ${VIDEO_BITRATE} (最大: ${VIDEO_MAXRATE})" | tee -a "$LOG_FILE"
    echo "CRF值: ${CRF_VALUE}" | tee -a "$LOG_FILE"
    echo "段持续时间: ${SEGMENT_DURATION}秒" | tee -a "$LOG_FILE"
    echo "FFmpeg超时: ${FFMPEG_TIMEOUT}秒" | tee -a "$LOG_FILE"

    # Initial cleanup
    cleanup_old_files

    # Main loop
    while true; do
        echo "$(date) - 🔄 开始新的录制周期..." | tee -a "$LOG_FILE"

        # Start FFmpeg
        if start_ffmpeg; then
            echo "$(date) - ✅ 录制周期完成" | tee -a "$LOG_FILE"
        else
            echo "$(date) - ⚠️  录制周期失败，等待30秒后重试..." | tee -a "$LOG_FILE"
            sleep 30
        fi

        # Cleanup old files
        cleanup_old_files

        # Wait before next cycle
        echo "$(date) - ⏸️  等待5秒后开始下一个周期..." | tee -a "$LOG_FILE"
        sleep 5
    done
}

# Start main function
main