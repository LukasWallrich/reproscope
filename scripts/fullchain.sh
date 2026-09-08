#!/bin/zsh
# Usage: [S0_ARGS='--force-step extract'] scripts/fullchain.sh <paper_id> — Stage 0, then Stages 1-3 + report with retries, all logged under runs/logs/.
cd /Users/lukaswallrich/Documents/Coding/reproduction_pipeline
P=$1
[ -n "$P" ] && [ -f "corpus/$P/manifest.json" ] || { echo "no manifest for '$P'"; exit 1; }
mkdir -p runs/logs
for attempt in 1 2 3; do
  echo "--- $(date '+%F %T') stage 0 start $P (attempt $attempt)"
  .venv/bin/python -m reproscope run "$P" --stages 0 ${S0_ARGS:+${=S0_ARGS}} >> "runs/logs/stage0_$P.log" 2>&1
  rc=$?
  echo "--- $(date '+%F %T') stage 0 exit $rc $P"
  [ -f "runs/$P/stage0/done.json" ] && break
  sleep 120   # provider gateway errors clear on the minute scale; finished steps are cached
done
[ -f "runs/$P/stage0/done.json" ] || { echo "STAGE0 FAILED $P"; exit 1; }
.venv/bin/python scripts/chain_retry.py "$P"
echo "--- $(date '+%F %T') fullchain exit $? $P"
