import subprocess
import unittest
from unittest.mock import patch

from agent_detector import Process, _interactive, _launch, _read_processes, _state, detect_agents


class DetectionTests(unittest.TestCase):
    def test_ps_requests_untruncated_command_lines(self):
        path = "/very/" + "long-directory/" * 25 + "claude"
        result = subprocess.CompletedProcess([], 0, f"42 1 {path} {path} --model sonnet\n", "")
        with patch("agent_detector.subprocess.run", return_value=result) as run:
            processes = _read_processes()
        self.assertIn("-ww", run.call_args.args[0])
        self.assertEqual(_launch(processes[0]), ("Claude", ["--model", "sonnet"]))

    def test_empty_and_invalid_panes_do_not_scan_processes(self):
        panes = [{"pane_pid": "oops"}, {"pane_pid": "42", "pane_dead": "1"}, {"pane_pid": "0"}]
        with patch("agent_detector._read_processes") as read:
            self.assertEqual(detect_agents(panes, lambda args: ""), [])
        read.assert_not_called()

    def test_claude_native_version(self):
        process = Process(42, 1, "2.1.223", "/Users/test/.local/share/claude/versions/2.1.223 --model sonnet")
        self.assertEqual(_launch(process), ("Claude", ["--model", "sonnet"]))

    def test_shell_argument_is_not_an_agent(self):
        self.assertIsNone(_launch(Process(42, 1, "zsh", 'zsh -c "echo claude codex"')))
        self.assertIsNone(_launch(Process(42, 1, "node", "node my-script.js claude")))

    def test_headless_agents_are_not_interactive(self):
        for args in (["app-server"], ["exec", "do a task"], ["-m", "gpt-5", "exec", "task"], ["mcp-server"]):
            self.assertFalse(_interactive("Codex", args))
        self.assertFalse(_interactive("Claude", ["-p", "task"]))
        self.assertFalse(_interactive("Claude", ["--print", "--output-format=stream-json"]))
        self.assertTrue(_interactive("Codex", ["resume", "--last"]))
        self.assertTrue(_interactive("Codex", ["--model", "exec"]))

    def test_only_pane_descendants_and_wrapper_deduplication(self):
        processes = [
            Process(10, 1, "zsh", "zsh"),
            Process(11, 10, "node", "node /x/@openai/codex/bin/codex.js"),
            Process(12, 11, "codex", "/x/codex"),
            Process(20, 1, "codex", "codex app-server"),
            Process(21, 1, "claude", "claude"),
        ]
        pane = {"pane_id": "%1", "pane_pid": "10", "window_id": "@4"}
        calls = []
        def tmux(args):
            calls.append(args)
            return "› \n? for shortcuts"
        with patch("agent_detector._read_processes", return_value=processes):
            rows = detect_agents([pane], tmux)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["agent"], rows[0]["pid"], rows[0]["state"]), ("Codex", 12, "idle"))
        self.assertEqual(calls, [["capture-pane", "-p", "-t", "%1"]])

    def test_capture_is_bounded_to_bottom_visible_rows_and_shared_per_pane(self):
        processes = [Process(10, 1, "zsh", "zsh"), Process(11, 10, "claude", "claude"), Process(12, 10, "codex", "codex")]
        pane = {"pane_id": "%1", "pane_pid": "10", "pane_height": "100"}
        calls = []
        def tmux(args):
            calls.append(args)
            return "› \n? for shortcuts"
        with patch("agent_detector._read_processes", return_value=processes) as read:
            rows = detect_agents([pane], tmux)
        read.assert_called_once_with()
        self.assertEqual(len(rows), 2)
        self.assertEqual(calls, [["capture-pane", "-p", "-t", "%1", "-S", "68", "-E", "99"]])
        self.assertTrue(all(row["state"] == "idle" for row in rows))
        self.assertTrue(all("screen" not in row and "args" not in row for row in rows))

    def test_small_pane_capture_does_not_include_scrollback(self):
        pane = {"pane_id": "%1", "pane_pid": "10", "pane_height": "12"}
        with patch("agent_detector._read_processes", return_value=[Process(10, 1, "claude", "claude")]):
            calls = []
            detect_agents([pane], lambda args: calls.append(args) or "")
        self.assertEqual(calls[0][-4:], ["-S", "0", "-E", "11"])

    def test_fresh_ui_near_top_of_tall_pane_is_not_lost(self):
        pane = {"pane_id": "%1", "pane_pid": "10", "pane_height": "100"}
        def tmux(args):
            return "\n" * 32 if "-S" in args else "Codex\n› \n? for shortcuts\n" + "\n" * 90
        with patch("agent_detector._read_processes", return_value=[Process(10, 1, "codex", "codex")]):
            rows = detect_agents([pane], tmux)
        self.assertEqual(rows[0]["state"], "idle")

    def test_process_existence_does_not_imply_working(self):
        self.assertEqual(_state("Claude", "some output"), "unknown")
        self.assertEqual(_state("Codex", "some output", "my terminal"), "unknown")

    def test_claude_state_markers(self):
        self.assertEqual(_state("Claude", "", "⠋ Build"), "working")
        self.assertEqual(_state("Claude", "✻ Thinking… (3s · ↓ 20 tokens)\n❯ "), "working")
        self.assertEqual(_state("Claude", "Bash command\nDo you want to proceed?\n❯ 1. Yes\n2. No\nEnter to confirm · Esc to cancel"), "blocked")
        self.assertEqual(_state("Claude", "finished\n❯ \n? for shortcuts"), "idle")
        self.assertEqual(_state("Claude", "", "✳ Build"), "idle")

    def test_old_permission_above_current_prompt_is_history(self):
        text = "Do you want to proceed?\n❯ 1. Yes\n2. No\nEnter to confirm · Esc to cancel\nDone\n❯ \n? for shortcuts"
        self.assertEqual(_state("Claude", text), "idle")
        self.assertEqual(_state("Codex", "allow command?\nDone\n› \n? for shortcuts"), "idle")

    def test_current_permission_overrides_lingering_spinner(self):
        screen = "Do you want to proceed?\n❯ 1. Yes\n2. No\nEnter to confirm · Esc to cancel"
        self.assertEqual(_state("Claude", screen, "⠋ Build"), "blocked")
        self.assertEqual(_state("Codex", "Allow command?\nPress enter to confirm or esc to cancel", "⠋ Codex"), "blocked")

    def test_codex_queued_inputs_do_not_finish_current_turn(self):
        for heading in (
            "Queued follow-up inputs",
            "Messages to be submitted after next tool call (press esc to interrupt and send immediately)",
            "Messages to be submitted at end of turn",
        ):
            screen = f"• Working (12s • esc to interrupt)\n• {heading}\n  next task\n› "
            with self.subTest(heading=heading):
                self.assertEqual(_state("Codex", screen, "Codex"), "working")
                self.assertEqual(_state("Codex", screen.replace("\n› ", "\n• Finished\n› "), "Codex"), "idle")

    def test_codex_state_markers(self):
        self.assertEqual(_state("Codex", "", "Codex: Action Required"), "blocked")
        self.assertEqual(_state("Codex", "• Working (12s • esc to interrupt)\n› \n? for shortcuts"), "working")
        self.assertEqual(_state("Codex", "• Working (12s • esc to interrupt)\n• Done.\n› \n? for shortcuts"), "idle")
        self.assertEqual(_state("Codex", "Folder access\nTrust this folder?\nCodex can read, edit, and run files here\n› Trust and continue\nEsc to cancel"), "blocked")
        self.assertEqual(_state("Codex", "Reconnect failed — check the endpoint, then relaunch (12s)"), "unknown")


if __name__ == "__main__":
    unittest.main()
