---
name: homelab-deploy
description: Use when the user asks to deploy, host or run an app on their home server (the HP server, mint, the linus server, homelab) so it is reachable on the home network.
---

# Deploy to the home server

Before doing anything, read the full guide:

    /Users/amir/Workspace/homelab-dashboard/docs/deploying-apps.md

Then follow it: make the app meet "What the app must have", add a
`homelab.yaml`, pick a free port with `homelab-deploy ls`, run
`homelab-deploy` from the app folder, and report the URL. Ask before using
`--force` or `homelab-deploy down`.
