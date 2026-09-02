"""Pure/in-memory tests; no engine games and no file deletion."""
import threading
import unittest
from unittest.mock import Mock

import abc100_match as m
from abc100_gui_fix import GuiMatch


def rows(wins, draws, losses, name="A"):
    return [{"candidate": name, "candidate_white": i % 2 == 0, "label": label}
            for i, label in enumerate(["win"] * wins + ["draw"] * draws + ["loss"] * losses)]


class ProtocolTests(unittest.TestCase):
    def test_gui_state_serializes_legal_move_property(self):
        match = GuiMatch.__new__(GuiMatch)
        match.lock = threading.RLock()
        match.summary = Mock(return_value={"automated_completed": 0})
        match.human = {"game": 100, "candidate": "Human", "candidate_white": True,
                       "fen": m.chess.STARTING_FEN, "moves": [], "started": False, "result": "*"}
        match.active = None
        state = match.state()
        self.assertEqual(len(state["human"]["legal_moves"]), 20)
        self.assertIn("e2e4", state["human"]["legal_moves"])
        self.assertEqual(state["human"]["pieces"]["e1"], "wK")
        self.assertEqual(state["active"], {})

    def test_draws_count_fully_for_nonloss(self):
        r = m.summarize(rows(0, 17, 16))["A"]
        self.assertTrue(r["passed"])
        self.assertEqual(r["points"], 8.5)
        self.assertLess(r["score"], 0.5)

    def test_seventeen_losses_fail(self):
        self.assertFalse(m.summarize(rows(16, 0, 17))["A"]["passed"])

    def test_all_draws_pass(self):
        self.assertTrue(m.summarize(rows(0, 33, 0))["A"]["passed"])

    def test_incomplete_never_passes(self):
        self.assertFalse(m.summarize(rows(17, 0, 0))["A"]["passed"])

    def test_human_excluded(self):
        r = m.summarize(rows(16, 0, 17) + rows(1, 0, 0, "Human"))
        self.assertFalse(r["A"]["passed"])
        self.assertEqual(r["A"]["games"], 33)

    def test_protocol_failure_blocks_pass(self):
        data = rows(33, 0, 0)
        data[0]["protocol_failure"] = "deadline"
        self.assertFalse(m.summarize(data)["A"]["passed"])

    def test_schedule_exact_counts_and_equal_assignments(self):
        positions = [{"fen": f"position-{i}"} for i in range(17)]
        data = m.schedule(positions)
        self.assertEqual([r["game"] for r in data], list(range(1, 100)))
        baseline = None
        for name in "ABC":
            part = [r for r in data if r["candidate"] == name]
            self.assertEqual(len(part), 33)
            self.assertEqual(sum(r["candidate_white"] for r in part), 17)
            assignment = [(r["fen"], r["candidate_white"]) for r in part]
            if baseline is not None:
                self.assertEqual(assignment, baseline)
            baseline = assignment
            for i in range(16):
                self.assertEqual(part[i * 2]["fen"], part[i * 2 + 1]["fen"])
                self.assertNotEqual(part[i * 2]["candidate_white"], part[i * 2 + 1]["candidate_white"])

    def test_missing_openings_rejected(self):
        with self.assertRaises(ValueError):
            m.schedule([])

    def test_pgn_roundtrip_and_illegal_saved_move(self):
        row = {"game": 100, "candidate": "Human", "candidate_white": True,
               "fen": m.chess.STARTING_FEN, "moves": ["e2e4", "e7e5", "g1f3"]}
        pgn = m.chess.pgn.read_game(m.io.StringIO(m.game_pgn(row)))
        self.assertEqual(pgn.end().board().fen(), m.restore_board(row).fen())
        row["moves"] = ["e2e5"]
        with self.assertRaises(ValueError):
            m.game_pgn(row)

    def test_terminal_draw_and_checkmate(self):
        match = m.Match.__new__(m.Match)
        row = {"candidate_white": True}
        self.assertTrue(match.finish_if_terminal(row, m.chess.Board("7k/8/8/8/8/8/8/K7 w - - 0 1")))
        self.assertEqual(row["label"], "draw")
        self.assertTrue(match.finish_if_terminal(row, m.chess.Board("7k/6Q1/6K1/8/8/8/8/8 b - - 0 1")))
        self.assertEqual(row["label"], "win")

    def test_human_must_start_cannot_restart_and_stale_move_rejected(self):
        match = m.Match.__new__(m.Match)
        match.lock = threading.RLock()
        match.event = Mock()
        match.persist_human = Mock()
        match.maybe_human_reply = Mock()
        match.human = {"started": False, "candidate_white": True, "fen": m.chess.STARTING_FEN,
                       "moves": [], "thinking": False, "result": "*"}
        with self.assertRaises(ValueError):
            match.human_action("move", {"move": "e2e4", "fen": m.chess.STARTING_FEN})
        match.human_action("start", {"color": "white"})
        with self.assertRaises(ValueError):
            match.human_action("start", {"color": "black"})
        with self.assertRaises(ValueError):
            match.human_action("move", {"move": "e2e4", "fen": "stale"})
        match.human_action("move", {"move": "e2e4", "fen": m.chess.STARTING_FEN})
        self.assertEqual(match.human["moves"], ["e2e4"])
        with self.assertRaises(ValueError):
            match.human_action("move", {"move": "e7e5", "fen": m.restore_board(match.human).fen()})


if __name__ == "__main__":
    unittest.main()
