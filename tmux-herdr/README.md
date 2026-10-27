# tmux with a Herdr-style sidebar

Separate snapshot of the custom tmux configuration as used on 2026-10-27.
The repository's standard `./install.sh tmux` continues to install `tmux/tmux.conf`.

The left pane contains sessions and windows above a list of coding agents.
Clicking a window or agent opens its working pane. Each list scrolls independently;
the agent list scrolls by complete cards. The bottom tmux status line is disabled.

Agent states are inferred from processes inside tmux panes and the current visible
CLI interface: working, waiting for input, completed in the background, idle, or
unknown. Agent transcripts are not read. Status detection is heuristic.

## Files

```text
tmux.conf                      -> ~/.tmux.conf
herdr-sidebar.conf             -> ~/.config/tmux/herdr-sidebar.conf
navigator/sidebar.py           -> ~/.config/tmux/navigator/sidebar.py
navigator/agent_detector.py    -> ~/.config/tmux/navigator/agent_detector.py
tests/test_agent_detector.py   -> development tests
```

These files preserve the installed version exactly. They contain the original
machine's absolute paths: `/Users/vasyan`, `/usr/bin/python3`, and
`/opt/homebrew/bin/tmux`. Before using the snapshot elsewhere, adapt the home
directory in both `.conf` files, the Python executable in `herdr-sidebar.conf`,
and the tmux executable in `navigator/sidebar.py`. The latter two paths can be
checked with `command -v python3` and `command -v tmux`.

Requires tmux and Python 3 with curses; no third-party Python packages are needed.
The snapshot was tested with tmux 3.8 and the macOS system Python 3.9.6.
Back up the destination files before copying the snapshot into place.

## Controls

- Prefix: `Ctrl+A`.
- Reload: prefix, then `r`.
- Focus the sidebar or return to the working pane: prefix, then `b`.
- Show or hide the sidebar: prefix, then `Shift+B`.
- Sidebar: wheel, `j`/`k`, Enter; Tab chooses a section.
- Page Up/Down and Home/End scroll the chosen section.

Ghostty's Cmd shortcuts are configured separately in `ghostty/config`.

## Validation

From the repository root:

```sh
PYTHONPATH=tmux-herdr/navigator python3 -m unittest discover -s tmux-herdr/tests
```

The implementation was also checked in isolated tmux sessions with real terminal
mouse events: 16 agent entries, repeated wheel events, independent list scrolling,
click navigation, configuration reloads, and closing the last working pane.

Each window has a persistent sidebar process. Hidden sidebars sleep and share one
status snapshot with visible sidebars. Wheel events go directly to the persistent
UI, avoiding per-event Python processes. Temporary state stores pane metadata and
click maps; obsolete maps for closed panes and known stopped servers are cleaned up.
