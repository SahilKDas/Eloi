"""In-memory ABC60 protocol tests: no engines, temporary files or deletion."""
import datetime as dt
import unittest
from unittest.mock import patch

import run_abc60 as run


def opening_rows(count=4):
    rows = []
    for move in list(run.chess.Board().legal_moves)[:count]:
        board = run.chess.Board()
        board.push(move)
        rows.append({"fen": board.fen(), "reserve_index": len(rows) + 17})
    return rows


def screening(labels=None):
    rows = run.make_schedule(opening_rows(), "screening")
    for row in rows:
        row["label"] = (labels or {}).get(row["candidate"], "draw")
    return rows


def finished_game():
    plan = {"stage": "screening", "game": 1, "candidate": "A", "candidate_white": True,
            "opening": 0, "reserve_index": 17, "fen": run.chess.STARTING_FEN}
    moves = ["f2f3", "e7e5", "g2g4", "d8h4"]
    board = run.chess.Board()
    for move in moves:
        board.push_uci(move)
    row = {**plan, "protocol_sha256": "frozen", "moves": moves, "move_seconds": [.25] * 4,
           "final_fen": board.fen(), "result": "0-1", "label": "loss",
           "pgn": run.pgn_text(plan, moves, "0-1", "CHECKMATE")}
    return plan, row


class ProtocolTests(unittest.TestCase):
    def test_mirrored_screening(self):
        rows = screening()
        self.assertEqual(len(rows), 24)
        for name in "ABC":
            group = [r for r in rows if r["candidate"] == name]
            self.assertEqual(len(group), 8)
            for opening in range(4):
                self.assertEqual({r["candidate_white"] for r in group if r["opening"] == opening}, {True, False})
        self.assertEqual([rows[i * 6]["candidate"] for i in range(4)], list("ABCA"))

    def test_confirmation_is_twenty_mirrored_games(self):
        rows = run.make_schedule(opening_rows(10), "confirmation", "B")
        self.assertEqual(len(rows), 20)
        self.assertEqual({r["candidate"] for r in rows}, {"B"})

    def test_disjoint_openings_skip_duplicates_and_prior_use(self):
        positions = [{"fen": run.chess.STARTING_FEN}] * 17 + opening_rows(20)
        used = {run.fen_key(positions[17]["fen"])}
        first, second = run.pick_openings(positions, used)
        self.assertEqual((len(first), len(second)), (4, 10))
        self.assertEqual(len({run.fen_key(p["fen"]) for p in first + second}), 14)
        self.assertFalse({run.fen_key(p["fen"]) for p in first + second} & used)

    def test_counters_not_distinct_openings(self):
        self.assertEqual(run.fen_key(run.chess.STARTING_FEN), run.fen_key(run.chess.STARTING_FEN[:-3] + "9 8"))

    def test_points_and_nonloss_separate(self):
        rows = screening({"A": "win", "B": "draw", "C": "loss"})
        b = run.stats([r for r in rows if r["candidate"] == "B"])
        self.assertEqual((b["points"], b["score"], b["non_losses_secondary"]), (4, .5, 8))
        self.assertEqual(run.select(rows), "A")

    def test_fixed_tie_preference(self):
        self.assertEqual(run.select(screening()), "C")

    def test_fewer_losses_breaks_equal_points(self):
        rows = screening()
        group = [r for r in rows if r["candidate"] == "C"]
        group[0]["label"] = "win"
        group[1]["label"] = "loss"
        self.assertEqual(run.select(rows), "A")

    def test_incomplete_screening_rejected(self):
        with self.assertRaises(ValueError):
            run.select(screening()[:-1])

    def test_incident_screening_rejected(self):
        rows = screening()
        rows[0]["protocol_failure"] = "baseline watchdog"
        with self.assertRaises(ValueError):
            run.select(rows)

    def test_threshold_requires_completed_confirmation(self):
        rows = run.make_schedule(opening_rows(10), "confirmation", "C")
        for i, row in enumerate(rows):
            row["label"] = "win" if i < 11 else "loss"
        self.assertTrue(run.confirmation_positive(rows))
        self.assertFalse(run.confirmation_positive(rows[:11]))
        rows[0]["label"] = "draw"
        self.assertFalse(run.confirmation_positive(rows))

    def test_confirmation_incident_never_passes(self):
        rows = run.make_schedule(opening_rows(10), "confirmation", "C")
        for row in rows:
            row["label"] = "win"
        rows[0]["protocol_failure"] = "baseline crash"
        self.assertFalse(run.confirmation_positive(rows))

    def test_identity_mismatch(self):
        with patch.object(run.lab, "sha256", return_value="wrong"):
            with self.assertRaises(ValueError):
                run.verify_identities({"test": ("dummy", "expected")})

    def test_illegal_and_missing_move(self):
        board = run.chess.Board()
        self.assertEqual(run.check_response(board, run.chess.Move.from_uci("e2e5"), .1), "illegal-or-missing-move")
        self.assertEqual(run.check_response(board, None, .1), "illegal-or-missing-move")

    def test_watchdog_boundary(self):
        board = run.chess.Board()
        move = run.chess.Move.from_uci("e2e4")
        self.assertIsNone(run.check_response(board, move, 2.5))
        self.assertEqual(run.check_response(board, move, 2.501), "watchdog-exceeded")

    def test_deadline_cancellation(self):
        budget = run.Budget((dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=61)).isoformat())
        with self.assertRaises(TimeoutError):
            budget.check(55)

    def test_quota_total_training_owned_and_disk(self):
        run.quota_check(1_000_000, 1_000, 1_000, 1_000, 2_000_000_000)
        for args in [(10_000_000_000, 0, 0, 1, 2_000_000_000),
                     (0, 8_000_000_000, 0, 0, 2_000_000_000),
                     (0, 0, 90_000_000, 1, 2_000_000_000), (0, 0, 0, 1, 1)]:
            with self.subTest(args=args), self.assertRaises(ValueError):
                run.quota_check(*args)

    def test_independent_replay(self):
        plan, row = finished_game()
        run.validate_game(row, plan, "frozen")

    def test_wrong_outcome_rejected(self):
        plan, row = finished_game()
        row["label"] = "win"
        with self.assertRaises(ValueError):
            run.validate_game(row, plan, "frozen")

    def test_wrong_pairing_rejected(self):
        plan, row = finished_game()
        row["candidate"] = "B"
        with self.assertRaises(ValueError):
            run.validate_game(row, plan, "frozen")

    def test_wrong_final_fen_rejected(self):
        plan, row = finished_game()
        row["final_fen"] = run.chess.STARTING_FEN
        with self.assertRaises(ValueError):
            run.validate_game(row, plan, "frozen")

    def test_regression_depths_include_stability_depth(self):
        cases = {r["id"]: r for r in run.epd_cases()}
        self.assertEqual(len(cases), 15)
        self.assertEqual(cases["poisoned-pawn-capture"]["depth"], 3)
        self.assertEqual(cases["lichess-001XA"]["depth"], 7)


if __name__ == "__main__":
    unittest.main()
