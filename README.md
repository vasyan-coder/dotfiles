# dotfiles

Personal Ghostty and tmux configuration for macOS.

## Requirements

- [Ghostty](https://ghostty.org/)
- [tmux](https://github.com/tmux/tmux)
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
```

Restart Ghostty and reload tmux after installation.
