#include "eloi/brain.hpp"

#include "Game.hpp"
#include "Move.hpp"
#include "Position.hpp"

#include <algorithm>
#include <vector>

namespace eloi {

CaissaPositionProbe probe_caissa_position(const Board& board) {
  CaissaPositionProbe probe;
  if (board.horde || board.chess960) {
    probe.detail = "Caissa position adapter is Standard-only at this stage";
    return probe;
  }

  ::InitEngine();
  const std::string fen = to_fen(board);
  ::Position position;
  probe.parsed = position.FromFEN(fen);
  if (!probe.parsed) {
    probe.detail = "Caissa rejected Eloi's FEN";
    return probe;
  }

  probe.reconstructed_fen = position.ToFEN();
  probe.fen_round_trip = probe.reconstructed_fen == fen;

  std::vector<::Move> moves;
  position.GetNumLegalMoves(&moves);
  probe.legal_moves.reserve(moves.size());
  for (const ::Move& move : moves)
    probe.legal_moves.push_back(move.ToString());
  std::ranges::sort(probe.legal_moves);
  probe.legal_moves.erase(
      std::ranges::unique(probe.legal_moves).begin(),
      probe.legal_moves.end());

  Board initial = board;
  std::vector<Move> history;
  history.reserve(initial.history.size());
  while (!initial.history.empty()) {
    const auto move = initial.last_move();
    if (!move || !initial.pop()) {
      probe.detail = "Eloi could not rewind position history";
      return probe;
    }
    history.push_back(*move);
  }
  std::ranges::reverse(history);

  ::Position caissa_initial;
  if (!caissa_initial.FromFEN(to_fen(initial))) {
    probe.detail = "Caissa rejected Eloi's rewound initial FEN";
    return probe;
  }
  ::Game game;
  game.Reset(caissa_initial);
  for (const Move& eloi_move : history) {
    const ::Move move = game.GetPosition().MoveFromString(
        eloi_move.uci(), MoveNotation::LAN);
    if (!move.IsValid() || !game.DoMove(move)) {
      probe.detail = "Caissa rejected replayed move " + eloi_move.uci();
      return probe;
    }
  }
  probe.history_size = game.GetMoves().size();
  probe.history_replayed =
      probe.history_size == history.size() &&
      game.GetPosition().ToFEN() == fen;
  probe.repetition_count = game.GetRepetitionCount(game.GetPosition());
  probe.drawn = game.IsDrawn();
  return probe;
}

}  // namespace eloi
