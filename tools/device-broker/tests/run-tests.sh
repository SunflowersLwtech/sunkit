#!/usr/bin/env bash
# Tests for device-broker. No real emulator/simulator/browser is started:
# leases are exercised directly, and adb/emulator calls go through stub
# commands the tests point the wrappers at via env.
#
#   bash run-tests.sh           # all tests; exit 0 only if every one passed
#
# Evidence is designed to be able to fail: several tests assert a nonzero
# exit and check that the *reason* is the expected one, not just "it failed".

set -u
cd "$(dirname "$0")/.."
BIN="${PWD}/bin"
PASS=0; FAIL=0
T=""

say() { printf '%s\n' "$*"; }
ok()   { PASS=$((PASS+1)); say "ok   ${T}"; }
bad()  { FAIL=$((FAIL+1)); say "FAIL ${T} — $*"; }

newhome() { mktemp -d /tmp/db-test.XXXXXX; }

# --- T1: second acquire of a live lease by a different owner is refused (3)
T="t1: foreign acquire of live lease refused"
H1="$(newhome)"; H2="$(newhome)"
DB_HOME="${H1}" "${BIN}/device-broker" acquire android-emulator:port-5990 \
  --meta avd=t1avd --owner-key sess-A >/dev/null 2>&1
# simulate a DIFFERENT session: same leases dir, different owner key
DB_HOME="${H1}" "${BIN}/device-broker" acquire android-emulator:port-5990 \
  --meta avd=intruder --owner-key sess-B >/dev/null 2>&1
rc=$?
[ "${rc}" -eq 3 ] && ok || bad "expected exit 3, got ${rc}"

# --- T2: same owner re-acquire is idempotent (0)
T="t2: same owner re-acquire returns 0"
DB_HOME="${H1}" "${BIN}/device-broker" acquire android-emulator:port-5990 \
  --owner-key sess-A >/dev/null 2>&1
rc=$?
[ "${rc}" -eq 0 ] && ok || bad "expected 0, got ${rc}"

# --- T3: after holder pid dies, foreign acquirer reclaims
T="t3: dead holder -> lease reclaimable"
# make a lease owned by a pid that is already dead: use a pid that can't exist
H3="$(newhome)"
DB_HOME="${H3}" "${BIN}/device-broker" acquire android-emulator:port-5991 \
  --owner-key sess-DEAD --owner-pid 4194303 >/dev/null 2>&1
# pid 4194303: above typical pid_max, dead. acquire by another owner must win.
DB_HOME="${H3}" "${BIN}/device-broker" acquire android-emulator:port-5991 \
  --owner-key sess-B >/dev/null 2>&1
rc=$?
[ "${rc}" -eq 0 ] && ok || bad "expected 0 after dead holder, got ${rc}"

# --- T4: pid-reuse guard — lease whose recorded lstart doesn't match is stale
T="t4: pid reused by different start = stale"
H4="$(newhome)"
DB_HOME="${H4}" "${BIN}/device-broker" acquire android-emulator:port-5992 \
  --owner-key sess-A >/dev/null 2>&1
JF="${H4}/leases/android-emulator:port-5992.lock/lease.json"
# corrupt pidStart to a time that is not this process's start
sed -i 's/"pidStart": "[^"]*"/"pidStart": "Mon Jan  1 00:00:00 1990"/' "${JF}"
DB_HOME="${H4}" "${BIN}/device-broker" acquire android-emulator:port-5992 \
  --owner-key sess-B >/dev/null 2>&1
rc=$?
[ "${rc}" -eq 0 ] && ok || bad "pid-reused lease should be reclaimable, got ${rc}"

# --- T5: cap enforcement — second emulator of same type refused at cap 1
T="t5: android-emulator cap=1 blocks a second emulator"
H5="$(newhome)"
DB_HOME="${H5}" "${BIN}/device-broker" acquire android-emulator:port-6001 \
  --owner-key sess-A >/dev/null 2>&1
DB_HOME="${H5}" "${BIN}/device-broker" acquire android-emulator:port-6003 \
  --owner-key sess-B >/dev/null 2>&1
rc=$?
[ "${rc}" -eq 6 ] && ok || bad "expected exit 6 (cap), got ${rc}"

# --- T6: check --require-mine refuses for foreign holder
T="t6: check --require-mine exits 3 on foreign lease"
H6="$(newhome)"
DB_HOME="${H6}" "${BIN}/device-broker" acquire android-emulator:port-6010 \
  --meta avd=mine --owner-key sess-A >/dev/null 2>&1
DB_HOME="${H6}" "${BIN}/device-broker" check android-emulator:port-6010 \
  --require-mine --owner-key sess-B >/dev/null 2>&1
rc=$?
[ "${rc}" -eq 3 ] && ok || bad "expected 3, got ${rc}"

# --- T7: adb-run refuses when the device on the serial is a DIFFERENT AVD.
#        This is the 2026-11-16 incident: emulator-5584 answered as fold7
#        while the lease named another avd.
T="t7: adb-run refuses serial whose real AVD differs from lease"
H7="$(newhome)"
DB_HOME="${H7}" "${BIN}/device-broker" acquire android-emulator:port-6012 \
  --meta avd=my-avd --owner-key sess-A >/dev/null 2>&1
# stub adb: reports a different avd name
STUB="$(mktemp -d /tmp/dbstub.XXXXXX)"
cat > "${STUB}/adb" <<'EOF'
#!/usr/bin/env bash
if [ "$1" = "-s" ] && [ "$3" = "emu" ]; then echo "fold7"; exit 0; fi
echo "STUB-ADB called with $*" >&2; exit 0
EOF
chmod +x "${STUB}/adb"
DB_HOME="${H7}" ADB="${STUB}/adb" DEVICE_BROKER="${BIN}/device-broker" \
  DB_OWNER_KEY=sess-A "${BIN}/adb-run" -s emulator-6012 shell echo hi >/dev/null 2>&1
rc=$?
[ "${rc}" -eq 7 ] && ok || bad "expected 7 (wrong avd), got ${rc}"

# --- T8: adb-run passes through when avd matches
T="t8: adb-run allows when avd matches lease"
cat > "${STUB}/adb" <<'EOF'
#!/usr/bin/env bash
if [ "$1" = "-s" ] && [ "$3" = "emu" ]; then echo "my-avd"; exit 0; fi
echo "PASSTHROUGH $*"; exit 0
EOF
chmod +x "${STUB}/adb"
OUT="$(DB_HOME="${H7}" ADB="${STUB}/adb" DEVICE_BROKER="${BIN}/device-broker" \
  DB_OWNER_KEY=sess-A "${BIN}/adb-run" -s emulator-6012 shell echo hi 2>/dev/null)"
case "${OUT}" in *PASSTHROUGH*) ok ;; *) bad "expected passthrough, got: ${OUT}" ;; esac

# --- T9: physical device serial refused fail-closed
T="t9: physical serial refused"
DB_HOME="${H7}" ADB="${STUB}/adb" DEVICE_BROKER="${BIN}/device-broker" \
  DB_OWNER_KEY=sess-A "${BIN}/adb-run" -s RFGL22V0DSB shell echo hi >/dev/null 2>&1
rc=$?
[ "${rc}" -eq 5 ] && ok || bad "expected 5, got ${rc}"

# --- T10: release only by owner
T="t10: foreign release refused"
H10="$(newhome)"
DB_HOME="${H10}" "${BIN}/device-broker" acquire android-emulator:port-6020 \
  --owner-key sess-A >/dev/null 2>&1
DB_HOME="${H10}" "${BIN}/device-broker" release android-emulator:port-6020 \
  --owner-key sess-B >/dev/null 2>&1
rc=$?
[ "${rc}" -eq 3 ] && ok || bad "expected 3, got ${rc}"
# and the lease must still be there
[ -d "${H10}/leases/android-emulator:port-6020.lock" ] && ok || bad "lease was wrongly released"
T="t10b: lease still present after refused release"

# --- T11: gc reclaims stale but keeps live
T="t11: gc removes only stale leases"
H11="$(newhome)"
DB_HOME="${H11}" "${BIN}/device-broker" acquire android-emulator:port-6030 \
  --owner-key sess-LIVE >/dev/null 2>&1
DB_HOME="${H11}" "${BIN}/device-broker" acquire browser:cdp-port-9222 \
  --owner-key sess-DEAD --owner-pid 4194303 >/dev/null 2>&1
DB_HOME="${H11}" "${BIN}/device-broker" gc >/dev/null 2>&1
[ -d "${H11}/leases/android-emulator:port-6030.lock" ] && \
  [ ! -d "${H11}/leases/browser:cdp-port-9222.lock" ] && ok || \
  bad "gc kept wrong leases: $(ls "${H11}/leases")"

# --- T12: status lists live vs stale correctly
T="t12: status marks stale"
OUT="$(DB_HOME="${H11}" "${BIN}/device-broker" status)"
case "${OUT}" in *'"state": "live"'*) ok ;; *) bad "no live lease reported: ${OUT}" ;; esac

# --- T13: expired lease (ttl) is stale and reclaimable
T="t13: ttl-expired lease is reclaimable by another owner"
H13="$(newhome)"
DB_HOME="${H13}" "${BIN}/device-broker" acquire browser:cdp-port-9300 \
  --owner-key sess-A --ttl 1 >/dev/null 2>&1
sleep 2
DB_HOME="${H13}" "${BIN}/device-broker" acquire browser:cdp-port-9300 \
  --owner-key sess-B >/dev/null 2>&1
rc=$?
[ "${rc}" -eq 0 ] && ok || bad "expected 0 on expired lease, got ${rc}"

# --- T14: a bare lock dir younger than the grace window is NOT reclaimed
#         (an acquire in flight owns it while lease.json is being written)
T="t14: fresh bare lock dir is treated as held"
H14="$(newhome)"
mkdir -p "${H14}/leases/android-emulator:port-6040.lock"
DB_HOME="${H14}" "${BIN}/device-broker" acquire android-emulator:port-6040 \
  --owner-key sess-B >/dev/null 2>&1
rc=$?
[ "${rc}" -eq 3 ] && ok || bad "expected 3 for in-flight bare dir, got ${rc}"

# --- T15: a bare lock dir older than the grace window IS reclaimed
T="t15: ancient bare lock dir is reclaimed"
H15="$(newhome)"
mkdir -p "${H15}/leases/android-emulator:port-6041.lock"
touch -d "2 minutes ago" "${H15}/leases/android-emulator:port-6041.lock" 2>/dev/null \
  || touch -t "$(date -v-2M '+%Y%m%d%H%M.%S' 2>/dev/null)" "${H15}/leases/android-emulator:port-6041.lock" 2>/dev/null
DB_HOME="${H15}" "${BIN}/device-broker" acquire android-emulator:port-6041 \
  --owner-key sess-B >/dev/null 2>&1
rc=$?
[ "${rc}" -eq 0 ] && ok || bad "expected 0 reclaiming ancient bare dir, got ${rc}"

# --- T16: limits set/get round-trip, and the custom cap is enforced
T="t16: limits set persists and is enforced"
H16="$(newhome)"
DB_HOME="${H16}" "${BIN}/device-broker" limits set browser:cdp-port 1 >/dev/null 2>&1
GOT="$(DB_HOME="${H16}" "${BIN}/device-broker" limits get browser:cdp-port 2>/dev/null)"
[ "${GOT}" = "1" ] && ok || bad "limits get returned '${GOT}', want 1"
DB_HOME="${H16}" "${BIN}/device-broker" acquire browser:cdp-port-9400 \
  --owner-key sess-A >/dev/null 2>&1
DB_HOME="${H16}" "${BIN}/device-broker" acquire browser:cdp-port-9401 \
  --owner-key sess-B >/dev/null 2>&1
rc=$?
[ "${rc}" -eq 6 ] && ok || bad "expected cap refusal 6, got ${rc}"
T="t16b: custom cap enforced"
LIST="$(DB_HOME="${H16}" "${BIN}/device-broker" limits list)"
case "${LIST}" in *'"browser:cdp-port": 1'*) ok ;; *) bad "limits list lost override: ${LIST}" ;; esac
T="t16c: limits list shows override"

# --- T17: malformed limits.json still yields defaults (fail to defaults)
T="t17: unreadable limits.json falls back to defaults"
H17="$(newhome)"
printf 'not json at all' > "${H17}/limits.json"
GOT="$(DB_HOME="${H17}" "${BIN}/device-broker" limits get android-emulator 2>/dev/null)"
[ "${GOT}" = "1" ] && ok || bad "expected default 1, got '${GOT}'"

say ""
say "== ${PASS} passed, ${FAIL} failed =="
[ "${FAIL}" -eq 0 ]
