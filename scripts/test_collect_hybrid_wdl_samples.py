import unittest

import collect_hybrid_wdl_samples as collection

chess = collection.movegen.chess


class HybridWdlCollectionTests(unittest.TestCase):
    def test_outcome_is_from_side_to_move(self):
        self.assertEqual(collection.outcome_for_turn("1-0", chess.WHITE), 1.0)
        self.assertEqual(collection.outcome_for_turn("1-0", chess.BLACK), 0.0)
        self.assertEqual(collection.outcome_for_turn("0-1", chess.WHITE), 0.0)
        self.assertEqual(collection.outcome_for_turn("0-1", chess.BLACK), 1.0)
        self.assertEqual(
            collection.outcome_for_turn("1/2-1/2", chess.WHITE), 0.5
        )

    def test_game_and_position_selection_are_deterministic(self):
        games = [
            {
                "id": f"g{index}",
                "positions": [
                    {"ply": ply, "fen": f"fen-{index}-{ply}", "turn": True}
                    for ply in range(10)
                ],
            }
            for index in range(8)
        ]
        first = collection.select_games(games, 4, "seed")
        second = collection.select_games(games, 4, "seed")
        self.assertEqual(first, second)
        self.assertEqual(
            collection.select_positions(first[0], 3, "seed"),
            collection.select_positions(first[0], 3, "seed"),
        )

    def test_incomplete_result_is_rejected(self):
        with self.assertRaises(collection.CollectionError):
            collection.outcome_for_turn("*", chess.WHITE)

    def test_source_hash_namespaces_game_ids(self):
        source = collection.ROOT / "data" / "abc60_parallel_games.pgn"
        games = collection.read_games(source)
        prefix = collection.probe.sha256_file(source)[:16] + ":"
        self.assertTrue(games)
        self.assertTrue(all(game["id"].startswith(prefix) for game in games))


if __name__ == "__main__":
    unittest.main(verbosity=2)
