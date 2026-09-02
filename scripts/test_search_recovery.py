#!/usr/bin/env python3
"""Fast, offline tests for search-recovery partition and match integrity."""
import hashlib
import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch, MagicMock

import engine_lab as lab
import search_recovery as recovery


class RecoveryTests(unittest.TestCase):
    def test_partition_is_order_independent_disjoint_and_exact(self):
        rows = [{"fen": f"fixture-{i}"} for i in range(500)]
        first = recovery.partition_openings({"positions": rows})
        second = recovery.partition_openings({"positions": list(reversed(rows))})
        self.assertEqual(first, second)
        self.assertEqual([v["count"] for v in first.values()], [20, 30, 30, 150, 270])
        flat = [r["fen"] for v in first.values() for r in v["positions"]]
        expected = sorted((r["fen"] for r in rows), key=lambda fen:
                          (hashlib.sha256(recovery.SEED + fen.encode()).digest(), fen))
        self.assertEqual(flat, expected)
        self.assertEqual(len(set(flat)), 500)

    def test_duplicate_openings_are_rejected(self):
        with self.assertRaises(ValueError):
            recovery.partition_openings({"positions": [{"fen": "same"}] * 500})

    def test_frozen_artifact_cannot_be_replaced(self):
        with tempfile.TemporaryDirectory() as raw:
            path = pathlib.Path(raw) / "frozen.json"
            recovery.immutable_write(path, b"first")
            recovery.immutable_write(path, b"first")
            with self.assertRaises(ValueError):
                recovery.immutable_write(path, b"changed")
            self.assertEqual(path.read_bytes(), b"first")

    def test_165_points_pass_300_game_score_gate(self):
        identity = {"games": 300, "gate_metric": "score", "required_half_points": 330}
        rows = [{"game": i + 1, "result": "win" if i < 100 else
                 "draw" if i < 230 else "loss"} for i in range(300)]
        report = {"identity": identity, "results": rows}
        lab.summarize_strength(report)
        self.assertEqual(report["points"], 165)
        self.assertTrue(report["passed"])
        rows[229]["result"] = "loss"
        lab.summarize_strength(report)
        self.assertFalse(report["passed"])
        rows[229]["result"] = "draw"
        rows.pop()
        lab.summarize_strength(report)
        self.assertFalse(report["passed"])

    def test_protocol_failure_overrides_a_winning_score(self):
        report = {"identity": {"games": 2, "gate_metric": "score", "required_half_points": 2},
                  "results": [{"game": 1, "result": "win", "protocol_failure": "deadline"},
                              {"game": 2, "result": "win"}]}
        lab.summarize_strength(report)
        self.assertFalse(report["passed"])

    def test_score_match_is_frozen_resumable_and_hash_bound(self):
        with tempfile.TemporaryDirectory() as raw:
            root = pathlib.Path(raw)
            candidate, baseline = root / "candidate.exe", root / "baseline.exe"
            candidate.write_bytes(b"candidate")
            baseline.write_bytes(b"baseline")
            suite, protocol = root / "suite.json", root / "protocol.json"
            suite.write_text(json.dumps({"positions": [{"fen": lab.chess.STARTING_FEN}]}))
            protocol.write_text("{}")
            checkpoint, pgn = root / "match.json", root / "match.pgn"

            def game(*args, **kwargs):
                # Protocol must already exist before game one starts.
                self.assertTrue(checkpoint.exists())
                self.assertEqual(json.loads(checkpoint.read_text())["identity"]["nodes_per_move"], 10000)
                g = lab.chess.pgn.Game()
                g.headers["Result"] = "1/2-1/2"
                return "draw", g

            kwargs = dict(movetime_ms=None, games=2, nodes=10000, gate_metric="score",
                          required_score=0.5, protocol_path=protocol)
            with patch.object(lab, "start_engine", return_value=MagicMock()), patch.object(lab, "play_game", side_effect=game):
                report = lab.strength_gate(candidate, baseline, suite, checkpoint, pgn, **kwargs)
                self.assertTrue(report["passed"])
                self.assertEqual(report["identity"]["required_half_points"], 2)
                self.assertEqual(report["pgn_sha256"], lab.sha256(pgn))
                evidence = json.loads(checkpoint.with_suffix(".evidence.json").read_text())
                self.assertEqual(evidence["checkpoint_sha256"], lab.sha256(checkpoint))
                lab.strength_gate(candidate, baseline, suite, checkpoint, pgn, **kwargs)
                for change in ({"games": 4}, {"required_score": 0.6}, {"nodes": 10001}):
                    with self.assertRaises(ValueError):
                        lab.strength_gate(candidate, baseline, suite, checkpoint, pgn, **(kwargs | change))
                with pgn.open("a") as stream:
                    stream.write("tampered")
                with self.assertRaises(ValueError):
                    lab.strength_gate(candidate, baseline, suite, checkpoint, pgn, **kwargs)

    def test_budget_types_are_exclusive(self):
        with tempfile.TemporaryDirectory() as raw:
            root = pathlib.Path(raw)
            suite = root / "suite.json"
            suite.write_text(json.dumps({"positions": [{"fen": lab.chess.STARTING_FEN}]}))
            for time, nodes in ((250, 1000), (None, None), (None, 0)):
                with self.assertRaises(ValueError):
                    lab.strength_gate(root / "a", root / "b", suite, root / "c", root / "d",
                                      movetime_ms=time, nodes=nodes, games=2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
