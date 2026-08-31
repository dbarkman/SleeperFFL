# Deploying the waiver watcher to web2

The draft assistant runs locally on your Mac. Only the watcher needs a server,
because it has to keep taking snapshots while you are not looking.

## Install

```bash
# On web2, as david
sudo -u apache git -C /var/www/html clone <repo-url> SleeperFFL
cd /var/www/html/SleeperFFL
sudo -u apache /home/david/.local/bin/uv sync --frozen

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
* State lives in `.state/watch_<league_id>.json`. Delete it to re-baseline.
* The topic is `dbdev-ffl` on ntfy.sh. Subscribe on your phone to receive pushes.
