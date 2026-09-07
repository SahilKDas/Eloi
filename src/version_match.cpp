#include "eloi/version_match.hpp"

#ifdef _WIN32

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <bcrypt.h>

#include <array>
#include <charconv>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <mutex>
#include <sstream>
#include <string_view>
#include <vector>

namespace eloi {
namespace {

std::vector<std::string> words(std::string_view line) {
  std::istringstream input{std::string(line)};
  std::vector<std::string> result;
  for (std::string word; input >> word;) result.push_back(std::move(word));
  return result;
}

template <typename Number>
bool parse_number(std::string_view value, Number& output) {
  const auto parsed = std::from_chars(
      value.data(), value.data() + value.size(), output);
  return parsed.ec == std::errc{} &&
         parsed.ptr == value.data() + value.size();
}

}  // namespace

std::string sha256_file(const std::filesystem::path& path) {
  BCRYPT_ALG_HANDLE algorithm = nullptr;
  BCRYPT_HASH_HANDLE hash = nullptr;
  DWORD object_size = 0;
  DWORD digest_size = 0;
  DWORD copied = 0;
  std::vector<unsigned char> object;
  std::vector<unsigned char> digest;
  auto close = [&] {
    if (hash) BCryptDestroyHash(hash);
    if (algorithm) BCryptCloseAlgorithmProvider(algorithm, 0);
  };
  if (BCryptOpenAlgorithmProvider(
          &algorithm, BCRYPT_SHA256_ALGORITHM, nullptr, 0) < 0 ||
      BCryptGetProperty(
          algorithm, BCRYPT_OBJECT_LENGTH,
          reinterpret_cast<PUCHAR>(&object_size), sizeof(object_size),
          &copied, 0) < 0 ||
      BCryptGetProperty(
          algorithm, BCRYPT_HASH_LENGTH,
          reinterpret_cast<PUCHAR>(&digest_size), sizeof(digest_size),
          &copied, 0) < 0) {
    close();
    return {};
  }
  object.resize(object_size);
  digest.resize(digest_size);
  if (BCryptCreateHash(algorithm, &hash, object.data(), object_size,
                       nullptr, 0, 0) < 0) {
    close();
    return {};
  }
  std::ifstream input(path, std::ios::binary);
  if (!input) {
    close();
    return {};
  }
  std::array<char, 64 * 1024> buffer{};
  while (input) {
    input.read(buffer.data(), static_cast<std::streamsize>(buffer.size()));
    const auto count = input.gcount();
    if (count > 0 &&
        BCryptHashData(
            hash, reinterpret_cast<PUCHAR>(buffer.data()),
            static_cast<ULONG>(count), 0) < 0) {
      close();
      return {};
    }
  }
  if (!input.eof() ||
      BCryptFinishHash(hash, digest.data(), digest_size, 0) < 0) {
    close();
    return {};
  }
  close();
  std::ostringstream output;
  output << std::uppercase << std::hex << std::setfill('0');
  for (unsigned char byte : digest)
    output << std::setw(2) << static_cast<unsigned>(byte);
  return output.str();
}

struct UciVersionEngine::Impl {
  explicit Impl(std::filesystem::path path)
      : executable(std::move(path)) {}

  ~Impl() { shutdown(); }

  bool write_line(std::string_view line) {
    std::scoped_lock lock(write_mutex);
    if (!input_write) return false;
    std::string command(line);
    command += '\n';
    DWORD written = 0;
    return WriteFile(input_write, command.data(),
                     static_cast<DWORD>(command.size()), &written, nullptr) &&
           written == command.size();
  }

  bool read_line(std::string& line) {
    line.clear();
    if (!output_read) return false;
    for (;;) {
      char character = 0;
      DWORD read = 0;
      if (!ReadFile(output_read, &character, 1, &read, nullptr) || !read)
        return false;
      if (character == '\n') return true;
      if (character != '\r') line += character;
    }
  }

  bool wait_for(std::string_view expected, std::string& error) {
    for (std::string line; read_line(line);) {
      if (line == expected) return true;
    }
    error = "UCI engine closed before " + std::string(expected);
    return false;
  }

  bool start(std::string& error) {
    if (process) return true;
    if (!std::filesystem::is_regular_file(executable)) {
      error = "Engine executable was not found: " + executable.string();
      return false;
    }

    SECURITY_ATTRIBUTES security{};
    security.nLength = sizeof(security);
    security.bInheritHandle = TRUE;
    HANDLE child_output_read = nullptr;
    HANDLE child_output_write = nullptr;
    HANDLE child_input_read = nullptr;
    HANDLE child_input_write = nullptr;
    if (!CreatePipe(&child_output_read, &child_output_write, &security, 0) ||
        !SetHandleInformation(child_output_read, HANDLE_FLAG_INHERIT, 0) ||
        !CreatePipe(&child_input_read, &child_input_write, &security, 0) ||
        !SetHandleInformation(child_input_write, HANDLE_FLAG_INHERIT, 0)) {
      if (child_output_read) CloseHandle(child_output_read);
      if (child_output_write) CloseHandle(child_output_write);
      if (child_input_read) CloseHandle(child_input_read);
      if (child_input_write) CloseHandle(child_input_write);
      error = "Could not create UCI communication pipes";
      return false;
    }

    STARTUPINFOW startup{};
    startup.cb = sizeof(startup);
    startup.dwFlags = STARTF_USESTDHANDLES;
    startup.hStdInput = child_input_read;
    startup.hStdOutput = child_output_write;
    startup.hStdError = child_output_write;
    PROCESS_INFORMATION created{};
    std::wstring command = L"\"" + executable.wstring() + L"\" --uci";
    const BOOL launched = CreateProcessW(
        executable.wstring().c_str(), command.data(), nullptr, nullptr, TRUE,
        CREATE_NO_WINDOW, nullptr, executable.parent_path().wstring().c_str(),
        &startup, &created);
    CloseHandle(child_input_read);
    CloseHandle(child_output_write);
    if (!launched) {
      CloseHandle(child_output_read);
      CloseHandle(child_input_write);
      error = "Could not launch " + executable.string();
      return false;
    }

    process = created.hProcess;
    process_thread = created.hThread;
    output_read = child_output_read;
    input_write = child_input_write;
    if (!write_line("uci") || !wait_for("uciok", error)) {
      shutdown();
      return false;
    }
    write_line("setoption name OwnBook value false");
    write_line("setoption name Hash value 32");
    if (!write_line("isready") || !wait_for("readyok", error)) {
      shutdown();
      return false;
    }
    new_game_pending = true;
    return true;
  }

  std::string position_command(const Board& board) const {
    std::string command = "position startpos";
    if (!board.history.empty()) {
      command += " moves";
      for (const Board::Snapshot& snapshot : board.history) {
        command += ' ';
        command += snapshot.move.uci();
      }
    }
    return command;
  }

  UciVersionResult choose_move(const Board& board, int depth) {
    UciVersionResult result;
    if (!start(result.error)) return result;
    if (new_game_pending) {
      if (!write_line("ucinewgame") || !write_line("isready") ||
          !wait_for("readyok", result.error))
        return result;
      new_game_pending = false;
    }
    if (!write_line(position_command(board)) ||
        !write_line("go depth " + std::to_string(depth))) {
      result.error = "Could not send the UCI search command";
      return result;
    }

    for (std::string line; read_line(line);) {
      const auto tokens = words(line);
      if (tokens.empty()) continue;
      if (tokens[0] == "info") {
        for (std::size_t i = 1; i + 1 < tokens.size(); ++i) {
          if (tokens[i] == "depth") parse_number(tokens[++i], result.depth);
          else if (tokens[i] == "nodes")
            parse_number(tokens[++i], result.nodes);
          else if (tokens[i] == "nps")
            parse_number(tokens[++i], result.nps);
          else if (tokens[i] == "time")
            parse_number(tokens[++i], result.elapsed_ms);
          else if (tokens[i] == "pv") {
            result.pv.assign(tokens.begin() +
                                 static_cast<std::ptrdiff_t>(i + 1),
                             tokens.end());
            break;
          }
          else if (tokens[i] == "score" && i + 2 < tokens.size()) {
            const std::string kind = tokens[++i];
            if (kind == "cp") parse_number(tokens[++i], result.score_cp);
            else if (kind == "mate") {
              int mate = 0;
              if (parse_number(tokens[++i], mate))
                result.score_cp = mate > 0 ? 30'000 : -30'000;
            }
          }
        }
      } else if (tokens[0] == "bestmove" && tokens.size() >= 2) {
        result.bestmove = tokens[1];
        return result;
      }
    }
    result.error = "UCI engine stopped without returning a move";
    return result;
  }

  void request_stop() { write_line("stop"); }

  void shutdown() {
    if (!process) return;
    write_line("quit");
    if (WaitForSingleObject(process, 1000) == WAIT_TIMEOUT) {
      TerminateProcess(process, 1);
      WaitForSingleObject(process, 1000);
    }
    if (input_write) CloseHandle(input_write);
    if (output_read) CloseHandle(output_read);
    if (process_thread) CloseHandle(process_thread);
    CloseHandle(process);
    input_write = nullptr;
    output_read = nullptr;
    process_thread = nullptr;
    process = nullptr;
  }

  std::filesystem::path executable;
  HANDLE process{};
  HANDLE process_thread{};
  HANDLE input_write{};
  HANDLE output_read{};
  std::mutex write_mutex;
  bool new_game_pending{true};
};

UciVersionEngine::UciVersionEngine(std::filesystem::path executable)
    : impl_(std::make_unique<Impl>(std::move(executable))) {}
UciVersionEngine::~UciVersionEngine() = default;

UciVersionResult UciVersionEngine::choose_move(const Board& board, int depth) {
  return impl_->choose_move(board, depth);
}

void UciVersionEngine::begin_new_game() { impl_->new_game_pending = true; }
void UciVersionEngine::request_stop() { impl_->request_stop(); }
const std::filesystem::path& UciVersionEngine::executable() const {
  return impl_->executable;
}

int run_version_match_smoke(const std::filesystem::path& current,
                            const std::filesystem::path& previous,
                            int depth, int plies) {
  auto board = parse_fen(initial_fen);
  if (!board) return 2;
  UciVersionEngine current_engine(current);
  UciVersionEngine previous_engine(previous);
  current_engine.begin_new_game();
  previous_engine.begin_new_game();
  for (int ply = 0; ply < plies && !board->legal_moves().empty(); ++ply) {
    UciVersionEngine& engine = board->turn == Color::white
        ? current_engine : previous_engine;
    const UciVersionResult result = engine.choose_move(*board, depth);
    if (!result.error.empty() || result.bestmove.empty() ||
        !board->push_uci(result.bestmove)) {
      std::cerr << "version match smoke failed at ply " << (ply + 1)
                << ": " << (result.error.empty()
                                  ? "illegal or missing bestmove"
                                  : result.error)
                << '\n';
      return 2;
    }
    std::cout << (board->turn == Color::black ? "current" : "previous")
              << " " << result.bestmove << " depth " << result.depth
              << " nodes " << result.nodes << '\n';
  }
  std::cout << "version match smoke ok\n";
  return 0;
}

}  // namespace eloi

#else

namespace eloi {
struct UciVersionEngine::Impl {
  explicit Impl(std::filesystem::path path) : executable(std::move(path)) {}
  std::filesystem::path executable;
};
UciVersionEngine::UciVersionEngine(std::filesystem::path executable)
    : impl_(std::make_unique<Impl>(std::move(executable))) {}
UciVersionEngine::~UciVersionEngine() = default;
UciVersionResult UciVersionEngine::choose_move(const Board&, int) {
  return {.error = "Version matches are currently available on Windows"};
}
void UciVersionEngine::begin_new_game() {}
void UciVersionEngine::request_stop() {}
const std::filesystem::path& UciVersionEngine::executable() const {
  return impl_->executable;
}
int run_version_match_smoke(const std::filesystem::path&,
                            const std::filesystem::path&, int, int) {
  return 2;
}
std::string sha256_file(const std::filesystem::path&) { return {}; }
}  // namespace eloi

#endif
