#!/usr/bin/env bash
# PoC 02-web-snapshots: monolith single-file snapshots of 5 real pages.
# Snapshot HTML embeds subresources as data: URLs — opening the file with
# networking disabled proves self-containment (see report).
set -u
MONO=/tmp/mono/monolith
OUT="$(cd "$(dirname "$0")" && pwd)/snapshots"
mkdir -p "$OUT"
PAGES=(
  "https://lucumr.pocoo.org/2026/9/7/astra-why/"
  "https://simonwillison.net/2026/Sep/10/calif-research/"
  "https://blog.vllm.ai/2025/01/27/v1-alpha-release.html"
  "https://www.ruanyifeng.com/blog/2026/09/weekly-issue-411.html"
  "https://openai.com/news/"
)
i=0
ok=0
for url in "${PAGES[@]}"; do
  i=$((i+1))
  dest="$OUT/snap-$i.html"
  /usr/bin/time -v "$MONO" "$url" -o "$dest" -I -t 60 2>/tmp/mono-time.log
  rc=$?
  size=$(stat -c %s "$dest" 2>/dev/null || echo 0)
  secs=$(grep "Elapsed (wall" /tmp/mono-time.log | awk -F': ' '{print $NF}')
  rss=$(grep "Maximum resident" /tmp/mono-time.log | awk -F': ' '{print $NF/1024}')
  if [ "$rc" = "0" ] && [ "$size" -gt 0 ]; then ok=$((ok+1)); st=OK; else st=FAIL; fi
  printf "[%d] %s %ss %.2fMB rss=%sMB %s\n" "$i" "$st" "$secs" "$(echo "$size/1048576" | bc -l)" "$rss" "$url"
done
echo "snapshots OK: $ok/5 -> $OUT"
