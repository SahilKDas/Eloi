#include "eloi/chess.hpp"
#include "eloi/version.hpp"

#include <charconv>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <sstream>

namespace eloi {
namespace {
void string_json(std::ostream& out, std::string_view value) {
  out << '"';
  for (const unsigned char c : value) {
    if (c == '"' || c == '\\') out << '\\' << c;
    else if (c == '\n') out << "\\n";
    else if (c == '\r') out << "\\r";
    else if (c == '\t') out << "\\t";
    else if (c < 32) out << '?';
    else out << c;
  }
  out << '"';
}

void moves_json(std::ostream& out, const std::vector<Move>& moves, Board board) {
  out << '[';
  bool comma = false;
  for (const Move& move : moves) {
    if (comma) out << ',';
    string_json(out, uci_move(move, board.position, board.chess960));
    comma = true;
    if (!board.push(move)) break;
  }
  out << ']';
}

const char* bound_name(int flag) {
  return flag < 0 ? "upper" : flag > 0 ? "lower" : "exact";
}

void result_json(std::ostream& out, const SearchResult& row, const Board& board) {
  out << "{\"depth\":" << row.depth << ",\"score_cp\":" << row.score_cp
      << ",\"mate\":" << row.mate << ",\"elapsed_ms\":" << row.elapsed.count()
      << ",\"static_eval_cp\":" << row.static_eval_cp << ",\"selected_move\":";
  string_json(out, row.pv.empty() ? "0000" : uci_move(row.pv.front(), board.position, board.chess960));
  out << ",\"pv\":";
  moves_json(out, row.pv, board);
  out << ",\"nodes\":" << row.nodes << ",\"qnodes\":" << row.qnodes
      << ",\"tt_hits\":" << row.tt_hits
      << ",\"pruning\":{\"beta_cutoffs\":" << row.beta_cutoffs
      << ",\"razor_cutoffs\":" << row.razor_cutoffs
      << ",\"reverse_futility_cutoffs\":" << row.reverse_futility_cutoffs
      << ",\"internal_reductions\":" << row.internal_reductions
      << ",\"futility_prunes\":" << row.futility_prunes
      << ",\"late_move_prunes\":" << row.late_move_prunes
      << ",\"lmr_reductions\":" << row.lmr_reductions
      << ",\"null_cutoffs\":" << row.null_cutoffs
      << ",\"probcut_cutoffs\":" << row.probcut_cutoffs
      << ",\"singular_extensions\":" << row.singular_extensions << '}'
      << ",\"root_tt\":{\"hit\":" << (row.root_tt_hit ? "true" : "false")
      << ",\"depth\":" << row.root_tt_depth << ",\"score_cp\":" << row.root_tt_score_cp
      << ",\"bound\":";
  string_json(out, bound_name(row.root_tt_bound));
  out << "},\"root_moves\":[";
  bool comma = false;
  for (const auto& move : row.root_moves) {
    if (comma) out << ',';
    comma = true;
    out << "{\"move\":";
    string_json(out, uci_move(move.move, board.position, board.chess960));
    out << ",\"score_cp\":";
    if (move.score_cp) out << *move.score_cp;
    else out << "null";
    out << ",\"bound\":";
    if (move.score_cp) string_json(out, bound_name(move.bound));
    else out << "null";
    out << ",\"static_eval_cp\":" << move.static_eval_cp
        << ",\"see_cp\":" << move.see_cp << ",\"lane\":" << move.lane
        << ",\"tt\":{\"hit\":" << (move.tt_hit ? "true" : "false")
        << ",\"depth\":" << move.tt_depth << ",\"score_cp\":" << move.tt_score_cp
        << ",\"bound\":";
    string_json(out, bound_name(move.tt_bound));
    out << "},\"pv\":";
    moves_json(out, move.pv, board);
    out << '}';
  }
  out << "]}";
}

bool positive_integer(std::string_view value, int& destination) {
  int parsed{};
  const auto result = std::from_chars(value.data(), value.data() + value.size(), parsed);
  if (result.ec != std::errc{} || result.ptr != value.data() + value.size() || parsed < 1)
    return false;
  destination = parsed;
  return true;
}
}  // namespace

int run_search_diagnostic(int argc, char** argv) {
  std::string fen;
  std::filesystem::path destination;
  std::string profile = "production";
  int depth = 6, max_ms = 30'000, nodes = 10'000'000, hash_mb = 4;
  for (int i = 1; i < argc; ++i) {
    const std::string_view option = argv[i];
    if (i + 1 >= argc) { std::cerr << "missing diagnostic option value\n"; return 2; }
    const std::string_view value = argv[++i];
    bool valid = true;
    if (option == "--fen") fen = value;
    else if (option == "--json") destination = std::string(value);
    else if (option == "--profile") profile = value;
    else if (option == "--depth") valid = positive_integer(value, depth);
    else if (option == "--max-ms") valid = positive_integer(value, max_ms);
    else if (option == "--nodes") valid = positive_integer(value, nodes);
    else if (option == "--hash-mb") valid = positive_integer(value, hash_mb);
    else valid = false;
    if (!valid) { std::cerr << "invalid diagnostic option " << option << '\n'; return 2; }
  }
  if (fen.empty() || destination.empty() || depth > 64 || max_ms > 120'000 ||
      hash_mb > 256 || (profile != "production" && profile != "full-width")) {
    std::cerr << "diagnostics require FEN, JSON path, depth 1..64, max-ms <=120000, hash <=256, and a valid profile\n";
    return 2;
  }
  std::string error;
  auto board = parse_fen(fen, &error);
  if (!board) { std::cerr << "invalid FEN: " << error << '\n'; return 2; }
  if (std::filesystem::exists(destination)) {
    std::cerr << "diagnostic output already exists; choose a new evidence path\n";
    return 2;
  }
  auto config = default_config();
  config.hash_mb = hash_mb;
  config.own_book = false;
  config.noise_millipawns = 0;
  std::atomic_bool stopped{false};
  Searcher searcher(config, stopped);
  SearchLimits limits;
  limits.depth = depth;
  limits.nodes = static_cast<std::uint64_t>(nodes);
  limits.deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(max_ms);
  limits.profile = profile == "full-width" ? SearchProfile::full_width : SearchProfile::production;
  limits.collect_diagnostics = true;
  std::vector<SearchResult> completed;
  const auto last = searcher.iterative(*board, limits, [&](const SearchResult& row) {
    completed.push_back(row);
  });
  const bool finished = last.depth >= depth || last.mate != 0 || board->legal_moves().empty();
  std::ostringstream out;
  out << "{\"schema\":1,\"version\":";
  string_json(out, version);
  out << ",\"fen\":";
  string_json(out, to_fen(*board));
  out << ",\"profile\":";
  string_json(out, profile);
  out << ",\"threads\":3,\"hash_mb\":" << hash_mb
      << ",\"requested_depth\":" << depth << ",\"max_ms\":" << max_ms
      << ",\"node_limit\":" << nodes << ",\"total_nodes_consumed\":" << searcher.nodes_searched()
      << ",\"completed\":" << (finished ? "true" : "false")
      << ",\"static_eval_cp\":" << searcher.static_evaluation(*board)
      << ",\"score_perspective\":\"root side except child TT scores\""
      << ",\"tt_snapshot\":\"owning private shard at end of root pass\""
      << ",\"full_width_scope\":\"disables razor, reverse/move futility, internal reduction, null move, ProbCut, LMP, LMR; retains alpha-beta, TT, extensions and normal quiescence\""
      << ",\"iterations\":[";
  for (std::size_t index = 0; index < completed.size(); ++index) {
    if (index) out << ',';
    result_json(out, completed[index], *board);
  }
  out << "],\"final_result\":";
  result_json(out, last, *board);
  out << "}\n";
  if (!destination.parent_path().empty()) std::filesystem::create_directories(destination.parent_path());
  std::ofstream output(destination, std::ios::binary);
  if (!output) { std::cerr << "cannot create diagnostic report\n"; return 2; }
  output << out.str();
  output.close();
  if (!output) { std::cerr << "diagnostic report write failed\n"; return 2; }
  std::cout << "diagnostic " << profile << " completed_depth " << last.depth
            << " requested_depth " << depth << " nodes " << searcher.nodes_searched()
            << " bestmove " << (last.pv.empty() ? "0000" : last.pv.front().uci()) << '\n';
  return finished ? 0 : 3;
}
}  // namespace eloi
