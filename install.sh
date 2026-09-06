#!/bin/bash

set -euo pipefail

if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
  printf 'Do not run this installer with sudo.\n' >&2
  exit 1
fi

readonly REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
readonly STATE_ROOT="${DOTFILES_BACKUP_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/dotfiles/backups}"
readonly BACKUP_ROOT="$STATE_ROOT/$(date '+%Y%m%d-%H%M%S')-$$"

dry_run=false
selected=()
backup_used=false
backup_root_created=false
last_backup=''

usage() {
  cat <<'EOF'
Usage: ./install.sh [--dry-run] [component ...]

Install dotfiles from this repository into their standard locations.
With no components, everything is installed.

Components:
  aerospace  Copy the config and link the gap helper
  ghostty    Link the Ghostty config
  tmux       Link the tmux config
  zsh        Link the zsh config

Options:
  -n, --dry-run  Show planned changes without writing anything
  -h, --help     Show this help
EOF
}

for argument in "$@"; do
  case "$argument" in
    -n|--dry-run)
      dry_run=true
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    aerospace|ghostty|tmux|zsh)
      selected+=("$argument")
      ;;
    *)
      printf 'Unknown option or component: %s\n\n' "$argument" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if (( ${#selected[@]} == 0 )); then
  selected=(aerospace ghostty tmux zsh)
fi

is_selected() {
  local wanted="$1"
  local component
  for component in "${selected[@]}"; do
    [[ "$component" == "$wanted" ]] && return 0
  done
  return 1
}

require_source() {
  local source="$1"
  if [[ ! -f "$source" ]]; then
    printf 'Missing source file: %s\n' "$source" >&2
    exit 1
  fi
}

require_executable() {
  local source="$1"
  require_source "$source"
  if [[ ! -x "$source" ]]; then
    printf 'Source file is not executable: %s\n' "$source" >&2
    exit 1
  fi
}

# Validate every selected source before making the first change.
if is_selected aerospace; then
  require_source "$REPO_ROOT/aerospace/aerospace.toml"
  require_executable "$REPO_ROOT/aerospace/adjust-gaps.sh"
fi
is_selected ghostty && require_source "$REPO_ROOT/ghostty/config"
is_selected tmux && require_source "$REPO_ROOT/tmux/tmux.conf"
is_selected zsh && require_source "$REPO_ROOT/zsh/zshrc"

prepare_backup_root() {
  if [[ "$backup_root_created" == true ]]; then
    return
  fi

  if ! mkdir -p "$STATE_ROOT"; then
    printf 'Could not prepare backup parent: %s\n' "$STATE_ROOT" >&2
    return 1
  fi
  if ! mkdir "$BACKUP_ROOT"; then
    printf 'Could not create unique backup directory: %s\n' "$BACKUP_ROOT" >&2
    return 1
  fi
  backup_root_created=true
}

backup_destination() {
  local destination="$1"
  local relative_path="${destination#"$HOME"/}"
  last_backup="$BACKUP_ROOT/$relative_path"

  printf 'BACKUP %s -> %s\n' "$destination" "$last_backup"
  if [[ "$dry_run" == false ]]; then
    if ! prepare_backup_root; then
      return 1
    fi
    if [[ -e "$last_backup" || -L "$last_backup" ]]; then
      printf 'Backup destination already exists: %s\n' "$last_backup" >&2
      return 1
    fi
    if ! mkdir -p "$(dirname "$last_backup")"; then
      printf 'Could not prepare backup path: %s\n' "$last_backup" >&2
      return 1
    fi
    if ! mv "$destination" "$last_backup"; then
      printf 'Could not back up: %s\n' "$destination" >&2
      return 1
    fi
  fi
  backup_used=true
}

ensure_parent() {
  local destination="$1"
  if [[ "$dry_run" == false ]]; then
    mkdir -p "$(dirname "$destination")"
  fi
}

install_link() {
  local source="$1"
  local destination="$2"

  if [[ -L "$destination" && "$destination" -ef "$source" ]]; then
    printf 'SKIP   %s (already linked)\n' "$destination"
    return
  fi

  ensure_parent "$destination"
  last_backup=''
  if [[ -e "$destination" || -L "$destination" ]]; then
    backup_destination "$destination"
  fi

  printf 'LINK   %s -> %s\n' "$destination" "$source"
  if [[ "$dry_run" == false ]]; then
    if ! ln -s "$source" "$destination"; then
      if [[ -n "$last_backup" && ( -e "$last_backup" || -L "$last_backup" ) ]]; then
        mv "$last_backup" "$destination"
      fi
      return 1
    fi
  fi
}

install_copy() {
  local source="$1"
  local destination="$2"
  local destination_dir
  local staged_copy=''

  if [[ -f "$destination" && ! -L "$destination" ]] && cmp -s "$source" "$destination"; then
    printf 'SKIP   %s (already up to date)\n' "$destination"
    return
  fi

  if [[ "$dry_run" == false ]]; then
    ensure_parent "$destination"
    destination_dir="$(dirname "$destination")"
    staged_copy="$(mktemp "$destination_dir/.dotfiles-install.XXXXXX")"
    if ! cp -p "$source" "$staged_copy"; then
      rm -f "$staged_copy"
      printf 'Could not stage config: %s\n' "$source" >&2
      return 1
    fi
  fi

  last_backup=''
  if [[ -e "$destination" || -L "$destination" ]]; then
    if ! backup_destination "$destination"; then
      [[ -z "$staged_copy" ]] || rm -f "$staged_copy"
      return 1
    fi
  fi

  printf 'COPY   %s -> %s\n' "$source" "$destination"
  if [[ "$dry_run" == false ]]; then
    if ! mv "$staged_copy" "$destination"; then
      rm -f "$staged_copy"
      if [[ -n "$last_backup" && ( -e "$last_backup" || -L "$last_backup" ) ]]; then
        mv "$last_backup" "$destination"
      fi
      return 1
    fi
  fi
}

if is_selected aerospace; then
  install_link "$REPO_ROOT/aerospace/adjust-gaps.sh" "$HOME/.local/bin/aerospace-adjust-gaps"
  # This one is deliberately a copy: hotkey-driven gap changes remain local
  # and never make the Git working tree dirty.
  install_copy "$REPO_ROOT/aerospace/aerospace.toml" "$HOME/.aerospace.toml"
fi

if is_selected ghostty; then
  install_link "$REPO_ROOT/ghostty/config" "$HOME/Library/Application Support/com.mitchellh.ghostty/config.ghostty"
fi

if is_selected tmux; then
  install_link "$REPO_ROOT/tmux/tmux.conf" "$HOME/.tmux.conf"
fi

if is_selected zsh; then
  install_link "$REPO_ROOT/zsh/zshrc" "$HOME/.zshrc"
fi

if [[ "$backup_used" == true ]]; then
  if [[ "$dry_run" == true ]]; then
    printf 'Planned backup directory: %s\n' "$BACKUP_ROOT"
  else
    printf 'Backups: %s\n' "$BACKUP_ROOT"
  fi
fi
