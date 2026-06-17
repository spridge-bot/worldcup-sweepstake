#!/bin/zsh
# Mac mini updater: periodic full score refresh. The live watcher that drives
# the real-time relay is now a dedicated always-on launchd job
# (com.sweepstake.watch), so it's not spawned from here any more.
set -u
cd "$(dirname "$0")/.."
export PATH="/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin"

/usr/bin/python3 scripts/update_scores.py 2>&1 | tail -2
