#!/bin/bash
# Sign "Lyricist Sync.app" inside-out with the Developer ID (hardened runtime + secure timestamp):
# every nested Mach-O (dylibs, .so, Qt plugins, helper executables) first, then the .framework bundles,
# then the app with mac/entitlements.plist. No --deep (Apple discourages it for signing).
#   mac/sign.sh APP IDENTITY [KEYCHAIN]     (IDENTITY "-" = ad-hoc, for unsigned PR builds)
set -euo pipefail
APP="$1"; ID="$2"; KC="${3:-}"
HERE="$(cd "$(dirname "$0")" && pwd)"
ENT="$HERE/entitlements.plist"
args=(--force --options runtime --sign "$ID")
if [ "$ID" != "-" ]; then args+=(--timestamp); fi
if [ -n "$KC" ]; then args+=(--keychain "$KC"); fi

# lists of what to sign, deepest first (python3: BSD sort/cut have no NUL options)
list_targets() {
  python3 - "$APP" "$1" <<'PY'
import os, sys
app, kind = sys.argv[1], sys.argv[2]
main = os.path.join(app, 'Contents', 'MacOS', 'LyricistSync')
out = []
for root, dirs, files in os.walk(os.path.join(app, 'Contents')):
    if kind == 'frameworks':
        out += [os.path.join(root, d) for d in dirs if d.endswith('.framework') and not os.path.islink(os.path.join(root, d))]
        continue
    for f in files:
        p = os.path.join(root, f)
        if os.path.islink(p) or p == main:
            continue
        with open(p, 'rb') as fh:
            magic = fh.read(4)
        if magic not in (b'\xcf\xfa\xed\xfe', b'\xce\xfa\xed\xfe', b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca'):
            continue
        if magic == b'\xca\xfe\xba\xbe' and p.endswith('.class'):
            continue   # Java class files share the fat magic
        parts = p.split(os.sep)
        fw = [i for i, x in enumerate(parts) if x.endswith('.framework')]
        if fw and parts[-1] == parts[fw[-1]][:-10] and 'Versions' in parts[fw[-1]:]:
            continue   # a framework's main binary: signed with its bundle
        out.append(p)
for p in sorted(out, key=lambda x: (-x.count(os.sep), x)):
    print(p)
PY
}

n=0
while IFS= read -r f; do
  codesign "${args[@]}" "$f"
  n=$((n + 1))
done < <(list_targets files)
echo "signed $n nested Mach-O files"

m=0
while IFS= read -r fw; do
  codesign "${args[@]}" "$fw"
  m=$((m + 1))
done < <(list_targets frameworks)
echo "signed $m frameworks"

# 3) the app (main executable + Info.plist + resources seal) with the entitlements
codesign "${args[@]}" --entitlements "$ENT" "$APP"
codesign --verify --deep --strict -v "$APP"
codesign -dv --verbose=4 "$APP" 2>&1 | grep -E '^(Identifier=|Format=|CodeDirectory |Authority=|Timestamp=|TeamIdentifier=|Runtime Version=)' || true
