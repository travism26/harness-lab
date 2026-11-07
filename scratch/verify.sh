#!/usr/bin/env bash
# Throwaway check for "Install spiffecli and confirm the unverified facts" (harness-lab #39).
# Downloads spiffecli v0.1.3, runs it headless from aid.toml, and prints what each
# unverified fact looks like at runtime. Token signatures are redacted.
# Usage: bash verify.sh            (spiffecli facts)
#        OPENROUTER_API_KEY=... bash verify.sh   (also the temperature:0 probe)
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
WORK="$(mktemp -d /tmp/spcli.XXXX)"
VER=0.1.3
TD=agent-identity.lab
SOCK=/tmp/aid
hdr() { printf -- '\n=== %s\n' "$*"; }

b64url_json() { # decode one base64url JWT segment
  local s="${1//-/+}"; s="${s//_//}"
  while (( ${#s} % 4 )); do s="$s="; done
  printf '%s' "$s" | base64 -d 2>/dev/null; echo
}

hdr "platform"
uname -sm
case "$(uname -s)-$(uname -m)" in
  Darwin-arm64) ASSET=darwin_arm64 ;; Darwin-x86_64) ASSET=darwin_amd64 ;;
  Linux-x86_64) ASSET=linux_amd64 ;;   Linux-aarch64) ASSET=linux_arm64 ;;
  *) echo "unsupported platform"; exit 1 ;;
esac

hdr "install (gh release download, checksum)"
cd "$WORK"
gh release download "v$VER" --repo defakto-security/spiffecli \
  -p "spiffecli_${VER}_${ASSET}.tar.gz" -p "spiffecli_${VER}_checksums.txt" || exit 1
grep "_${ASSET}.tar.gz" "spiffecli_${VER}_checksums.txt" | shasum -a 256 -c || exit 1
tar -xzf "spiffecli_${VER}_${ASSET}.tar.gz"
BIN="$WORK/spiffecli"
ls -l "$BIN"
if [[ "$(uname -s)" == Darwin ]]; then echo "xattrs: [$(xattr "$BIN" | tr '\n' ' ')]"; fi
"$BIN" --version 2>&1 || "$BIN" version 2>&1 || true

hdr "missing config, headless (stdin closed, 5s timeout)"
( "$BIN" run --config "$WORK/nope.toml" </dev/null >"$WORK/nope.log" 2>&1 & p=$!; sleep 5; kill $p 2>/dev/null && echo "still running after 5s (killed)" || echo "exited by itself"; )
sed 's/^/  | /' "$WORK/nope.log"

hdr "socket path over 104 bytes"
LONG="/tmp/$(printf 'x%.0s' {1..110})/a.sock"
cat >"$WORK/long.toml" <<EOF
[td."$TD".workload.long]
socket_path = "$LONG"
EOF
( "$BIN" run --config "$WORK/long.toml" </dev/null >"$WORK/long.log" 2>&1 & p=$!; sleep 3; kill $p 2>/dev/null && echo "still running after 3s (killed)" || echo "exited by itself"; )
sed 's/^/  | /' "$WORK/long.log" | head -5
rm -rf "/tmp/$(printf 'x%.0s' {1..110})"

hdr "start: spiffecli run --config aid.toml"
rm -rf "$SOCK"
sed "s#SOCKDIR#$SOCK#g" "$HERE/aid.toml" >"$WORK/aid.toml"
cat "$WORK/aid.toml"
"$BIN" run --config "$WORK/aid.toml" </dev/null >"$WORK/run.log" 2>&1 &
RUNPID=$!
trap 'kill $RUNPID 2>/dev/null' EXIT
for i in $(seq 1 50); do
  [[ -S $SOCK/permission-agent.sock && -S $SOCK/warden.sock && -S $SOCK/unlisted-agent.sock && -S $SOCK/short-lived.sock ]] && break
  sleep 0.2
done
ls -l "$SOCK"
echo "run log:"; sed 's/^/  | /' "$WORK/run.log"
echo "listening on :8080?"
if command -v lsof >/dev/null; then lsof -nP -iTCP:8080 -sTCP:LISTEN || echo "  nothing on :8080"
else ss -ltn | grep ':8080' || echo "  nothing on :8080"; fi

for w in permission-agent warden unlisted-agent short-lived; do
  hdr "get jwt-svid --audiences warden  ($w)"
  T="$("$BIN" get jwt-svid -s "unix://$SOCK/$w.sock" --audiences warden 2>&1)"
  IFS=. read -r H P S <<<"$T"
  echo "token: $H.$P.<sig redacted, ${#S} chars>"
  echo "header: $(b64url_json "$H")"
  CL="$(b64url_json "$P")"; echo "claims: $CL"
  iat=$(sed -E 's/.*"iat":([0-9]+).*/\1/' <<<"$CL"); exp=$(sed -E 's/.*"exp":([0-9]+).*/\1/' <<<"$CL")
  echo "exp - iat = $((exp - iat))s; has iss: $(grep -q '"iss"' <<<"$CL" && echo yes || echo no); has nbf: $(grep -q '"nbf"' <<<"$CL" && echo yes || echo no)"
  [[ $w == permission-agent ]] && echo "$T" >"$WORK/agent.jwt"
done

hdr "two audiences"
T="$("$BIN" get jwt-svid -s "unix://$SOCK/permission-agent.sock" --audiences warden,other)"
IFS=. read -r H P S <<<"$T"; echo "claims: $(b64url_json "$P")"

hdr "no audiences"
"$BIN" get jwt-svid -s "unix://$SOCK/permission-agent.sock" 2>&1 | head -3

hdr "--decode"
"$BIN" get jwt-svid -s "unix://$SOCK/permission-agent.sock" --audiences warden --decode 2>&1

hdr "--decode plus --filename"
"$BIN" get jwt-svid -s "unix://$SOCK/permission-agent.sock" --audiences warden --decode --filename "$WORK/both.jwt" 2>&1
echo "file written: $([[ -f $WORK/both.jwt ]] && echo yes || echo no)"

hdr "--filename"
"$BIN" get jwt-svid -s "unix://$SOCK/permission-agent.sock" --audiences warden --filename "$WORK/f.jwt" 2>&1
ls -l "$WORK/f.jwt" 2>&1

for fmt in summary json; do
  hdr "inspect jwt --format $fmt --headers"
  "$BIN" inspect jwt --format "$fmt" --headers "$WORK/agent.jwt" 2>&1 \
    || "$BIN" inspect jwt --format "$fmt" --headers --filename "$WORK/agent.jwt" 2>&1 \
    || "$BIN" inspect jwt --help 2>&1 | sed -n '1,25p'
done

hdr "get bundle jwt -t $TD  (from the warden socket)"
"$BIN" get bundle jwt -s "unix://$SOCK/warden.sock" -t "$TD" --filename "$WORK/bundle.jwks" 2>&1
cat "$WORK/bundle.jwks"; echo

hdr "get bundle --format jwt (the doc page's form)"
"$BIN" get bundle --format jwt -s "unix://$SOCK/warden.sock" -t "$TD" 2>&1 | head -3

hdr "verify jwt-svid via the warden socket (go-spiffe NewJWTSource path)"
"$BIN" verify jwt-svid -s "unix://$SOCK/warden.sock" --audiences warden --filename "$WORK/agent.jwt" 2>&1; echo "exit=$?"

hdr "verify jwt-svid --bundle file"
"$BIN" verify jwt-svid --bundle "$WORK/bundle.jwks" --trust-domain "$TD" --audiences warden --filename "$WORK/agent.jwt" 2>&1; echo "exit=$?"

hdr "verify an unlisted-agent token (same trust domain)"
"$BIN" get jwt-svid -s "unix://$SOCK/unlisted-agent.sock" --audiences warden --filename "$WORK/unlisted.jwt"
"$BIN" verify jwt-svid -s "unix://$SOCK/warden.sock" --audiences warden --filename "$WORK/unlisted.jwt" 2>&1; echo "exit=$?"

hdr "short-lived token, 3s after mint"
"$BIN" get jwt-svid -s "unix://$SOCK/short-lived.sock" --audiences warden --filename "$WORK/short.jwt"
sleep 3
"$BIN" verify jwt-svid -s "unix://$SOCK/warden.sock" --audiences warden --filename "$WORK/short.jwt" 2>&1; echo "exit=$?"

hdr "verify with the wrong audience"
"$BIN" verify jwt-svid -s "unix://$SOCK/warden.sock" --audiences billing --filename "$WORK/agent.jwt" 2>&1 | head -3

hdr "restart: old token against the new keys"
kill $RUNPID; wait $RUNPID 2>/dev/null
"$BIN" run --config "$WORK/aid.toml" </dev/null >"$WORK/run2.log" 2>&1 &
RUNPID=$!
for i in $(seq 1 50); do [[ -S $SOCK/warden.sock ]] && break; sleep 0.2; done
sleep 0.5
"$BIN" verify jwt-svid -s "unix://$SOCK/warden.sock" --audiences warden --filename "$WORK/agent.jwt" 2>&1 | head -3

if [[ -n "${OPENROUTER_API_KEY:-}" ]]; then
  hdr "OpenRouter: temperature 0 + strict tool, anthropic/claude-haiku-5.5"
  curl -sS https://openrouter.ai/api/v1/messages \
    -H "Authorization: Bearer $OPENROUTER_API_KEY" -H 'content-type: application/json' \
    -H 'anthropic-version: 2023-06-01' -d @- <<'JSON' | tee "$WORK/or.json"; echo
{
  "model": "anthropic/claude-haiku-5.5",
  "max_tokens": 300,
  "temperature": 0,
  "tool_choice": {"type": "auto"},
  "system": "You answer permission questions only by calling lookup_permission.",
  "tools": [{
    "name": "lookup_permission",
    "description": "Look up whether a user holds a permission.",
    "strict": true,
    "input_schema": {
      "type": "object",
      "properties": {
        "target": {"type": "string"},
        "permission": {"type": "string", "enum": ["invoice:approve", "invoice:read", "permission:read"]}
      },
      "required": ["target", "permission"],
      "additionalProperties": false
    }
  }],
  "messages": [{"role": "user", "content": "Can Tom approve invoices?"}]
}
JSON
else
  hdr "OpenRouter probe skipped (OPENROUTER_API_KEY unset)"
fi

hdr "done"
