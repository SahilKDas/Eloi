#!/usr/bin/env python3
"""Additive UI-only adapter; original frozen match runner stays byte-identical.

Fix python-chess Board.legal_moves property access in GET /api/state. No move
selection, pairings, budgets, adjudication, threshold or persistence changes.
See data/nnue_abc100_gui_amendment.json for identity and restart evidence.
"""
import abc100_match as match


class GuiMatch(match.Match):
    def state(self):
        with self.lock:
            board = match.restore_board(self.human)
            return {**self.summary(), "human": {**self.human,
                "current_fen": board.fen(),
                "pieces": {match.chess.square_name(s): ("w" if p.color else "b") + p.symbol().upper()
                           for s, p in board.piece_map().items()},
                "legal_moves": [m.uci() for m in board.legal_moves],
                "turn": "white" if board.turn else "black",
                "pgn": match.game_pgn(self.human)},
                "active": {k: v for k, v in (self.active or {}).items() if k != "pgn"}}


if __name__ == "__main__":
    match.Match = GuiMatch
    match.main()
