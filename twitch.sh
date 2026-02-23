#!/bin/bash
# Configuration
RECORDINGS_DIR="/home/runner/work/camera/camera"
OUTPUT_DIR="/home/runner/work/camera/camera/streaming"
OUTPUT_FILE="$OUTPUT_DIR/combined_output.mp4"
LIST_FILE="$RECORDINGS_DIR/concat_list.txt"
STREAM_URL="rtmp://live.twitch.tv/app/${TWITCH_KEY}"
LOG_FILE="$OUTPUT_DIR/stream.log"

# Resolution settings for bandwidth reduction
OUTPUT_WIDTH=1280
OUTPUT_HEIGHT=480

# Monitoring settings
NO_FILES_THRESHOLD=3
no_files_count=0
last_restart_time=0
RESTART_COOLDOWN=120

# Create output directory
mkdir -p "$OUTPUT_DIR"

# Logging function
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# Check if start-stream.sh process is running
check_camera_service() {
    pgrep -f "start-stream.sh" > /dev/null 2>&1
    return $?
}

# Restart start-stream.sh with cooldown
restart_camera_service() {
    local current_time=$(date +%s)
    local time_since_restart=$((current_time - last_restart_time))

    if [ $time_since_restart -lt $RESTART_COOLDOWN ]; then
        log "⏳ Cooldown active. Last restart was $time_since_restart seconds ago. Waiting..."
        return 1
    fi

    log "🔄 Attempting to restart start-stream.sh..."

    pkill -f "start-stream.sh" 2>/dev/null || true
    sleep 3

    if [ -x "./start-stream.sh" ]; then
        ./start-stream.sh &
        log "✅ Successfully restarted start-stream.sh (PID: $!)"
        last_restart_time=$current_time
        no_files_count=0
        return 0
    else
        log "❌ start-stream.sh not found or not executable"
        return 1
    fi
}

restart_stream() {
    log "🎛️ CONTROLLER: Managing start-stream.sh process..."

    if pgrep -f "start-stream.sh" > /dev/null; then
        log "🛑 CONTROLLER: Stopping existing start-stream.sh processes..."
        pkill -f "start-stream.sh"
        sleep 3

        if pgrep -f "start-stream.sh" > /dev/null; then
            log "🔨 CONTROLLER: Force killing stubborn processes..."
            pkill -9 -f "start-stream.sh"
            sleep 2
        fi
    fi

    if [ -x "./start-stream.sh" ]; then
        log "▶️ CONTROLLER: Starting start-stream.sh..."
        ./start-stream.sh &
        new_pid=$!
        log "✅ CONTROLLER: Started start-stream.sh with PID: $new_pid"

        sleep 5
        if kill -0 "$new_pid" 2>/dev/null; then
            log "✅ CONTROLLER: start-stream.sh is running successfully"
        else
            log "❌ CONTROLLER: start-stream.sh failed to start or exited immediately"
        fi
    else
        log "❌ CONTROLLER: start-stream.sh not found or not executable"
        log "📁 CONTROLLER: Current directory: $(pwd)"
    fi
}

cleanup_old_files() {
    log "🧹 Cleaning files older than 1 hour..."
    old_count=$(find "$RECORDINGS_DIR" -maxdepth 1 -type f -name "*.mp4" -mmin +60 2>/dev/null | wc -l)

    if [ "$old_count" -gt 0 ]; then
        log "📋 Found $old_count file(s) older than 1 hour"
        find "$RECORDINGS_DIR" -maxdepth 1 -type f -name "*.mp4" -mmin +60 -print0 2>/dev/null | \
        while IFS= read -r -d '' file; do
            log "🗑️ Deleting old file: $(basename "$file")"
            rm -f "$file"
        done
        log "✅ Cleanup completed - removed $old_count old file(s)"
    else
        log "ℹ️ No files older than 1 hour found"
    fi
}

get_file_count() {
    find "$RECORDINGS_DIR" -maxdepth 1 -type f -name "*.mp4" 2>/dev/null | wc -l
}

monitor_files() {
    local current_files=$(get_file_count)
    log "📊 Current .mp4 files in directory: $current_files"

    if ! check_camera_service; then
        log "⚠️ WARNING: camera-stream is NOT running!"
        log "🚨 Service is down - attempting immediate restart..."
        restart_camera_service
        sleep 10
        current_files=$(get_file_count)
        log "📊 After restart, files in directory: $current_files"
    fi

    if [ "$current_files" -lt 1 ]; then
        no_files_count=$((no_files_count + 1))
        log "⚠️ No files found (count: $no_files_count/$NO_FILES_THRESHOLD)"

        if [ $no_files_count -ge $NO_FILES_THRESHOLD ]; then
            log "🚨 No files for $no_files_count cycles. Taking action..."
            restart_camera_service
        fi
        return 1
    else
        if [ $no_files_count -gt 0 ]; then
            log "✅ Files detected. Resetting no-files counter (was: $no_files_count)"
        fi
        no_files_count=0
        return 0
    fi
}

trap 'log "🛑 Script interrupted. Cleaning up..."; rm -f "$OUTPUT_FILE" "$LIST_FILE"; exit 0' INT TERM

cycle_count=0
consecutive_failures=0
MAX_CONSECUTIVE_FAILURES=5
START_TIME=$(date +%s)
MAX_RUNTIME=21600   # 6 hours in seconds

log "🚀 Stream script started"
log "📁 Monitoring directory: $RECORDINGS_DIR"
log "🎥 Camera service: start-stream.sh process"
log "📐 Output resolution: ${OUTPUT_WIDTH}x${OUTPUT_HEIGHT}"
log "⏱️  Max runtime: 6 hours"

while true; do
    cycle_count=$((cycle_count + 1))
    log "🔄 Starting cycle #$cycle_count"

    # Exit loop after 6 hours
    elapsed=$(( $(date +%s) - START_TIME ))
    if [ $elapsed -ge $MAX_RUNTIME ]; then
        log "⏰ 6-hour runtime limit reached (${elapsed}s). Exiting cleanly."
        break
    fi

    cleanup_old_files

    if ! monitor_files; then
        log "⏸ No files available. Waiting 15 seconds before retry..."
        sleep 15
        continue
    fi

    log "🔄 Cleaning previous combined output..."
    rm -f "$OUTPUT_FILE" "$LIST_FILE"

    log "📁 Finding files to combine..."
    log "DEBUG: Current directory: $(pwd)"
    log "DEBUG: Files found:"

    # Clear the list file first
    > "$LIST_FILE"

    # Alpine-compatible: manually get timestamps with stat
    find "$RECORDINGS_DIR" -maxdepth 1 -type f -name "*.mp4" 2>/dev/null | \
        while IFS= read -r file; do
            timestamp=$(stat -c %Y "$file" 2>/dev/null)
            echo "$timestamp $file"
        done | \
        sort -n | tail -n 10 | head -n 9 | cut -d' ' -f2- | \
        while IFS= read -r file; do
            log "  Checking: $file"
            if ffprobe -v error -show_format -show_streams "$file" > /dev/null 2>&1; then
                echo "file '$file'" >> "$LIST_FILE"
                log "    ✅ Added to list"
            else
                log "    ⚠️ Skipping invalid file: $file"
            fi
        done

    if [ ! -s "$LIST_FILE" ] || [ "$(wc -l < "$LIST_FILE")" -lt 2 ]; then
        log "⏸ Not enough valid files to combine. Retrying in 10 seconds..."
        sleep 10
        continue
    fi

    log "🎞 Files to combine:"
    cat "$LIST_FILE" | sed 's/file /  - /' | tee -a "$LOG_FILE"

    log "🎞 Combining and scaling video files to ${OUTPUT_WIDTH}x${OUTPUT_HEIGHT}..."
    # FIXED: Proper encoding for streaming with correct settings
    if ffmpeg -f concat -safe 0 -i "$LIST_FILE" \
        -vf "scale=${OUTPUT_WIDTH}:${OUTPUT_HEIGHT}:flags=fast_bilinear" \
        -c:v libx264 -preset ultrafast -tune zerolatency \
        -b:v 1500k -maxrate 2000k -bufsize 4000k \
        -g 60 -keyint_min 30 \
        -r 20 -pix_fmt yuv420p \
        -movflags +faststart \
        "$OUTPUT_FILE" -y 2>&1 | grep -v "frame=" | tee -a "$LOG_FILE"; then
        
        log "✅ Successfully combined and scaled files to ${OUTPUT_WIDTH}x${OUTPUT_HEIGHT}"

        if [ -f "$OUTPUT_FILE" ]; then
            file_size=$(stat -c%s "$OUTPUT_FILE" 2>/dev/null)
            log "📡 Streaming combined file (size: $file_size bytes)..."

            # FIXED: Proper streaming with re-encoding for Twitch compatibility
            timeout 300 ffmpeg -re -i "$OUTPUT_FILE" \
                -c:v libx264 -preset veryfast -tune zerolatency \
                -b:v 1500k -maxrate 2000k -bufsize 4000k \
                -g 60 -keyint_min 30 \
                -r 20 -pix_fmt yuv420p \
                -f flv \
                "$STREAM_URL" 2>&1 | \
                grep -E "(error|Error|failed|Failed|Connection|frame=)" | tee -a "$LOG_FILE"

            stream_exit_code=$?

            if [ $stream_exit_code -eq 0 ]; then
                log "✅ Streaming finished successfully"
                consecutive_failures=0
            elif [ $stream_exit_code -eq 124 ]; then
                log "⏱️ Streaming timeout (normal after 5 minutes)"
                consecutive_failures=0
            else
                consecutive_failures=$((consecutive_failures + 1))
                log "❌ Streaming failed with exit code: $stream_exit_code (failure #$consecutive_failures)"

                if [ $consecutive_failures -ge $MAX_CONSECUTIVE_FAILURES ]; then
                    log "🚨 Too many consecutive failures. Waiting 60 seconds before retry..."
                    sleep 60
                    consecutive_failures=0
                fi
            fi
        else
            log "❌ Combined file not found after creation"
            consecutive_failures=$((consecutive_failures + 1))
        fi
    else
        log "❌ Failed to combine files. Skipping this cycle."
        consecutive_failures=$((consecutive_failures + 1))
    fi

    if [ $consecutive_failures -gt 0 ]; then
        wait_time=$((5 + consecutive_failures * 2))
        log "⏱️ Waiting $wait_time seconds before next cycle (after failure)..."
        sleep $wait_time
    else
        log "⏱️ Waiting 5 seconds before next cycle..."
        sleep 5
    fi
done