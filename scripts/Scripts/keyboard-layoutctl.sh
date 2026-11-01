#!/usr/bin/env bash
# Switches between the US, UK and French layouts, and moves every app's Vim keys with it:
# hjkl on QWERTY, jklm on AZERTY so they stay under the right hand.
# Hyprland, Neovim and zsh read the layout themselves; tmux, kitty, less and yazi get
# small generated files in ~/.local/state/hyprpunk/keyboard.
#   keyboard-layoutctl.sh get | list
#   keyboard-layoutctl.sh set <fr|us|gb> | toggle   from the shell
#   keyboard-layoutctl.sh init [fr|us|gb]           from install.sh, through sudo
#   keyboard-layoutctl.sh ensure                 rewrites the generated files only

set -euo pipefail

STATE_HOME="${XDG_STATE_HOME:-$HOME/.local/state}"
STATE_DIR="$STATE_HOME/hyprpunk"
STATE_FILE="$STATE_DIR/keyboard-layout"
GENERATED_DIR="${HYPRPUNK_KEYBOARD_RUNTIME_DIR:-$HOME/.local/state/hyprpunk/keyboard}"
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"
DOTFILES_DIR="$(cd "$(dirname "$SCRIPT_PATH")/../.." && pwd)"

usage() {
  echo "Usage: $0 {get|list|set <fr|us|gb>|toggle|init [fr|us|gb]|ensure}"
}

get_layout() {
  local layout="us"
  if [[ -r "$STATE_FILE" ]]; then
    IFS= read -r layout <"$STATE_FILE" || true
  fi
  case "$layout" in
    fr|us|gb) printf '%s\n' "$layout" ;;
    *) printf 'us\n' ;;
  esac
}

# Writes stdin to a file in one go, without the heredoc's indentation
write_file() {
  local target="$1"
  local temporary="$target.tmp.$$"
  umask 077
  sed 's/^[[:space:]]*//' >"$temporary"
  mv -f "$temporary" "$target"
}

# Yazi's config is a folder: link the shared files, and the AZERTY keymap when needed
generate_common() {
  local layout="$1"
  mkdir -p "$GENERATED_DIR/yazi"

  ln -sfn "$CONFIG_HOME/yazi/package.toml" "$GENERATED_DIR/yazi/package.toml"
  ln -sfn "$CONFIG_HOME/yazi/theme.toml" "$GENERATED_DIR/yazi/theme.toml"
  ln -sfn "$CONFIG_HOME/yazi/themes" "$GENERATED_DIR/yazi/themes"

  if [[ "$layout" == "fr" ]]; then
    ln -sfn "$DOTFILES_DIR/keyboard/yazi/fr.toml" "$GENERATED_DIR/yazi/keymap.toml"
  else
    unlink "$GENERATED_DIR/yazi/keymap.toml" 2>/dev/null || true
  fi
}

# AZERTY: tmux's copy mode, pane keys and session picker move over, kitty sends Ctrl+M as F12
# (terminals see it as Enter otherwise), and less scrolls with k and l
generate_fr() {
  write_file "$GENERATED_DIR/tmux.conf" <<'EOF'
    unbind-key -q -n C-h
    unbind-key -q -n C-j
    unbind-key -q -n C-k
    unbind-key -q -n C-l
    unbind-key -q -n F12
    unbind-key -T copy-mode-vi h
    unbind-key -T copy-mode-vi j
    unbind-key -T copy-mode-vi k
    unbind-key -T copy-mode-vi l
    unbind-key -T copy-mode-vi m
    bind-key -T copy-mode-vi j send -X cursor-left
    bind-key -T copy-mode-vi k send -X cursor-down
    bind-key -T copy-mode-vi l send -X cursor-up
    bind-key -T copy-mode-vi m send -X cursor-right
    set -g @vim_navigator_mapping_left "C-j"
    set -g @vim_navigator_mapping_down "C-k"
    set -g @vim_navigator_mapping_up "C-l"
    set -g @vim_navigator_mapping_right "F12"
    set -g @sessionx-bind-scroll-down "alt-k"
    set -g @sessionx-bind-scroll-up "alt-l"
EOF
  write_file "$GENERATED_DIR/kitty.conf" <<'EOF'
    map ctrl+m send_key f12
EOF
  write_file "$GENERATED_DIR/lesskey" <<'EOF'
    k forw-line
    l back-line
EOF
}

# QWERTY: the usual keys, nothing for kitty or less
generate_us() {
  write_file "$GENERATED_DIR/tmux.conf" <<'EOF'
    unbind-key -q -n C-h
    unbind-key -q -n C-j
    unbind-key -q -n C-k
    unbind-key -q -n C-l
    unbind-key -q -n F12
    unbind-key -T copy-mode-vi h
    unbind-key -T copy-mode-vi j
    unbind-key -T copy-mode-vi k
    unbind-key -T copy-mode-vi l
    unbind-key -T copy-mode-vi m
    bind-key -T copy-mode-vi h send -X cursor-left
    bind-key -T copy-mode-vi j send -X cursor-down
    bind-key -T copy-mode-vi k send -X cursor-up
    bind-key -T copy-mode-vi l send -X cursor-right
    set -g @vim_navigator_mapping_left "C-h"
    set -g @vim_navigator_mapping_down "C-j"
    set -g @vim_navigator_mapping_up "C-k"
    set -g @vim_navigator_mapping_right "C-l"
    set -g @sessionx-bind-scroll-down "alt-j"
    set -g @sessionx-bind-scroll-up "alt-k"
EOF
  : >"$GENERATED_DIR/kitty.conf"
  : >"$GENERATED_DIR/lesskey"
}

# Let whatever is running pick up the change right away
reload_apps() {
  if [[ -n "${HYPRLAND_INSTANCE_SIGNATURE:-}" ]] && command -v hyprctl >/dev/null 2>&1; then
    if ! timeout 2s hyprctl reload >/dev/null 2>&1; then
      echo "Warning: Hyprland did not reload in time." >&2
    fi
  fi
  if command -v pgrep >/dev/null 2>&1 && pgrep -x kitty >/dev/null 2>&1; then
    pkill -USR1 -x kitty >/dev/null 2>&1 || true
  fi
  if command -v tmux >/dev/null 2>&1 && timeout 2s tmux info >/dev/null 2>&1; then
    timeout 2s tmux source-file "$CONFIG_HOME/tmux/tmux.conf" >/dev/null 2>&1 || true
  fi
}

# The same layout for the login screen and the TTYs, keeping the keyboard's model and
# options. No password thanks to the polkit rule in keyboard/polkit, or through sudo
# when the installer asks ($2 = sudo). Failures stop init; interactive callers keep
# their saved desktop choice and warn instead.
apply_system_layout() {
  local layout="$1" prefix=() conversion=() status model options variant="" failed=0
  [[ "${2:-}" == sudo ]] && prefix=(sudo)
  if ! command -v localectl >/dev/null 2>&1 || ! status=$(LC_ALL=C localectl status 2>/dev/null); then
    echo "Warning: cannot read the system keymap; the login screen and TTY keymap was not changed." >&2
    return 1
  fi
  model=$(sed -n 's/^ *X11 Model: //p' <<<"$status")
  options=$(sed -n 's/^ *X11 Options: //p' <<<"$status")
  # Keep a custom system XKB variant when reselecting its layout. Variants belong
  # to a specific layout, so do not carry them across a switch to another one.
  if [[ "$(sed -n 's/^ *X11 Layout: //p' <<<"$status")" == "$layout" ]]; then
    variant=$(sed -n 's/^ *X11 Variant: //p' <<<"$status")
  fi
  # XKB calls the UK layout gb; kbd calls it uk. Set both explicitly, without
  # the console-to-X11 conversion replacing the chosen XKB model or options.
  [[ "$layout" == gb ]] && conversion=(--no-convert)
  if ! "${prefix[@]}" localectl "${conversion[@]}" set-x11-keymap "$layout" "${model:-pc105}" "$variant" "$options"; then
    echo "Warning: the login screen and TTY keymap was not changed." >&2
    failed=1
  fi
  if [[ "$layout" == gb ]] && ! "${prefix[@]}" localectl --no-convert set-keymap uk; then
    echo "Warning: the UK console keymap was not changed." >&2
    failed=1
  fi
  return "$failed"
}

apply_layout() {
  local layout="$1"
  case "$layout" in
    fr|us|gb) ;;
    *) echo "Unsupported keyboard layout: $layout" >&2; exit 2 ;;
  esac

  mkdir -p "$STATE_DIR" "$GENERATED_DIR"
  generate_common "$layout"
  if [[ "$layout" == fr ]]; then
    generate_fr
  else
    generate_us
  fi
  printf '%s\n' "$layout" >"$STATE_FILE.tmp.$$"
  mv -f "$STATE_FILE.tmp.$$" "$STATE_FILE"
  reload_apps
  printf 'Keyboard layout: %s (%s navigation)\n' "${layout^^}" "$([[ "$layout" == fr ]] && printf jklm || printf hjkl)"
}

case "${1:-}" in
  get) get_layout ;;
  list) printf 'us\nfr\ngb\n' ;;
  set)
    [[ $# -eq 2 ]] || { usage >&2; exit 2; }
    apply_layout "$2"
    apply_system_layout "$2" || true
    ;;
  toggle)
    case "$(get_layout)" in
      us) apply_layout fr ;;
      fr) apply_layout gb ;;
      gb) apply_layout us ;;
    esac
    apply_system_layout "$(get_layout)" || true
    ;;
  init)
    apply_layout "${2:-$(get_layout)}"
    apply_system_layout "$(get_layout)" sudo
    ;;
  ensure) apply_layout "$(get_layout)" ;;
  *) usage >&2; exit 2 ;;
esac
