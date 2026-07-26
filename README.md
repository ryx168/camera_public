# Camera Streaming with GitHub Actions

This repository contains scripts and GitHub Actions workflows for streaming camera feeds.

## GitHub Actions Setup

The workflow is configured to run for 6 hours and uses Tailscale to connect to your private network.

### Required Secrets

You need to add the following secrets to your GitHub repository:

1. **TS_OAUTH_CLIENT_ID** - Tailscale OAuth Client ID
2. **TS_OAUTH_SECRET** - Tailscale OAuth Secret
3. **TWITCH_KEY** - Your Twitch stream key (if using Twitch streaming)

### Setting up Tailscale OAuth

1. Go to [Tailscale Admin Console](https://login.tailscale.com/admin/settings/oauth)
2. Generate a new OAuth client
3. Add the client ID and secret to your GitHub repository secrets:
   - Go to your repository → Settings → Secrets and variables → Actions
   - Click "New repository secret"
   - Add `TS_OAUTH_CLIENT_ID` and `TS_OAUTH_SECRET`

### Workflow Schedule

The workflow runs:
- Automatically every 6 hours
- Manually via workflow_dispatch (Actions tab → Run workflow)

### Files

- `.github/workflows/stream.yml` - GitHub Actions workflow
- `start-stream.sh` - Camera streaming script
- `twitch.sh` - Twitch streaming script
- `front_door_ai.py` - AI Person Detection engine for Front Door (`192.168.1.38`) & Office (`192.168.1.31`) cameras
- `camera_ai.py` - Multi-camera AI detector alias
- `start-ai-front-door.sh` - Launcher script for AI checker
- `summary.md` - Bandwidth optimization summary

## 🚪 AI Person Detection (Front Door & Office)

The `front_door_ai.py` / `camera_ai.py` service monitors specified camera streams (defaulting to **Front Door** `192.168.1.38` and **Office** `192.168.1.31`), detects people arriving at these areas using computer vision (OpenCV HOG + SVM), logs timestamped detection events per camera, saves snapshot images with bounding boxes, and can trigger webhooks or alerts.

### Quick Usage

```bash
# Monitor both Front Door and Office cameras (default)
python camera_ai.py

# Monitor specific camera only
python camera_ai.py --cameras Front
python camera_ai.py --cameras Office

# Run a single frame check across monitored cameras
python camera_ai.py --once

# Use custom webhook / alert command
python camera_ai.py --webhook "https://discord.com/api/webhooks/..." --cooldown 30
```

### Options

- `--cameras`: Comma-separated list of cameras to monitor (default: `Front,Office`)
- `--url`: Override single camera stream URL
- `--interval`: Frame check interval in seconds (default: `2.0`)
- `--confidence`: Detection confidence threshold (default: `0.4`)
- `--cooldown`: Alert cooldown period per camera in seconds (default: `30.0`)
- `--webhook`: Optional HTTP webhook endpoint to POST detection JSON
- `--command`: Shell command executed when a person is detected
- `--once`: Check single frame per camera and exit

### Logs & Snapshots

- **Text Log**: `logs/camera_ai.log` / `logs/front_door_ai.log`
- **JSON Event Log**: `logs/camera_events.json` / `logs/front_door_events.json`
- **Annotated Snapshots**: `logs/camera_snapshots/{camera}_person_YYYYMMDD_HHMMSS.jpg`


