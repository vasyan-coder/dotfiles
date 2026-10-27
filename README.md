# dotfiles

Personal AeroSpace, Ghostty, tmux, and zsh configuration for macOS.

The optional [Herdr-style tmux sidebar](tmux-herdr/) is saved as a separate
configuration snapshot. The standard tmux configuration remains in `tmux/` and
is installed by `./install.sh tmux`.

## Requirements

- [AeroSpace](https://github.com/nikitabobko/AeroSpace)
- [Ghostty](https://ghostty.org/)
- [tmux](https://github.com/tmux/tmux)
- [oh-my-zsh](https://ohmyz.sh/) with [Powerlevel10k](https://github.com/romkatv/powerlevel10k)
- [JetBrainsMono Nerd Font](https://www.nerdfonts.com/)

## Install

Clone the repository:

```sh
git clone git@github.com:vasyan-coder/dotfiles.git ~/.dotfiles
```

Preview the installation, then apply it:

```sh
cd ~/.dotfiles
./install.sh --dry-run
./install.sh
```

The installer can be run from any working directory and accepts component names,
for example `~/.dotfiles/install.sh aerospace zsh`. Existing files and symlinks
are moved to `$XDG_STATE_HOME/dotfiles/backups/` when it is set, or to
`~/.local/state/dotfiles/backups/` otherwise. Set `DOTFILES_BACKUP_DIR` to use
another backup location.

The zsh, tmux, Ghostty, and AeroSpace helper files are linked to the repository.
The AeroSpace config itself is copied to `~/.aerospace.toml`: changing gaps with
the hotkeys therefore stays machine-local and does not dirty the Git working
tree. To restore the versioned defaults, run `./install.sh aerospace` again.

Restart Ghostty, reload tmux, and run `aerospace reload-config` after installation.

## Keyboard layout

Option is the AeroSpace modifier, except Option+←/→ and Option+Shift+←/→:
those stay with macOS word navigation/selection.

| Keys | Action |
| --- | --- |
| `Cmd+←/→` | previous/next tmux session |
| `Cmd+Shift+←/→` | previous/next tmux window |
| `Cmd+1..9` | go to tmux window by number |
| `Cmd+T` / `Cmd+W` | new tmux window / close pane |
| `Cmd+D` / `Cmd+Shift+D` | split pane vertically / horizontally |
| `Option+H/J/K/L` | focus window in AeroSpace |
| `Option+Shift+-` / `Option+Shift+=` | decrease/increase outer screen gaps by 4 px |
| `Option+Ctrl+←/→` | move workspace to another monitor |
