# dotfiles

Personal AeroSpace, Ghostty, tmux, and zsh configuration for macOS.

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

Link the configurations:

```sh
mkdir -p "$HOME/Library/Application Support/com.mitchellh.ghostty"
ln -sfn "$HOME/.dotfiles/ghostty/config" "$HOME/Library/Application Support/com.mitchellh.ghostty/config.ghostty"
ln -sfn "$HOME/.dotfiles/tmux/tmux.conf" "$HOME/.tmux.conf"
ln -sfn "$HOME/.dotfiles/aerospace/aerospace.toml" "$HOME/.aerospace.toml"
ln -sfn "$HOME/.dotfiles/zsh/zshrc" "$HOME/.zshrc"
```

Restart Ghostty, reload tmux, and run `aerospace reload-config` after installation.

## Keyboard layout

Option is reserved for the terminal: Option+←/→ and Option+Shift+←/→ stay with
macOS word navigation/selection, so AeroSpace does not bind them.

| Keys | Action |
| --- | --- |
| `Cmd+←/→` | previous/next tmux session |
| `Cmd+Shift+←/→` | previous/next tmux window |
| `Cmd+1..9` | go to tmux window by number |
| `Cmd+T` / `Cmd+W` | new tmux window / close pane |
| `Cmd+D` / `Cmd+Shift+D` | split pane vertically / horizontally |
| `Option+H/J/K/L` | focus window in AeroSpace |
| `Option+Ctrl+←/→` | move workspace to another monitor |
