#!/bin/bash
# Submit FILE (.zip/.dmg) to Apple's notary service with an App Store Connect API key and wait.
#   mac/notarize.sh FILE KEY.p8 KEY_ID ISSUER_ID OUT.json
# Prints "id=<submission id>" and "status=<status>" lines (also for $GITHUB_OUTPUT); exit 1 unless Accepted.
set -uo pipefail
FILE="$1"; KEY="$2"; KID="$3"; ISS="$4"; OUT="$5"
for attempt in 1 2 3; do
  xcrun notarytool submit "$FILE" --key "$KEY" --key-id "$KID" --issuer "$ISS" \
    --wait --timeout 50m --output-format json > "$OUT"
  rc=$?
  id="$(plutil -extract id raw -o - "$OUT" 2>/dev/null || true)"
  [ -n "$id" ] && break
  echo "notarytool submit failed (exit $rc, attempt $attempt):"; cat "$OUT"; sleep 30
done
cat "$OUT"; echo
status="$(plutil -extract status raw -o - "$OUT" 2>/dev/null || true)"
echo "id=${id:-}"
echo "status=${status:-unknown}"
if [ "$status" != "Accepted" ]; then
  if [ -n "${id:-}" ]; then
    echo "---- notary log ----"
    xcrun notarytool log "$id" --key "$KEY" --key-id "$KID" --issuer "$ISS" || true
  fi
  exit 1
fi
xcrun notarytool log "$id" --key "$KEY" --key-id "$KID" --issuer "$ISS" "${OUT%.json}-log.json" >/dev/null 2>&1 || true
exit 0
