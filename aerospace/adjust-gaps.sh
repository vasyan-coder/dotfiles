#!/bin/zsh

emulate -L zsh
setopt ERR_EXIT NO_UNSET PIPE_FAIL

readonly program_name="${0:t}"
readonly step="${AEROSPACE_GAP_STEP:-4}"
readonly minimum="${AEROSPACE_GAP_MIN:-0}"
readonly maximum="${AEROSPACE_GAP_MAX:-128}"

usage() {
  print -u2 "Usage: $program_name increase|decrease"
}

if (( $# != 1 )); then
  usage
  exit 2
fi

readonly action="$1"
if [[ "$action" != increase && "$action" != decrease ]]; then
  usage
  exit 2
fi

for value in "$step" "$minimum" "$maximum"; do
  if [[ ! "$value" =~ '^[0-9]+$' ]]; then
    print -u2 "Gap settings must be non-negative integers"
    exit 2
  fi
done

if (( step == 0 || minimum > maximum )); then
  print -u2 "Invalid gap range or step"
  exit 2
fi

if ! command -v aerospace >/dev/null 2>&1; then
  print -u2 "aerospace CLI was not found"
  exit 1
fi

config_path="$(aerospace config --config-path)"
if [[ -z "$config_path" || ! -f "$config_path" ]]; then
  print -u2 "Active AeroSpace config was not found"
  exit 1
fi

readonly config_path
readonly expected_config="$HOME/.aerospace.toml"
if [[ "$config_path" != "$expected_config" ]]; then
  print -u2 "Refusing to edit unexpected config path: $config_path"
  print -u2 "Run the dotfiles installer to deploy $expected_config"
  exit 1
fi
if [[ -L "$config_path" ]]; then
  print -u2 "Refusing to edit a symlinked AeroSpace config"
  print -u2 "Run the dotfiles installer to deploy a local config copy"
  exit 1
fi

readonly config_dir="${config_path:h}"
work_dir=''
transaction_active=false

cleanup() {
  local exit_code=$?
  trap - EXIT
  trap '' HUP INT TERM

  if [[ "$transaction_active" == true && -f "$work_dir/previous.toml" ]]; then
    if mv "$work_dir/previous.toml" "$config_path"; then
      transaction_active=false
      if ! aerospace reload-config --no-gui >/dev/null 2>&1; then
        print -u2 "Previous config was restored on disk, but AeroSpace could not reload it"
      fi
    else
      print -u2 "Automatic rollback failed; backup retained at:"
      print -u2 "$work_dir/previous.toml"
      (( exit_code == 0 )) && exit_code=1
      exit "$exit_code"
    fi
  fi

  if [[ -n "$work_dir" ]]; then
    rm -f "$work_dir/next.toml" "$work_dir/previous.toml"
    rmdir "$work_dir" 2>/dev/null || true
  fi

  exit "$exit_code"
}
trap cleanup EXIT
trap 'exit 130' HUP INT TERM

# exec-and-forget starts one process per key repeat. Keep one file descriptor
# locked for the whole transaction so rapid presses are applied in order.
readonly lock_path="${TMPDIR:-/tmp}/aerospace-adjust-gaps-${UID}.lock"
exec 9>"$lock_path"
if ! /usr/bin/lockf -s -t 5 9; then
  print -u2 "Timed out waiting for another gap adjustment"
  exit 1
fi

work_dir="$(mktemp -d "$config_dir/.aerospace-gaps.XXXXXX")"
readonly work_dir
readonly next_config="$work_dir/next.toml"
readonly previous_config="$work_dir/previous.toml"

cp -p "$config_path" "$next_config"
awk \
  -v action="$action" \
  -v step="$step" \
  -v minimum="$minimum" \
  -v maximum="$maximum" '
  /^[[:space:]]*outer\.(left|right|top|bottom)[[:space:]]*=[[:space:]]*[0-9]+[[:space:]]*(#.*)?$/ {
    value = $0
    sub(/^[^=]*=[[:space:]]*/, "", value)
    sub(/[[:space:]]*#.*/, "", value)
    sub(/[[:space:]]*$/, "", value)

    next_value = action == "increase" ? value + step : value - step
    if (next_value < minimum) next_value = minimum
    if (next_value > maximum) next_value = maximum

    prefix = $0
    sub(/[0-9]+[[:space:]]*(#.*)?$/, "", prefix)
    suffix = $0
    sub(/^[^=]*=[[:space:]]*[0-9]+/, "", suffix)

    print prefix next_value suffix
    changed++
    next
  }

  { print }

  END {
    if (changed != 4) {
      print "Expected four scalar gaps.outer values; config was left unchanged" > "/dev/stderr"
      exit 1
    }
  }
' "$config_path" > "$next_config"

if cmp -s "$config_path" "$next_config"; then
  exit 0
fi

cp -p "$config_path" "$previous_config"
transaction_active=true
if ! mv "$next_config" "$config_path"; then
  print -u2 "Could not replace the active AeroSpace config"
  exit 1
fi

if ! aerospace reload-config --dry-run --no-gui; then
  print -u2 "Updated AeroSpace config is invalid; rolling back"
  exit 1
fi

if ! aerospace reload-config --no-gui; then
  print -u2 "AeroSpace reload failed; rolling back"
  exit 1
fi

transaction_active=false
