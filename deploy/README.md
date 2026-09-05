# Deploying the waiver watcher to web2

The draft assistant runs locally on your Mac. Only the watcher needs a server,
because it has to keep taking snapshots while you are not looking.

## Install

```bash
# On web2, as david
sudo -u apache git -C /var/www/html clone <repo-url> SleeperFFL
cd /var/www/html/SleeperFFL
sudo -u apache env UV_CACHE_DIR=/var/www/html/SleeperFFL/.uv-cache \
  /usr/local/bin/uv sync --frozen

sudo install -m 644 deploy/sleeperffl-watch.service /etc/systemd/system/
sudo install -m 644 deploy/sleeperffl-watch.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now sleeperffl-watch.timer
```

## Verify

```bash
systemctl list-timers sleeperffl-watch.timer
sudo systemctl start sleeperffl-watch.service   # force one pass
journalctl -u sleeperffl-watch.service -n 50 --no-pager
```

The first run only records a baseline — drops are detected by comparing against
the previous run, so alerts begin from the second pass onward.

## Notes

* `ExecStart` uses the venv binary directly rather than `uv run`, matching the
  other services on the fleet.
* Use `/usr/local/bin/uv`, not the copy under `~david`. `/home/david` is mode
  700, so the `apache` user cannot traverse it.
* uv needs a writable cache. `apache`'s home is not, hence `UV_CACHE_DIR`.
* State lives in `.state/watch_<league_id>.json`. Delete it to re-baseline.
* Notifications go to a self-hosted ntfy at `https://ntfy.cla.ms`, topic
  `dbdev-ffl`. ntfy listens on `127.0.0.1:2586` and Apache terminates TLS.
* The server denies anonymous access, so the watcher needs a token:

  ```bash
  sudo install -d -m 750 -o root -g apache /etc/sleeperffl
  sudo sh -c 'umask 027; echo "SLEEPERFFL_NTFY_TOKEN=tk_..." > /etc/sleeperffl/env'
  sudo chgrp apache /etc/sleeperffl/env
  ```

  Generate a token with `sudo ntfy token add --label=sleeperffl-watcher dbdev`.
  It never lands in the repo.
