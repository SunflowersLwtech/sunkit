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

# Every temp dir this run makes lives under one root, removed on exit: a run
# used to leave its homes and stub dirs behind (21 under TMPDIR after one).
TESTROOT="$(mktemp -d "${TMPDIR:-/tmp}/db-tests.XXXXXX")"
trap 'rm -rf "${TESTROOT}"' EXIT

newhome() { mktemp -d "${TESTROOT}/home.XXXXXX"; }

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
sed 's/"pidStart": "[^"]*"/"pidStart": "Mon Jan  1 00:00:00 1990"/' "${JF}" > "${JF}.t" && mv "${JF}.t" "${JF}"
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
STUB="$(mktemp -d "${TESTROOT}/stub.XXXXXX")"
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

# --- T18: the simulator wrapper, against a stub xcrun (first on PATH) that
#          keeps a list of booted UDIDs and logs what it was asked. Nothing
#          real boots. simctl-run exits once `simctl boot` returns, so its pid
#          cannot keep the leases: they live while the simulator is booted.
SIMSTUB="$(mktemp -d "${TESTROOT}/sim.XXXXXX")"
cat > "${SIMSTUB}/xcrun" <<'EOF'
#!/usr/bin/env bash
F="${XCRUN_STUB_BOOTED:?}"
echo "xcrun $*" >> "${XCRUN_STUB_LOG:?}"
[ "$1" = simctl ] || exit 0
case "$2" in
  boot) grep -qx "$3" "$F" 2>/dev/null || echo "$3" >> "$F" ;;
  shutdown) grep -vx "$3" "$F" > "$F.n" 2>/dev/null; mv "$F.n" "$F" ;;
  list) [ -n "${XCRUN_STUB_LIST_FAIL:-}" ] && exit 1
        echo "== Devices =="; echo "-- iOS 26.5 --"
        # As real xcrun: UDIDs print in uppercase, whatever case boot was given.
        while read -r u; do [ -n "$u" ] && echo "    iPhone 17 ($(printf '%s' "$u" | tr '[:lower:]' '[:upper:]')) (${XCRUN_STUB_STATE:-Booted}) "; done < "$F" ;;
esac
exit 0
EOF
chmod +x "${SIMSTUB}/xcrun"
export XCRUN_STUB_BOOTED="${SIMSTUB}/booted" XCRUN_STUB_LOG="${SIMSTUB}/xcrun.log"
: > "${XCRUN_STUB_BOOTED}"; : > "${XCRUN_STUB_LOG}"
H18="$(newhome)"
# sim KEY simctl-run-args…  (KEY "-": no owner key in the environment at all)
sim() {
  local key="$1"; shift
  if [ "${key}" = - ]; then
    env -u DB_OWNER_KEY -u DB_SESSION -u OWNER_KEY DB_HOME="${H18}" PATH="${SIMSTUB}:${PATH}" \
      DEVICE_BROKER="${BIN}/device-broker" "${BIN}/simctl-run" "$@"
  else
    env -u DB_SESSION -u OWNER_KEY DB_OWNER_KEY="${key}" DB_HOME="${H18}" PATH="${SIMSTUB}:${PATH}" \
      DEVICE_BROKER="${BIN}/device-broker" "${BIN}/simctl-run" "$@"
  fi
}
# simstate RESOURCE -> live | stale | unknown | (nothing: no lease)
simstate() {
  DB_HOME="${H18}" PATH="${SIMSTUB}:${PATH}" "${BIN}/device-broker" status 2>/dev/null \
    | sed -n 's/.*"resource": "'"$1"'", "state": "\([a-z]*\)".*/\1/p' | head -1
}

T="t18a: simctl-run boot: the session's two leases stay live while its simulator is booted"
sim sess-A boot AAAA-1111 >/dev/null 2>&1; rc=$?
s1="$(simstate ios-simulator:host)"; s2="$(simstate ios-simulator:udid-AAAA-1111)"
[ "${rc}" -eq 0 ] && [ "${s1}" = live ] && [ "${s2}" = live ] && ok || \
  bad "boot rc=${rc}, ios-simulator:host ${s1:-none}, udid lease ${s2:-none}"

T="t18b: a second session's boot is refused (3: the machine's one simulator) and boots nothing"
sim sess-B boot BBBB-2222 >/dev/null 2>&1; rc=$?
if [ "${rc}" -eq 3 ] && ! grep -q "boot BBBB-2222" "${XCRUN_STUB_LOG}"; then ok
else bad "rc=${rc}; xcrun was asked: $(tr '\n' ';' < "${XCRUN_STUB_LOG}")"; fi

T="t18c: the session that booted it shuts it down through the wrapper (0), and both leases go"
sim sess-A shutdown AAAA-1111 >/dev/null 2>&1; rc=$?
if [ "${rc}" -eq 0 ] && grep -q "shutdown AAAA-1111" "${XCRUN_STUB_LOG}" && \
   [ ! -d "${H18}/leases/ios-simulator:host.lock" ] && [ ! -d "${H18}/leases/ios-simulator:udid-AAAA-1111.lock" ]; then ok
else bad "rc=${rc}; leases left: $(ls "${H18}/leases" | tr '\n' ' ')"; fi

T="t18d: a simulator shut down outside the wrapper leaves its leases stale: the next session boots"
sim sess-A boot AAAA-1111 >/dev/null 2>&1
: > "${XCRUN_STUB_BOOTED}"      # shut down by hand, not through simctl-run
sim sess-B boot BBBB-2222 >/dev/null 2>&1; rc=$?
s1="$(simstate ios-simulator:udid-BBBB-2222)"
[ "${rc}" -eq 0 ] && [ "${s1}" = live ] && ok || bad "rc=${rc}, sess-B's udid lease ${s1:-none}"
sim sess-B shutdown BBBB-2222 >/dev/null 2>&1

T="t18e: simctl-run boot with no owner key refuses (4) before it leases or boots anything"
: > "${XCRUN_STUB_LOG}"
sim - boot CCCC-3333 >/dev/null 2>&1; rc=$?
if [ "${rc}" -eq 4 ] && [ ! -s "${XCRUN_STUB_LOG}" ] && [ ! -d "${H18}/leases/ios-simulator:udid-CCCC-3333.lock" ] && \
   [ ! -d "${H18}/leases/ios-simulator:host.lock" ]; then ok
else bad "rc=${rc}; xcrun was asked: $(tr '\n' ';' < "${XCRUN_STUB_LOG}"); leases: $(ls "${H18}/leases" | tr '\n' ' ')"; fi

# --- T19: a lease that cannot be read is held, not free (fail closed)
H19="$(newhome)"
L19A="${H19}/leases/android-emulator:port-6050.lock"
L19B="${H19}/leases/android-emulator:port-6052.lock"
mkdir -p "${L19A}" "${L19B}"
: > "${L19A}/lease.json"
printf '{"schemaVersion": 1, "ownerKey": "sess-A", "owner": {"pid": "x"}}\n' > "${L19B}/lease.json"

T="t19a: an empty lease.json is held: another session's acquire exits 4 and leaves it as it was"
DB_HOME="${H19}" "${BIN}/device-broker" acquire android-emulator:port-6050 \
  --owner-key sess-B >/dev/null 2>&1; rc=$?
[ "${rc}" -eq 4 ] && [ -f "${L19A}/lease.json" ] && [ ! -s "${L19A}/lease.json" ] && ok || \
  bad "rc=${rc}; lease.json now: $(cat "${L19A}/lease.json" 2>/dev/null | tr '\n' ' ')"

T="t19b: a lease.json whose pid cannot be read: check says it cannot tell (4), not free (0)"
DB_HOME="${H19}" "${BIN}/device-broker" check android-emulator:port-6052 \
  --owner-key sess-C >/dev/null 2>&1; rc=$?
[ "${rc}" -eq 4 ] && ok || bad "expected 4, got ${rc}"

T="t19c: an unreadable lease counts against its cap: another emulator port is refused (6)"
DB_HOME="${H19}" "${BIN}/device-broker" acquire android-emulator:port-6054 \
  --owner-key sess-D >/dev/null 2>&1; rc=$?
[ "${rc}" -eq 6 ] && ok || bad "expected 6, got ${rc}"

T="t19d: another session cannot release an unreadable lease (refused, the lease still there)"
DB_HOME="${H19}" "${BIN}/device-broker" release android-emulator:port-6052 \
  --owner-key sess-C >/dev/null 2>&1; rc=$?
[ "${rc}" -ne 0 ] && [ -s "${L19B}/lease.json" ] && ok || bad "rc=${rc}; lease left: $(ls "${H19}/leases" | tr '\n' ' ')"

T="t19e: an unreadable lease.json nothing has touched for the grace window is reclaimed (0)"
H19E="$(newhome)"
L19E="${H19E}/leases/android-emulator:port-6056.lock"
mkdir -p "${L19E}"; : > "${L19E}/lease.json"
for f in "${L19E}/lease.json" "${L19E}"; do
  touch -d "2 minutes ago" "${f}" 2>/dev/null \
    || touch -t "$(date -v-2M '+%Y%m%d%H%M.%S' 2>/dev/null)" "${f}" 2>/dev/null
done
DB_HOME="${H19E}" "${BIN}/device-broker" acquire android-emulator:port-6056 \
  --owner-key sess-B >/dev/null 2>&1; rc=$?
own="$(sed -n 's/.*"ownerKey": *"\([^"]*\)".*/\1/p' "${L19E}/lease.json" 2>/dev/null | head -1)"
[ "${rc}" -eq 0 ] && [ "${own}" = sess-B ] && ok || bad "rc=${rc}, owner ${own:-none}"

# --- T20: a lease being written is never read half-written. A stub hostname
#          (called while lease.json's contents are made) holds the first
#          acquire mid-write; a second session's acquire meanwhile must see the
#          lease held by another (3) — not an empty lease.json (4, or taken).
SLOW="$(mktemp -d "${TESTROOT}/slow.XXXXXX")"
printf '#!/usr/bin/env bash\nsleep 3\necho slowhost\n' > "${SLOW}/hostname"
chmod +x "${SLOW}/hostname"
H20="$(newhome)"
L20="${H20}/leases/browser:cdp-port-9500.lock"
T="t20: while one acquire is still writing its lease, another's sees it held (3), and the first's lease is whole"
DB_HOME="${H20}" PATH="${SLOW}:${PATH}" "${BIN}/device-broker" acquire browser:cdp-port-9500 \
  --owner-key sess-A --owner-pid $$ >/dev/null 2>&1 &
APID=$!
sleep 1
DB_HOME="${H20}" "${BIN}/device-broker" acquire browser:cdp-port-9500 \
  --owner-key sess-B >/dev/null 2>&1; rcb=$?
wait "${APID}"; rca=$?
own="$(sed -n 's/.*"ownerKey": *"\([^"]*\)".*/\1/p' "${L20}/lease.json" 2>/dev/null | head -1)"
extra="$(ls -A "${L20}" 2>/dev/null | grep -v '^lease.json$' | tr '\n' ' ')"
if [ "${rcb}" -eq 3 ] && [ "${rca}" -eq 0 ] && [ "${own}" = sess-A ] && grep -q '"acquiredAt"' "${L20}/lease.json" && [ -z "${extra}" ]; then ok
else bad "second acquire rc=${rcb}, first rc=${rca}, owner ${own:-none}, other files: ${extra:-none}"; fi

# --- T21: a lowercase UDID (issue #77 §1). The stub prints UDIDs uppercase,
#          as real xcrun does; simctl-run must lease and boot one spelling.
T="t21a: a lowercase UDID boots under uppercase leases that stay live"
sim sess-A boot aaaa-1111 >/dev/null 2>&1; rc=$?
s1="$(simstate ios-simulator:host)"; s2="$(simstate ios-simulator:udid-AAAA-1111)"
if [ "${rc}" -eq 0 ] && [ "${s1}" = live ] && [ "${s2}" = live ] && \
   ! ls "${H18}/leases" | grep -q "udid-aaaa-1111" && \
   grep -q "boot AAAA-1111" "${XCRUN_STUB_LOG}"; then ok
else bad "boot rc=${rc}, host ${s1:-none}, uppercase udid lease ${s2:-none}, lowercase dir: $(ls "${H18}/leases" | tr '\n' ' ')"; fi

T="t21b: the one-simulator cap holds against a lowercase boot: a second session is refused (3)"
sim sess-B boot bbbb-2222 >/dev/null 2>&1; rc=$?
if [ "${rc}" -eq 3 ] && ! grep -q "boot BBBB-2222" "${XCRUN_STUB_LOG}"; then ok
else bad "rc=${rc}; xcrun was asked: $(tr '\n' ';' < "${XCRUN_STUB_LOG}")"; fi

T="t21c: shutdown by the lowercase spelling releases both leases"
sim sess-A shutdown aaaa-1111 >/dev/null 2>&1; rc=$?
if [ "${rc}" -eq 0 ] && [ ! -d "${H18}/leases/ios-simulator:host.lock" ] && \
   [ ! -d "${H18}/leases/ios-simulator:udid-AAAA-1111.lock" ]; then ok
else bad "rc=${rc}; leases left: $(ls "${H18}/leases" | tr '\n' ' ')"; fi

# --- T22: a simulator whose state xcrun cannot report is HELD (issue #77 §2,
#          K1 and K3): another session's boot exits 4, and gc keeps the leases.
T="t22a: a sim whose state xcrun cannot report is held: another session's boot exits 4"
sim sess-A boot AAAA-1111 >/dev/null 2>&1; rc=$?
export XCRUN_STUB_LIST_FAIL=1
sim sess-B boot BBBB-2222 >/dev/null 2>&1; rc2=$?
if [ "${rc}" -eq 0 ] && [ "${rc2}" -eq 4 ] && ! grep -q "boot BBBB-2222" "${XCRUN_STUB_LOG}"; then ok
else bad "first boot rc=${rc}, second rc=${rc2} (want 4); xcrun: $(tr '\n' ';' < "${XCRUN_STUB_LOG}")"; fi

T="t22b: gc keeps leases it cannot read: both survive, reported unknown"
DB_HOME="${H18}" PATH="${SIMSTUB}:${PATH}" "${BIN}/device-broker" gc >/dev/null 2>&1
s1="$(simstate ios-simulator:host)"; s2="$(simstate ios-simulator:udid-AAAA-1111)"
if [ -d "${H18}/leases/ios-simulator:host.lock" ] && [ -d "${H18}/leases/ios-simulator:udid-AAAA-1111.lock" ] && \
   [ "${s1}" = unknown ] && [ "${s2}" = unknown ]; then ok
else bad "after gc: host ${s1:-gone}, udid ${s2:-gone}; leases: $(ls "${H18}/leases" | tr '\n' ' ')"; fi
unset XCRUN_STUB_LIST_FAIL
sim sess-A shutdown AAAA-1111 >/dev/null 2>&1

# --- T23: (Booting) counts as booted (issue #77 §2, K7).
T="t23: a simulator still (Booting) counts as booted: its leases stay live"
export XCRUN_STUB_STATE=Booting
sim sess-A boot DDDD-4444 >/dev/null 2>&1; rc=$?
s1="$(simstate ios-simulator:host)"; s2="$(simstate ios-simulator:udid-DDDD-4444)"
unset XCRUN_STUB_STATE
if [ "${rc}" -eq 0 ] && [ "${s1}" = live ] && [ "${s2}" = live ]; then ok
else bad "boot rc=${rc}, host ${s1:-none}, udid lease ${s2:-none}"; fi
sim sess-A shutdown DDDD-4444 >/dev/null 2>&1

# --- T24: stale reclaim happens under a lock (issue #77, first review): two
#          acquirers must not each remove what the other just claimed.
T="t24a: a stale lease whose reclaim lock is held is left alone (4), not reclaimed"
H24="$(newhome)"
DB_HOME="${H24}" "${BIN}/device-broker" acquire android-emulator:port-6060 \
  --owner-key sess-DEAD --owner-pid 4194303 >/dev/null 2>&1
mkdir "${H24}/leases/android-emulator:port-6060.lock.reclaim"
DB_HOME="${H24}" "${BIN}/device-broker" acquire android-emulator:port-6060 \
  --owner-key sess-B >/dev/null 2>&1; rc=$?
own="$(sed -n 's/.*"ownerKey": *"\([^"]*\)".*/\1/p' "${H24}/leases/android-emulator:port-6060.lock/lease.json" 2>/dev/null | head -1)"
if [ "${rc}" -eq 4 ] && [ "${own}" = sess-DEAD ]; then ok
else bad "rc=${rc} (want 4), owner now ${own:-none}"; fi

T="t24b: a reclaim lock older than the grace window is a reclaim that died: broken, lease reclaimed"
for f in "${H24}/leases/android-emulator:port-6060.lock.reclaim"; do
  touch -d "2 minutes ago" "${f}" 2>/dev/null \
    || touch -t "$(date -v-2M '+%Y%m%d%H%M.%S' 2>/dev/null)" "${f}" 2>/dev/null
done
DB_HOME="${H24}" "${BIN}/device-broker" acquire android-emulator:port-6060 \
  --owner-key sess-B >/dev/null 2>&1; rc=$?
own="$(sed -n 's/.*"ownerKey": *"\([^"]*\)".*/\1/p' "${H24}/leases/android-emulator:port-6060.lock/lease.json" 2>/dev/null | head -1)"
if [ "${rc}" -eq 0 ] && [ "${own}" = sess-B ] && \
   [ ! -d "${H24}/leases/android-emulator:port-6060.lock.reclaim" ]; then ok
else bad "rc=${rc}, owner ${own:-none}, reclaim lock left: $(ls "${H24}/leases" | tr '\n' ' ')"; fi

# --- T25: no owner key anywhere: the first acquire refuses (issue #77, first
#          review), as simctl-run boot already does — not a key no later call
#          can match.
T="t25: acquire with no owner key anywhere refuses (4) and leases nothing"
H25="$(newhome)"
env -u DB_OWNER_KEY -u DB_SESSION -u OWNER_KEY DB_HOME="${H25}" \
  "${BIN}/device-broker" acquire android-emulator:port-6070 >/dev/null 2>&1; rc=$?
if [ "${rc}" -eq 4 ] && [ ! -d "${H25}/leases/android-emulator:port-6070.lock" ]; then ok
else bad "rc=${rc} (want 4); leases: $(ls "${H25}/leases" 2>/dev/null | tr '\n' ' ')"; fi

# --- T26: no owner key in the environment: release and check must refuse, not
#          fail open (PR #93 review #2). owner_key dies inside $(...) only exits
#          the subshell, so the old comparison became "" != "" / "" = "".
T="t26a: release with no owner key refuses an unreadable lease (4), lease kept"
H26="$(newhome)"
L26A="${H26}/leases/android-emulator:port-6090.lock"
mkdir -p "${L26A}"; : > "${L26A}/lease.json"
env -u DB_OWNER_KEY -u DB_SESSION -u OWNER_KEY DB_HOME="${H26}" \
  "${BIN}/device-broker" release android-emulator:port-6090 >/dev/null 2>&1; rc=$?
if [ "${rc}" -eq 4 ] && [ -d "${L26A}" ] && [ -f "${L26A}/lease.json" ]; then ok
else bad "rc=${rc} (want 4); lease $([ -d "${L26A}" ] && echo kept || echo REMOVED)"; fi

T="t26b: check --require-mine with no owner key refuses a live lease it cannot claim, lease kept"
L26B="${H26}/leases/android-emulator:port-6092.lock"
mkdir -p "${L26B}"
printf '{"schemaVersion": 1, "resource": "android-emulator:port-6092", "owner": {"pid": %s, "pidStart": ""}, "acquiredAt": 1, "meta": {}}\n' "$$" > "${L26B}/lease.json"
env -u DB_OWNER_KEY -u DB_SESSION -u OWNER_KEY DB_HOME="${H26}" \
  "${BIN}/device-broker" check android-emulator:port-6092 --require-mine >/dev/null 2>&1; rc=$?
if [ "${rc}" -ne 0 ] && [ -f "${L26B}/lease.json" ]; then ok
else bad "rc=${rc} (want nonzero refusal); lease $([ -f "${L26B}/lease.json" ] && echo kept || echo REMOVED)"; fi

# --- T27: the reclaim race (PR #93 review #3). A slow xcrun stub on the loser's
#          PATH makes its stale judgment end ~3 s late; meanwhile the winner
#          reclaims and writes a LIVE lease. The loser must re-check under the
#          lock and leave the winner's lease alone (acquire exits 3; gc keeps it).
R27="$(mktemp -d "${TESTROOT}/race.XXXXXX")"
mkdir -p "${R27}/fast" "${R27}/slow"
printf '#!/usr/bin/env bash\necho "== Devices =="\n' > "${R27}/fast/xcrun"
printf '#!/usr/bin/env bash\nsleep 3\necho "== Devices =="\n' > "${R27}/slow/xcrun"
chmod +x "${R27}/fast/xcrun" "${R27}/slow/xcrun"
RES27="ios-simulator:udid-EEEE-5555"

T="t27a: two acquirers of one stale lease: only one wins, the winner's lease survives"
H27="$(newhome)"; mkdir -p "${H27}/leases"
D27="${H27}/leases/${RES27}.lock"
mkdir "${D27}"
cat > "${D27}/lease.json" <<EOF
{"schemaVersion": 1, "resource": "${RES27}", "ownerKey": "sess-DEAD",
 "owner": {"pid": 4194303, "pidStart": "", "host": "x", "worktree": "/", "session": "", "command": "x"},
 "acquiredAt": 1, "whileBooted": "EEEE-5555", "meta": {}}
EOF
sleep 30 & A27PID=$!
( DB_HOME="${H27}" PATH="${R27}/slow:${PATH}" "${BIN}/device-broker" acquire "${RES27}" \
    --owner-key sess-B --while-booted EEEE-5555 > "${R27}/b.out" 2> "${R27}/b.err"; echo $? > "${R27}/b.rc" ) &
B27PID=$!
sleep 1
DB_HOME="${H27}" PATH="${R27}/fast:${PATH}" "${BIN}/device-broker" acquire "${RES27}" \
  --owner-key sess-A --owner-pid "${A27PID}" --while-booted EEEE-5555 > "${R27}/a.out" 2> "${R27}/a.err"; rca27=$?
wait "${B27PID}"; rcb27="$(cat "${R27}/b.rc")"
own27="$(sed -n 's/.*"ownerKey": *"\([^"]*\)".*/\1/p' "${D27}/lease.json" 2>/dev/null | head -1)"
kill "${A27PID}" 2>/dev/null
if [ "${rca27}" -eq 0 ] && [ "${rcb27}" -ne 0 ] && [ "${own27}" = sess-A ]; then ok
else bad "A rc=${rca27}, B rc=${rcb27} (want nonzero), final owner ${own27:-none}; B stderr: $(tr '\n' '|' < "${R27}/b.err")"; fi

T="t27b: gc that judged a stale lease does not remove the live lease another acquirer just wrote"
H27B="$(newhome)"; mkdir -p "${H27B}/leases"
D27B="${H27B}/leases/${RES27}.lock"
mkdir "${D27B}"
cat > "${D27B}/lease.json" <<EOF
{"schemaVersion": 1, "resource": "${RES27}", "ownerKey": "sess-DEAD",
 "owner": {"pid": 4194303, "pidStart": "", "host": "x", "worktree": "/", "session": "", "command": "x"},
 "acquiredAt": 1, "whileBooted": "EEEE-5555", "meta": {}}
EOF
sleep 30 & A27BPID=$!
( DB_HOME="${H27B}" PATH="${R27}/slow:${PATH}" "${BIN}/device-broker" gc > "${R27}/gc.out" 2> "${R27}/gc.err" ) &
G27PID=$!
sleep 1
DB_HOME="${H27B}" PATH="${R27}/fast:${PATH}" "${BIN}/device-broker" acquire "${RES27}" \
  --owner-key sess-A --owner-pid "${A27BPID}" --while-booted EEEE-5555 > "${R27}/a2.out" 2>&1; rca27b=$?
wait "${G27PID}"
own27b="$(sed -n 's/.*"ownerKey": *"\([^"]*\)".*/\1/p' "${D27B}/lease.json" 2>/dev/null | head -1)"
kill "${A27BPID}" 2>/dev/null
# The guarantee: gc must never remove a lease whose owner is alive. Either A was
# refused (gc held the reclaim lock while judging, so A could not write — gc then
# cleared only the stale lease), or A wrote a live lease and it survives gc's
# inside-lock re-check. The bug (head): A rc=0 yet gc removed A's live lease.
if [ "${rca27b}" -ne 0 ] || [ "${own27b}" = sess-A ]; then ok
else bad "A rc=${rca27b} but lease after gc: ${own27b:-GONE} (gc removed a live lease); gc said: $(tr '\n' '|' < "${R27}/gc.err")"; fi

say ""
say "== ${PASS} passed, ${FAIL} failed =="
[ "${FAIL}" -eq 0 ]
