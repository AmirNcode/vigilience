# Troubleshooting

Set this once per shell on the server:

```bash
cd ~/vigilience
alias vc='docker compose --project-name vigilience --env-file ~/.config/vigilience/production.env -f compose.yaml'
```

| Symptom | Check | Fix |
|---|---|---|
| Dashboard won't load | `vc ps`; `curl -I http://127.0.0.1:8123` | `vc up -d`; `docker logs --tail 100 vigilience-homeassistant` |
| All server metrics *Unavailable*, "metrics not collected" | `curl -s 127.0.0.1:61208/api/4/quicklook` | `vc restart glances`; `docker logs vigilience-glances` |
| Containers table empty | `curl -s 127.0.0.1:2375/containers/json \| head -c 200` | `vc restart docker-proxy glances` |
| WD drive "not mounted" but it is | `findmnt /mnt/media`; `curl -s 127.0.0.1:61208/api/4/fs` | Drive was mounted after Glances started with non-shared propagation: `vc restart glances` |
| Gateway shows *Unavailable* | `grep VIG_GATEWAY_HOST ~/.config/vigilience/production.env` | Set it, then `vc up -d homeassistant` (env changes need recreate, `up -d` does it) |
| Quick links missing | same, `VIG_*_URL` | as above |
| Deploy stops at "Configuration check failed" | Output shows the HA error and file/line | Fix in repo; nothing was restarted |
| Deploy refuses: "tracked files modified" | `git status` on server | `git stash` or `git checkout -- <file>`; never edit config on the server |
| Charts say "No statistics found" | New install | Hourly statistics appear after the first full hour |
| After reboot dashboard missing | `systemctl is-active docker`; `vc ps` | Containers use `restart: unless-stopped` and named volumes; `vc up -d` |
| HA warns about the HTTP config | — | Only if you added `http:` options; confirm in the dialog |

Logs:

```bash
docker logs --since 1h vigilience-homeassistant 2>&1 | grep -iE 'error|vig_'
```

Resource check:

```bash
docker stats --no-stream vigilience-homeassistant vigilience-glances vigilience-docker-proxy
```
