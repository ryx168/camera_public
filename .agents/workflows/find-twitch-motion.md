# Finding and Extracting Motion Events from Twitch VODs

This workflow outlines the process for locating specific events (e.g., a person knocking on a door) across hundreds of Twitch VODs without relying on AI, and then downloading and cropping the relevant segments.

## 1. Locate the Timeframe
Ensure you have the VOD metadata (like `videos.json`) which contains the chronological list of videos. Since Twitch VODs are roughly 35 seconds long, you can estimate the index of the video based on the time difference from the most recent broadcast. 

*Example: If the newest video is at 18:00 and you need videos from 15:00 (3 hours = 180 minutes = ~300 videos), you will look at indices 0 through 300.*

## 2. Detect Motion (No-AI Method)
AI person-detectors (like HOG) can trigger hundreds of false positives on things like reflections or moving plants. Instead, use a pixel-difference script (`fast_motion.py`) that focuses exactly on the crop region where the event happens (e.g., the front door).

### `fast_motion.py` Strategy:
1. **Parallel Stream Fetching:** Use `concurrent.futures.ThreadPoolExecutor` with `python -m yt_dlp -g <url>` to fetch hundreds of direct M3U8 stream URLs in seconds.
2. **OpenCV AbsDiff:** Open each stream using `cv2.VideoCapture`. Crop to the precise area of interest (e.g., `frame[0:240, 426:853]` for the Front Door).
3. **Calculate Burst Motion:** Compute `cv2.absdiff()` between adjacent frames. Apply a binary threshold and count the non-zero pixels. 
4. **Rank Videos:** The event you are looking for (a person walking up to a door) will cause a massive spike (e.g., 20%+ of the pixels changing instantly). Sort the videos by this max motion score.

## 3. Download the Target Video
Once you have the video ID of the event, download the source video using `yt-dlp`:

```bash
python -m yt_dlp -f bestvideo+bestaudio/best -o "c:\camera\%(title)s_%(id)s.%(ext)s" https://www.twitch.tv/videos/<VIDEO_ID>
```

## 4. Crop and Trim the Video
Use `ffmpeg` to isolate the cameras you want and trim out the empty footage. 

*Example: Cropping to both the Office and Front cameras (width 853, height 240, starting at x=0, y=0) and starting the video at 20 seconds:*

```bash
ffmpeg -ss 00:00:20 -i "source_video.mp4" -filter:v "crop=853:240:0:0" -c:a copy -y "output_video.mp4"
```

## Summary of Useful Scripts in `c:\camera`
- **`fast_motion.py`**: Rapidly computes peak structural differences across hundreds of streams in parallel to find massive motion spikes.
- **`get_next_videos.py`**: Given a target video ID, finds the chronologically subsequent videos in the `videos.json` metadata file to track events that span multiple clips.
