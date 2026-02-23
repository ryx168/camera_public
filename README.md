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
- `summary.md` - Bandwidth optimization summary
