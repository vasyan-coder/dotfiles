#!/usr/bin/python3
"""A persistent tmux navigator. Standard library only; no Herdr dependency."""
import argparse
import curses
import fcntl
import hashlib
import json
import locale
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import time
import unicodedata

from agent_detector import detect_agents

SCRIPT = Path(__file__).resolve()
SOCKET = os.environ.get("TMUX", "").split(",")[0]
TMUX = ["/opt/homebrew/bin/tmux"] + (["-S", SOCKET] if SOCKET else [])
RUNTIME = Path(tempfile.gettempdir()) / ("tmux-navigator-%s" % os.getuid())
RUNTIME.mkdir(mode=0o700, exist_ok=True)
SERVER = hashlib.sha256(
    ",".join(os.environ.get("TMUX", "").split(",")[:2]).encode()
).hexdigest()[:12]
SEP = "\x1f"
FIELDS = "session_id session_name window_id window_index window_name window_active window_width pane_id pane_pid pane_current_command pane_current_path pane_active pane_dead pane_title pane_width pane_height pane_left pane_top @herdr_sidebar".split()


def tmux(args, check=False):
    result = subprocess.run(TMUX + args, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=5)
    if check and result.returncode:
        raise RuntimeError(result.stderr.strip())
    return result.stdout.rstrip("\n")


def panes(window=None):
    args = ["list-panes"] + (["-t", window] if window else ["-a"])
    result = tmux(args + ["-F", SEP.join("#{%s}" % field for field in FIELDS)])
    return [dict(zip(FIELDS, line.split(SEP))) for line in result.splitlines()
            if len(line.split(SEP)) == len(FIELDS)]


def enabled():
    return tmux(["show-options", "-gqv", "@herdr_sidebar_enabled"]) != "off"


def command(*args):
    return shlex.join([sys.executable, str(SCRIPT)] + list(args))


def content_pane(items):
    content = [p for p in items if p.get("@herdr_sidebar") != "1"]
    return next((p for p in content if p["pane_active"] == "1"), content[0] if content else None)


def ensure(window=None, all_windows=False, prune=False):
    with open(RUNTIME / (SERVER + ".lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        items = panes(None if all_windows else window)
        if not all_windows and not window:
            current = tmux(["display-message", "-p", "#{window_id}"])
            items = [p for p in items if p["window_id"] == current]
        windows = {}
        is_enabled = enabled()
        visible = set(tmux(["list-clients", "-F", "#{window_id}"]).splitlines())
        for pane in items:
            windows.setdefault(pane["window_id"], []).append(pane)
        for target, group in windows.items():
            side = [p for p in group if p.get("@herdr_sidebar") == "1"]
            main = content_pane(group)
            if not main or not is_enabled:
                for pane in side:
                    tmux(["kill-pane", "-t", pane["pane_id"]])
                continue
            if prune:
                continue
            total_width = int(main.get("window_width") or 0)
            width = min(34, max(25, total_width // 3))
            if side:
                # Never respawn an existing UI on reload or window selection.
                if int(side[0]["pane_width"]) != width and total_width >= 70:
                    tmux(["resize-pane", "-t", side[0]["pane_id"], "-x", str(width)])
                if target in visible:
                    tmux(["send-keys", "-t", side[0]["pane_id"], "F9"])
                continue
            if total_width < 70:
                continue
            sidebar = tmux(["split-window", "-d", "-h", "-b", "-f", "-l", str(width),
                            "-t", main["pane_id"], "-P", "-F", "#{pane_id}", command("ui")], True)
            tmux(["set-option", "-p", "-t", sidebar, "@herdr_sidebar", "1"])
            tmux(["set-option", "-p", "-t", sidebar, "remain-on-exit", "off"])
            tmux(["select-pane", "-t", sidebar, "-T", "Navigator"])
            tmux(["select-pane", "-t", sidebar, "-P", "bg=#11111b,fg=#cdd6f4"])
            tmux(["select-pane", "-t", main["pane_id"]])


def state_file(pane):
    if not re.fullmatch(r"%\d+", pane):
        raise ValueError("Invalid pane ID")
    return RUNTIME / (SERVER + "-" + pane[1:] + ".json")


def save_state(pane, state):
    path = state_file(pane)
    temporary = path.with_suffix(".%s.tmp" % os.getpid())
    temporary.write_text(json.dumps(state), encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def read_state(pane):
    try:
        return json.loads(state_file(pane).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def navigate(action, client=None):
    if not action:
        return
    # IDs are stable when windows are renamed or renumbered.
    if action.get("pane") and not tmux(["display-message", "-p", "-t", action["pane"], "#{pane_id}"]):
        return
    if client:
        tmux(["switch-client", "-c", client, "-t", action["session"]])
    else:
        tmux(["switch-client", "-t", action["session"]])
    tmux(["select-window", "-t", action["session"] + ":" + action["window"]])
    if action.get("pane"):
        tmux(["select-pane", "-t", action["pane"]])


def click(pane, y, client):
    state = read_state(pane)
    navigate(state.get("hits", {}).get(str(y)), client)


def focus(window=None):
    group = panes(window or tmux(["display-message", "-p", "#{window_id}"]))
    side = next((p for p in group if p.get("@herdr_sidebar") == "1"), None)
    main = content_pane(group)
    if side and main:
        tmux(["select-pane", "-t", main["pane_id"] if side["pane_active"] == "1" else side["pane_id"]])


def clean(text):
    return "".join(c for c in str(text) if not unicodedata.category(c).startswith("C"))


def fit(text, width):
    result, columns = "", 0
    for char in clean(text):
        size = 0 if unicodedata.combining(char) else (2 if unicodedata.east_asian_width(char) in "WF" else 1)
        if columns + size > width:
            return result[:-1] + "…" if result else ""
        result += char
        columns += size
    return result


def action_for(pane):
    return {"session": pane["session_id"], "window": pane["window_id"], "pane": pane["pane_id"]}


def cleanup_runtime(all_panes):
    """Keep dead pane maps bounded. No screen contents or histories are stored."""
    marker = RUNTIME / (SERVER + ".gc")
    try:
        if time.time() - marker.stat().st_mtime < 60:
            return
    except OSError:
        pass
    live = {p["pane_id"][1:] for p in all_panes}
    for path in RUNTIME.glob(SERVER + "-*.json"):
        part = path.stem[len(SERVER) + 1:]
        if part.isdigit() and part not in live:
            path.unlink(missing_ok=True)
    for owner in RUNTIME.glob("*-owner.json"):
        prefix = owner.stem[:-len("-owner")]
        if prefix == SERVER or not re.fullmatch(r"[0-9a-f]{12}", prefix):
            continue
        try:
            pid = int(json.loads(owner.read_text())["pid"])
            if pid <= 1:
                continue
            os.kill(pid, 0)
        except ProcessLookupError:
            # Only remove namespaces whose recorded tmux server is gone.
            for stale in RUNTIME.glob(prefix + "*"):
                stale.unlink(missing_ok=True)
        except (OSError, ValueError, KeyError):
            pass
    marker.touch()


def server_snapshot(required_pane=None, force=False):
    """Share expensive process/screen reads across all navigator panes."""
    path = RUNTIME / (SERVER + "-snapshot.json")
    def read_cached():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
    def has_pane(value):
        return required_pane is None or any(p["pane_id"] == required_pane for p in value.get("panes", []))
    with open(RUNTIME / (SERVER + "-snapshot.lock"), "w") as lock:
        cached = read_cached()
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            if has_pane(cached):
                # Keep input responsive while another UI gathers fresh status.
                return cached
            fcntl.flock(lock, fcntl.LOCK_EX)
        cached = read_cached()
        age = time.monotonic() - cached.get("time", 0)
        if not force and has_pane(cached) and 0 <= age < 0.95:
            return cached
        all_panes = panes()
        viewed = set(tmux(["list-clients", "-F", "#{window_id}"]).splitlines())
        if viewed:
            agents = detect_agents([p for p in all_panes if p.get("@herdr_sidebar") != "1"], tmux)
        else:
            # Detached sessions have nobody to show status to. Keep the last
            # bounded snapshot until a client attachment wakes a visible UI.
            live_ids = {p["pane_id"] for p in all_panes}
            agents = [a for a in cached.get("agents", []) if a["pane_id"] in live_ids]
        previous = {(a["pane_id"], a["agent"]): a["state"] for a in cached.get("agents", [])}
        for agent in agents:
            old = previous.get((agent["pane_id"], agent["agent"]))
            if agent["state"] == "idle" and old in ("working", "done") and agent["window_id"] not in viewed:
                agent["state"], agent["status_label"] = "done", "завершил"
        value = {"time": time.monotonic(), "panes": all_panes, "agents": agents,
                 "visible_windows": sorted(viewed)}
        temporary = path.with_suffix(".%s.tmp" % os.getpid())
        temporary.write_text(json.dumps(value), encoding="utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(path)
        cleanup_runtime(all_panes)
        return value


def snapshot(own, force=False):
    data = server_snapshot(own, force)
    all_panes = data["panes"]
    current = next((p for p in all_panes if p["pane_id"] == own), {})
    groups = {}
    for pane in all_panes:
        groups.setdefault(pane["session_id"], {}).setdefault(pane["window_id"], []).append(pane)
    rows = []
    for session, windows in groups.items():
        active_group = next((g for g in windows.values() if g[0]["window_active"] == "1"), next(iter(windows.values())))
        session_main = content_pane(active_group)
        first = next(iter(windows.values()))[0]
        is_session = session == current.get("session_id")
        rows.append(("session", ("▾ " if is_session else "▸ ") + first["session_name"],
                     "accent" if is_session else "text", action_for(session_main) if session_main else None))
        for window, group in windows.items():
            main = content_pane(group)
            if not main:
                continue
            active = window == current.get("window_id")
            rows.append(("window", "  %s %s  %s" % ("▎" if active else " ", main["window_index"], main["window_name"]),
                         "selected" if active else "text", action_for(main)))
            rows.append(("gap", "", "separator", action_for(main)))
    return current, rows, data["agents"], all_panes, current.get("window_id") in data.get("visible_windows", [])


def scroll_limit(length, capacity, step=1):
    """Align agent scrolling to complete cards, including the final card."""
    excess = max(0, length - capacity)
    return min(max(0, length - step), ((excess + step - 1) // step) * step)


def screen_loop(screen):
    own = os.environ["TMUX_PANE"]
    curses.curs_set(0)
    curses.start_color()
    curses.use_default_colors()
    colors = {"text": (252, 234), "muted": (245, 234), "accent": (111, 234),
              "selected": (153, 237), "separator": (238, 234),
              "working": (221, 234), "blocked": (203, 234), "idle": (114, 234),
              "done": (111, 234), "unknown": (245, 234)}
    for number, (name, values) in enumerate(colors.items(), 1):
        curses.init_pair(number, *values)
        colors[name] = curses.color_pair(number)
    screen.bkgd(" ", colors["text"])
    screen.keypad(True)
    offsets = {"windows": 0, "agents": 0}
    capacities = {"windows": 0, "agents": 0}
    limits = {"windows": 0, "agents": 0}
    current, window_rows, agents, choices = {}, [], [], []
    selected, selected_section = 0, "windows"
    keyboard_selection = False
    old_render, old_state, old_model, old_size = None, None, None, None
    old_divider = None
    # Required-pane validation already invalidates an incomplete cache. Forcing
    # every new UI to rescan serializes startup work across many windows.
    next_snapshot, force_snapshot = 0, False
    visible, dirty = True, True
    wheel = {curses.KEY_F5: ("agents", -4), curses.KEY_F6: ("agents", 4),
             curses.KEY_F7: ("windows", -2), curses.KEY_F8: ("windows", 2)}
    while True:
        now = time.monotonic()
        if now >= next_snapshot:
            was_forced = force_snapshot
            current, window_rows, agents, all_panes, visible = snapshot(own, force_snapshot)
            force_snapshot = False
            if was_forced:
                visible = True
            if not current:
                return
            same_window = [p for p in all_panes if p["window_id"] == current["window_id"]]
            if not content_pane(same_window):
                return
            model = (current["window_id"], window_rows, agents)
            if model != old_model:
                dirty = True
                old_model = model
            # Hidden UIs do no rendering and only check shared data every 5s.
            # The selection/attachment hook sends F9 to wake a newly visible UI.
            next_snapshot = time.monotonic() + (1.0 if visible else 5.0)

        height, width = screen.getmaxyx()
        if (height, width) != old_size:
            dirty = True
            old_size = (height, width)
        if dirty and (visible or old_render is None):
            divider = max(6, min(height - 8, int(height * 0.50))) if height >= 16 else max(3, height // 2)
            capacities["windows"] = max(0, divider - 3)
            capacities["agents"] = max(0, height - divider - 4)
            # Display whole cards when there is room. Unused rows leave breathing
            # space above the footer instead of cutting the next agent in half.
            if capacities["agents"] >= 4:
                capacities["agents"] -= capacities["agents"] % 4
            agent_rows = []
            for agent in agents:
                action = action_for(agent)
                state = agent["state"]
                agent_rows.extend([
                    ("agent", " ● %s" % agent["agent"], state, action),
                    ("detail", "   %s · %s" % (agent["window_index"], agent["window_name"]), "text", action),
                    ("detail", "   %s · %s" % (agent["status_label"], agent["session_name"]), state, action),
                    ("gap", " " + "─" * max(0, width - 2), "separator", action)])
            limits["windows"] = scroll_limit(len(window_rows), capacities["windows"])
            limits["agents"] = scroll_limit(len(agent_rows), capacities["agents"], 4)
            for section in offsets:
                offsets[section] = max(0, min(offsets[section], limits[section]))
            lines = [("", "text", None) for _ in range(height)]
            hits = {}
            def put(y, text, color="text", action=None):
                if 0 <= y < height:
                    lines[y] = (fit(text, max(0, width - 1)), color, action)
                    if action:
                        hits[str(y)] = action
            put(0, "  TMUX  /  NAVIGATOR", "accent")
            window_hint = " ↑↓" if limits["windows"] else ""
            put(1, "  СЕССИИ / ОКНА" + window_hint, "muted")
            put(2, " " + "─" * max(0, width - 2), "separator")
            for y, row in enumerate(window_rows[offsets["windows"]:offsets["windows"] + capacities["windows"]], 3):
                put(y, *row[1:])
            put(divider, " " + "─" * max(0, width - 2), "separator")
            first = offsets["agents"] // 4 + 1
            last = min(len(agents), (offsets["agents"] + capacities["agents"] + 3) // 4)
            label = "%s–%s/%s" % (first, last, len(agents)) if agents and limits["agents"] else str(len(agents))
            put(divider + 1, "  АГЕНТЫ  " + label, "accent")
            for y, row in enumerate(agent_rows[offsets["agents"]:offsets["agents"] + capacities["agents"]], divider + 2):
                put(y, *row[1:])
            if not agents:
                put(divider + 3, "  Нет запущенных агентов", "muted")
            put(height - 2, "  клик · колесо · PgUp/PgDn", "muted")
            put(height - 1, "  ^A b фокус · ^A B скрыть", "muted")
            choices = [(int(y), action) for y, action in hits.items()
                       if (int(y) > divider) == (selected_section == "agents")]
            choices = [(y, a) for index, (y, a) in enumerate(choices)
                       if index == 0 or choices[index - 1][1] != a]
            if keyboard_selection and choices:
                selected = max(0, min(selected, len(choices) - 1))
                y = choices[selected][0]
                text, _, action = lines[y]
                lines[y] = (text, "selected", action)
            render = (height, width, lines)
            if render != old_render:
                for y, (text, color, _) in enumerate(lines):
                    try:
                        screen.addnstr(y, 0, " " * max(0, width - 1), width - 1, colors["text"])
                        screen.addnstr(y, 0, text, max(0, width - 1), colors[color])
                    except curses.error:
                        pass
                screen.noutrefresh()
                curses.doupdate()
                old_render = render
            state = {"hits": hits, "divider": divider, "offsets": dict(offsets),
                     "capacities": dict(capacities), "limits": dict(limits)}
            if state != old_state:
                save_state(own, state)
                old_state = state
            if divider != old_divider:
                # The tmux mouse binding picks the section without a subprocess.
                tmux(["set-option", "-p", "-t", own, "@navigator_divider", str(divider)])
                old_divider = divider
            dirty = False

        # getch wakes immediately for input even with a long timeout. No busy loop.
        screen.timeout(max(1, min(5000, int((next_snapshot - time.monotonic()) * 1000))))
        key = screen.getch()
        if key in wheel:
            section, amount = wheel[key]
            offsets[section] = max(0, min(limits[section], offsets[section] + amount))
            selected_section, selected = section, 0
            keyboard_selection, dirty = False, True
        elif key == curses.KEY_F9:
            visible, force_snapshot, dirty = True, True, True
            next_snapshot = 0
        elif key == curses.KEY_RESIZE:
            dirty = True
            next_snapshot = 0
        elif key in (curses.KEY_PPAGE, curses.KEY_NPAGE, curses.KEY_HOME, curses.KEY_END):
            if key == curses.KEY_HOME:
                offsets[selected_section] = 0
            elif key == curses.KEY_END:
                offsets[selected_section] = limits[selected_section]
            else:
                amount = max(1, capacities[selected_section]) * (-1 if key == curses.KEY_PPAGE else 1)
                offsets[selected_section] = max(0, min(limits[selected_section], offsets[selected_section] + amount))
            selected, dirty = 0, True
        elif key in (ord("j"), curses.KEY_DOWN):
            keyboard_selection, dirty = True, True
            if choices and selected < len(choices) - 1:
                selected += 1
            else:
                offsets[selected_section] += 4 if selected_section == "agents" else 1
        elif key in (ord("k"), curses.KEY_UP):
            keyboard_selection, dirty = True, True
            if selected > 0:
                selected -= 1
            else:
                offsets[selected_section] -= 4 if selected_section == "agents" else 1
        elif key in (10, 13, curses.KEY_ENTER):
            if choices:
                navigate(choices[min(selected, len(choices) - 1)][1])
        elif key == 9:
            keyboard_selection, dirty = True, True
            selected_section = "agents" if selected_section == "windows" else "windows"
            selected = 0
        elif key in (ord("q"), 27):
            main = content_pane(panes(current.get("window_id")))
            if main:
                tmux(["select-pane", "-t", main["pane_id"]])
        elif key == ord("r"):
            force_snapshot, next_snapshot = True, 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["ui", "ensure", "prune", "toggle", "focus", "click"])
    parser.add_argument("--window")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--pane")
    parser.add_argument("--client")
    parser.add_argument("--y", type=int, default=0)
    args = parser.parse_args()
    server_parts = os.environ.get("TMUX", "").split(",")
    if len(server_parts) >= 2 and server_parts[1].isdigit():
        owner = RUNTIME / (SERVER + "-owner.json")
        if not owner.exists():
            owner.write_text(json.dumps({"pid": int(server_parts[1]), "socket": SOCKET}))
            os.chmod(owner, 0o600)
    if args.mode == "ui":
        locale.setlocale(locale.LC_ALL, "")
        try:
            curses.wrapper(screen_loop)
        finally:
            state_file(os.environ["TMUX_PANE"]).unlink(missing_ok=True)
    elif args.mode in ("ensure", "prune"):
        ensure(args.window, args.all, args.mode == "prune")
    elif args.mode == "toggle":
        tmux(["set-option", "-g", "@herdr_sidebar_enabled", "off" if enabled() else "on"])
        ensure(all_windows=True)
    elif args.mode == "focus":
        focus(args.window)
    elif args.mode == "click":
        click(args.pane, args.y, args.client)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.TimeoutExpired) as error:
        print("tmux navigator: %s" % error, file=sys.stderr)
