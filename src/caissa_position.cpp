#include "eloi/brain.hpp"

#include "Move.hpp"
#include "Position.hpp"

#include <algorithm>

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
  return probe;
}

}  // namespace eloi
