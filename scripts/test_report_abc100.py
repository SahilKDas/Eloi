"""In-memory checks for independent result retention; no files or engines."""
import copy
import unittest

import abc100_match as match
import report_abc100 as report


def fixture():
    plan = {"game": 1, "candidate": "A", "candidate_game": 1, "opening": 0,
            "candidate_white": True, "fen": "7k/6Q1/6K1/8/8/8/8/8 b - - 0 1"}
    row = {**plan, "moves": [], "result": "1-0", "label": "win",
           "termination": "CHECKMATE", "protocol_sha256": report.PROTOCOL_SHA}
    row["pgn"] = match.game_pgn(row)
    return row, {"schedule": [plan]}


class ReportTests(unittest.TestCase):
    def test_valid_terminal_game(self):
        report.validate_row(*fixture())

    def test_candidate_result_inversion_rejected(self):
        row, protocol = fixture()
        row["label"] = "loss"
        with self.assertRaisesRegex(ValueError, "Candidate-relative"):
            report.validate_row(row, protocol)

    def test_wrong_protocol_rejected(self):
        row, protocol = fixture()
        row["protocol_sha256"] = "wrong"
        with self.assertRaisesRegex(ValueError, "protocol mismatch"):
            report.validate_row(row, protocol)

    def test_unearned_adjudication_rejected(self):
        row, protocol = fixture()
        row.update(fen=match.chess.STARTING_FEN, result="1/2-1/2", label="draw")
        protocol["schedule"][0]["fen"] = row["fen"]
        row["pgn"] = match.game_pgn(row)
        with self.assertRaisesRegex(ValueError, "Nonterminal"):
            report.validate_row(row, protocol)

    def test_pairing_change_rejected(self):
        row, protocol = fixture()
        row["opening"] = 1
        with self.assertRaisesRegex(ValueError, "pairing mismatch"):
            report.validate_row(row, protocol)

    def test_human_resignation(self):
        row, protocol = fixture()
        row.update(game=100, candidate="Human", fen=match.chess.STARTING_FEN,
                   result="0-1", label="loss", termination="Human resignation")
        row["pgn"] = match.game_pgn(row)
        report.validate_row(row, protocol)

    def test_odd_game_excluded_from_paired_interval(self):
        rows = [{"candidate": "C", "candidate_game": i + 1, "opening": i // 2,
                 "candidate_white": i % 2 == 0, "label": "draw" if i < 32 else "loss"}
                for i in range(33)]
        result = report.paired_summary(rows, "C")
        self.assertEqual(len(result["mirrored_pairs"]), 16)
        self.assertEqual(result["paired_score_95pct_descriptive_interval"], [0.5, 0.5])
        self.assertEqual(result["unpaired_extra_game"]["result"], "loss")


if __name__ == "__main__":
    unittest.main()
