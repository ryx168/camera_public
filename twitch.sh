#!/bin/bash
# Configuration
RECORDINGS_DIR="${GITHUB_WORKSPACE:-$(pwd)}/recordings"
OUTPUT_DIR="$RECORDINGS_DIR/streaming"
OUTPUT_FILE="$OUTPUT_DIR/combined_output.mp4"
LIST_FILE="$RECORDINGS_DIR/concat_list.txt"
STREAM_URL="rtmp://live.twitch.tv/app/${TWITCH_KEY}"
LOG_FILE="$OUTPUT_DIR/stream.log"

# Resolution settings for bandwidth reduction
OUTPUT_WIDTH=1280
OUTPUT_HEIGHT=480

# Monitoring settings
NO_FILES_THRESHOLD=3
# How many finished 60s segments go into each push to Twitch. Streaming uses
# -re, so a push of N segments takes N minutes of wall clock while N more are
# being recorded - the pipeline is self-balancing at any value. Larger is
# better for continuity: the RTMP connection is opened and closed once per
# push, and every close ends the broadcast and starts a new VOD. At 9 that was
# a reconnection every nine minutes; at 20 it is every twenty. The +1 in the
# tail below skips the newest file, which is still being written.
COMBINE_SEGMENTS=${COMBINE_SEGMENTS:-20}

# Never push fewer than this. Sending one or two segments opens and closes the
# RTMP connection for a few seconds of footage, which ends the broadcast and
# starts another VOD - the micro-VOD churn.
MIN_SEGMENTS=${MIN_SEGMENTS:-3}

# Anything shorter than this from the combine step is a broken input set, not a
# broadcast; pushing it just ends the stream again.
MIN_PUSH_SECONDS=${MIN_PUSH_SECONDS:-45}

# Newest segment mtime already broadcast. Selection used to re-pick the newest
# N files every cycle with no record of what had gone out, so whenever
# recording stalled or fell behind, the same segments were re-encoded and
# re-sent - the viewer saw the picture freeze while the burnt-in camera clock
# sat still for half an hour. Each segment now goes out exactly once.
last_pushed_ts=0

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

    if [ -f "/tmp/no_space.flag" ]; then
        log "🚨 CRITICAL: No space flag detected. Aborting restart."
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

    # Ensure any orphaned ffmpeg processes connecting to cameras are also killed
    if pgrep -f "ffmpeg.*video\.cgi" > /dev/null; then
        log "🧹 CONTROLLER: Cleaning up orphaned capturing ffmpeg processes..."
        pkill -9 -f "ffmpeg.*video\.cgi"
        sleep 1
    fi
    if [ -f "/tmp/ffmpeg_stream.pid" ]; then
        local pid=$(cat /tmp/ffmpeg_stream.pid)
        if kill -0 "$pid" 2>/dev/null; then
            log "🧹 CONTROLLER: Force killing PID $pid from pidfile..."
            kill -9 "$pid" 2>/dev/null
        fi
        rm -f "/tmp/ffmpeg_stream.pid"
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

    if [ -f "/tmp/no_space.flag" ]; then
        log "🚨 CRITICAL: /tmp/no_space.flag found. Disk space exhausted. Quitting stream controller."
        break
    fi

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
    ALL_FILE="$RECORDINGS_DIR/.segments"
    find "$RECORDINGS_DIR" -maxdepth 1 -type f -name "*.mp4" 2>/dev/null | \
        while IFS= read -r file; do
            timestamp=$(stat -c %Y "$file" 2>/dev/null)
            [ -n "$timestamp" ] && echo "$timestamp $file"
        done | sort -n > "$ALL_FILE"

    total_segments=$(wc -l < "$ALL_FILE")
    if [ "$total_segments" -lt 2 ]; then
        log "⏸ Only $total_segments segment(s) on disk. Retrying in 10 seconds..."
        sleep 10
        continue
    fi

    # Drop the newest: start-stream.sh is still writing it.
    head -n $((total_segments - 1)) "$ALL_FILE" > "$ALL_FILE.settled"

    # Only what has not been broadcast yet, oldest first, so the archive stays
    # continuous and in order instead of jumping to whatever is newest.
    awk -v mark="$last_pushed_ts" '$1 > mark' "$ALL_FILE.settled" > "$ALL_FILE.new"
    new_segments=$(wc -l < "$ALL_FILE.new")
    log "📊 $new_segments segment(s) not yet broadcast"

    # cleanup_old_files deletes anything over an hour old, so a backlog that
    # deep is going to be erased before it can be sent. Skip forward rather
    # than spend the cycle pushing footage that is about to vanish.
    max_backlog=$((COMBINE_SEGMENTS * 2))
    if [ "$new_segments" -gt "$max_backlog" ]; then
        drop=$((new_segments - max_backlog))
        log "⏭ Backlog of $new_segments exceeds $max_backlog - skipping $drop oldest"
        tail -n +$((drop + 1)) "$ALL_FILE.new" > "$ALL_FILE.tmp"
        mv "$ALL_FILE.tmp" "$ALL_FILE.new"
        new_segments=$max_backlog
    fi

    if [ "$new_segments" -lt "$MIN_SEGMENTS" ]; then
        log "⏸ Only $new_segments new segment(s) since the last push - waiting"
        log "   rather than re-sending footage that has already gone out."
        sleep 20
        continue
    fi

    head -n "$COMBINE_SEGMENTS" "$ALL_FILE.new" > "$ALL_FILE.take"

    # Read from a file, not a pipe: a `while read` on the right-hand side of a
    # pipe runs in a subshell and pending_mark would be lost with it.
    pending_mark=0
    while IFS=' ' read -r seg_ts seg_file; do
        log "  Checking: $seg_file"
        if ffprobe -v error -show_format -show_streams "$seg_file" > /dev/null 2>&1; then
            echo "file '$seg_file'" >> "$LIST_FILE"
            pending_mark=$seg_ts
            log "    ✅ Added to list"
        else
            log "    ⚠️ Skipping invalid file: $seg_file"
        fi
    done < "$ALL_FILE.take"

    if [ ! -s "$LIST_FILE" ] || [ "$(wc -l < "$LIST_FILE")" -lt "$MIN_SEGMENTS" ]; then
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
        "$OUTPUT_FILE" -y 2>&1 | grep -v "frame=" | tee -a "$LOG_FILE"
    # ${PIPESTATUS[0]} is ffmpeg's status; plain $? would be tee's, which is
    # ~always 0, so a failed combine used to read as a success.
    [ "${PIPESTATUS[0]}" -eq 0 ]; then
        
        log "✅ Successfully combined and scaled files to ${OUTPUT_WIDTH}x${OUTPUT_HEIGHT}"

        if [ -f "$OUTPUT_FILE" ]; then
            file_size=$(stat -c%s "$OUTPUT_FILE" 2>/dev/null)

            # A combine that yields seconds instead of minutes means the input
            # segments were truncated. Pushing it ends the broadcast almost as
            # soon as it starts and leaves another stub VOD behind.
            out_dur=$(ffprobe -v error -show_entries format=duration \
                      -of default=nw=1:nk=1 "$OUTPUT_FILE" 2>/dev/null)
            out_dur=${out_dur%%.*}
            if [ -z "$out_dur" ] || [ "$out_dur" -lt "$MIN_PUSH_SECONDS" ]; then
                log "⏸ Combined file is only ${out_dur:-0}s (need ${MIN_PUSH_SECONDS}s)."
                log "   Segments are truncated - skipping this push."
                last_pushed_ts=$pending_mark
                sleep 15
                continue
            fi

            log "📡 Streaming combined file (${out_dur}s, size: $file_size bytes)..."

            # -re streams at wall-clock speed, so a push takes as long as the combined
            # file. The old fixed 300s cap truncated every push at five minutes and
            # dropped the RTMP connection there, which ends the broadcast and starts a
            # new VOD. Derived from the file length now, with two minutes of slack.
            timeout $((COMBINE_SEGMENTS * 60 + 120)) ffmpeg -re -i "$OUTPUT_FILE" \
                -c:v libx264 -preset veryfast -tune zerolatency \
                -b:v 1500k -maxrate 2000k -bufsize 4000k \
                -g 60 -keyint_min 30 \
                -r 20 -pix_fmt yuv420p \
                -f flv \
                "$STREAM_URL" 2>&1 | \
                grep -E "(error|Error|failed|Failed|Connection|frame=)" | tee -a "$LOG_FILE"

            # Again ffmpeg's status, not tee's.
            stream_exit_code=${PIPESTATUS[0]}

            if [ $stream_exit_code -eq 0 ]; then
                log "✅ Streaming finished successfully"
                # These segments have been broadcast; never send them again.
                last_pushed_ts=$pending_mark
                consecutive_failures=0
            elif [ $stream_exit_code -eq 124 ]; then
                log "⏱️ Streaming hit the timeout - moving on"
                # Cut short, but re-sending would only repeat the freeze.
                last_pushed_ts=$pending_mark
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