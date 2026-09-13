#include "eloi/policy_value.hpp"

#include <iomanip>
#include <iostream>
#include <string>

int main(int argc, char** argv) {
  std::filesystem::path model;
  std::string fen;
  for (int index = 1; index + 1 < argc; ++index) {
    const std::string_view option = argv[index];
    if (option == "--model") model = argv[++index];
    else if (option == "--fen") fen = argv[++index];
  }
  if (model.empty() || fen.empty()) return 2;
  eloi::PolicyValueNetwork network;
  std::string error;
  if (!network.load(model, &error)) {
    std::cerr << error << '\n';
    return 2;
  }
  const auto board = eloi::parse_fen(fen);
  if (!board || board->horde || board->chess960) return 2;
  const auto prediction = network.predict(*board, board->legal_moves());
  std::cout << std::setprecision(9) << "{\"value\":["
            << prediction.value_wdl[0] << ',' << prediction.value_wdl[1]
            << ',' << prediction.value_wdl[2] << "],\"policy\":{";
  for (std::size_t index = 0; index < prediction.policy.size(); ++index) {
    if (index) std::cout << ',';
    std::cout << '\"' << prediction.policy[index].first.uci() << "\":"
              << prediction.policy[index].second;
  }
  std::cout << "}}\n";
  return 0;
}
