#include "eloi/brain.hpp"

#include <algorithm>
#include <charconv>
#include <chrono>
#include <cstdlib>
#include <iostream>
#include <mutex>
#include <optional>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#endif

namespace eloi {
namespace {

std::vector<std::string> split(std::string_view text, char delimiter) {
  std::vector<std::string> rows;
  std::size_t first = 0;
  while (first <= text.size()) {
    const std::size_t next = text.find(delimiter, first);
    rows.emplace_back(text.substr(
        first, next == std::string_view::npos ? text.size() - first
                                              : next - first));
    if (next == std::string_view::npos) break;
    first = next + 1;
  }
  return rows;
}

template <typename Integer>
bool integer(std::string_view text, Integer& value) {
  const auto [end, error] =
      std::from_chars(text.data(), text.data() + text.size(), value);
  return error == std::errc{} && end == text.data() + text.size();
}

std::pair<std::string, std::string> board_wire(Board board) {
  std::vector<std::string> moves;
  while (!board.history.empty()) {
    const auto move = board.last_move();
    if (!move || !board.pop()) return {};
    moves.push_back(move->uci());
  }
  std::ranges::reverse(moves);
  std::ostringstream history;
  for (std::size_t index = 0; index < moves.size(); ++index) {
    if (index) history << ',';
    history << moves[index];
  }
  return {to_fen(board), history.str()};
}

std::optional<Board> board_from_wire(
    std::string_view fen, std::string_view history) {
  auto board = parse_fen(fen);
  if (!board) return std::nullopt;
  if (!history.empty())
    for (const auto& move : split(history, ','))
      if (move.empty() || !board->push_uci(move)) return std::nullopt;
  return board;
}

std::string pv_wire(Board board, const std::vector<Move>& pv) {
  std::ostringstream output;
  for (std::size_t index = 0; index < pv.size(); ++index) {
    if (index) output << ',';
    output << pv[index].uci();
    if (!board.push(pv[index])) break;
  }
  return output.str();
}

std::vector<Move> pv_from_wire(Board board, std::string_view encoded) {
  std::vector<Move> pv;
  if (encoded.empty()) return pv;
  for (const auto& token : split(encoded, ',')) {
    const MoveList legal = board.legal_moves();
    const auto found = std::ranges::find_if(legal, [&](const Move& move) {
      return move.uci() == token;
    });
    if (found == legal.end() || !board.push(*found)) return {};
    pv.push_back(*found);
  }
  return pv;
}

int worker_hash_mb(int argc, char** argv) {
  for (int index = 1; index + 1 < argc; ++index) {
    if (std::string_view(argv[index]) != "--caissa-worker-hash") continue;
    int value = 0;
    if (integer(std::string_view(argv[index + 1]), value))
      return std::clamp(value, 0, 16'384);
  }
  return 16;
}

std::filesystem::path worker_network(int argc, char** argv) {
  for (int index = 1; index + 1 < argc; ++index)
    if (std::string_view(argv[index]) == "--caissa-network")
      return std::filesystem::absolute(argv[index + 1]);
  return {};
}

#ifdef _WIN32
std::wstring quoted(const std::filesystem::path& path) {
  std::wstring result{L"\""};
  for (const wchar_t character : path.wstring()) {
    if (character == L'"') result += L'\\';
    result += character;
  }
  result += L'"';
  return result;
}
#endif

}  // namespace

bool caissa_worker_requested(int argc, char** argv) noexcept {
  for (int index = 1; index < argc; ++index)
    if (std::string_view(argv[index]) == "--internal-caissa-worker")
      return true;
  return false;
}

int run_caissa_worker(int argc, char** argv) {
  std::atomic_bool stopped{false};
  const int hash_mb = worker_hash_mb(argc, argv);
  // The donor loader emits UCI-facing startup telemetry on std::cout. Worker
  // stdout is a private framed stream, so capture that banner rather than
  // allowing it to masquerade as a result frame.
  std::ostringstream startup_telemetry;
  std::streambuf* protocol_output = std::cout.rdbuf(
      startup_telemetry.rdbuf());
  CaissaBrain brain(worker_network(argc, argv), stopped,
                    static_cast<std::size_t>(hash_mb) * 1024u * 1024u);
  std::cout.rdbuf(protocol_output);
  if (!brain.available()) return 70;
  const bool crash_test =
      std::getenv("ELOI_CAISSA_WORKER_CRASH_TEST") != nullptr;
  for (std::string line; std::getline(std::cin, line);) {
    if (line == "QUIT") return 0;
    const auto fields = split(line, '\t');
    if (fields.size() != 10 || fields[0] != "SEARCH") return 71;
    if (crash_test) {
#ifdef _WIN32
      TerminateProcess(GetCurrentProcess(), 86);
#else
      std::_Exit(86);
#endif
    }
    SearchLimits limits;
    long long deadline_ms = -1;
    if (!integer(fields[1], limits.depth) ||
        !integer(fields[2], limits.nodes) ||
        !integer(fields[3], limits.remaining_ms) ||
        !integer(fields[4], limits.increment_ms) ||
        !integer(fields[5], limits.moves_to_go) ||
        !integer(fields[6], limits.move_overhead_ms) ||
        !integer(fields[7], deadline_ms)) return 72;
    auto board = board_from_wire(fields[8], fields[9]);
    if (!board) return 73;
    if (deadline_ms >= 0)
      limits.deadline = std::chrono::steady_clock::now() +
          std::chrono::milliseconds(deadline_ms);
    const BrainResponse response = brain.search(*board, limits);
    std::cout << "RESULT\t" << static_cast<int>(response.status)
              << '\t' << response.search.score_cp
              << '\t' << response.search.mate
              << '\t' << response.search.depth
              << '\t' << response.search.nodes
              << '\t' << response.search.qnodes
              << '\t' << response.search.elapsed.count()
              << '\t' << pv_wire(*board, response.search.pv)
              << '\n' << std::flush;
  }
  return 0;
}

struct IsolatedCaissaBrain::Impl {
  Impl(std::filesystem::path executable_source,
       std::filesystem::path network_source,
       std::atomic_bool& stop_flag, std::size_t bytes)
      : executable(std::move(executable_source)),
        network(std::move(network_source)),
        stopped(stop_flag),
        hash_mb(static_cast<int>(bytes / (1024u * 1024u))) {}

  std::filesystem::path executable;
  std::filesystem::path network;
  std::atomic_bool& stopped;
  int hash_mb;
  mutable std::mutex mutex;
  bool permanently_unavailable{false};
  std::string failure;
#ifdef _WIN32
  PROCESS_INFORMATION process{};
  HANDLE input{nullptr};
  HANDLE output{nullptr};

  void close_worker(bool terminate) noexcept {
    if (input) {
      if (!terminate) {
        const char quit[] = "QUIT\n";
        DWORD written = 0;
        WriteFile(input, quit, sizeof(quit) - 1, &written, nullptr);
      }
      CloseHandle(input);
      input = nullptr;
    }
    if (process.hProcess) {
      if (WaitForSingleObject(process.hProcess, terminate ? 0 : 500) !=
          WAIT_OBJECT_0)
        TerminateProcess(process.hProcess, 87);
      WaitForSingleObject(process.hProcess, 500);
      CloseHandle(process.hThread);
      CloseHandle(process.hProcess);
      process = {};
    }
    if (output) {
      CloseHandle(output);
      output = nullptr;
    }
  }

  bool start_worker() {
    if (process.hProcess) return true;
    if (executable.empty() || !std::filesystem::is_regular_file(executable)) {
      permanently_unavailable = true;
      failure = "Caissa worker executable is absent";
      return false;
    }
    SECURITY_ATTRIBUTES attributes{
        sizeof(SECURITY_ATTRIBUTES), nullptr, TRUE};
    HANDLE child_input = nullptr;
    HANDLE child_output = nullptr;
    if (!CreatePipe(&child_input, &input, &attributes, 0) ||
        !CreatePipe(&output, &child_output, &attributes, 0)) {
      if (child_input) CloseHandle(child_input);
      if (child_output) CloseHandle(child_output);
      close_worker(true);
      failure = "Caissa worker pipe creation failed";
      return false;
    }
    SetHandleInformation(input, HANDLE_FLAG_INHERIT, 0);
    SetHandleInformation(output, HANDLE_FLAG_INHERIT, 0);
    STARTUPINFOW startup{};
    startup.cb = sizeof(startup);
    startup.dwFlags = STARTF_USESTDHANDLES | STARTF_USESHOWWINDOW;
    startup.wShowWindow = SW_HIDE;
    startup.hStdInput = child_input;
    startup.hStdOutput = child_output;
    startup.hStdError = child_output;
    std::wstring command = quoted(executable) +
        L" --internal-caissa-worker --caissa-worker-hash " +
        std::to_wstring(hash_mb);
    if (!network.empty())
      command += L" --caissa-network " + quoted(network);
    std::vector<wchar_t> mutable_command(command.begin(), command.end());
    mutable_command.push_back(L'\0');
    const BOOL created = CreateProcessW(
        executable.c_str(), mutable_command.data(), nullptr, nullptr, TRUE,
        CREATE_NO_WINDOW | IDLE_PRIORITY_CLASS, nullptr,
        executable.parent_path().c_str(), &startup, &process);
    CloseHandle(child_input);
    CloseHandle(child_output);
    if (!created) {
      close_worker(true);
      failure = "Caissa worker process creation failed";
      return false;
    }
    return true;
  }

  bool write_line(const std::string& line) {
    DWORD written = 0;
    return WriteFile(input, line.data(), static_cast<DWORD>(line.size()),
                     &written, nullptr) &&
           written == static_cast<DWORD>(line.size());
  }

  std::optional<std::string> read_line(
      std::optional<std::chrono::steady_clock::time_point> deadline) {
    std::string line;
    for (;;) {
      if (stopped) {
        failure = "Caissa worker stopped";
        close_worker(true);
        return std::nullopt;
      }
      if (deadline && std::chrono::steady_clock::now() >= *deadline) {
        failure = "Caissa worker exceeded its deadline";
        close_worker(true);
        return std::nullopt;
      }
      DWORD available = 0;
      if (!PeekNamedPipe(output, nullptr, 0, nullptr, &available, nullptr)) {
        failure = "Caissa worker pipe closed after crash or exit";
        close_worker(true);
        return std::nullopt;
      }
      if (available) {
        char character = 0;
        DWORD read = 0;
        if (!ReadFile(output, &character, 1, &read, nullptr) || read != 1) {
          failure = "Caissa worker response read failed";
          close_worker(true);
          return std::nullopt;
        }
        if (character == '\n') return line;
        if (character != '\r') line.push_back(character);
        if (line.size() > 1'000'000) {
          failure = "Caissa worker response exceeded protocol limit";
          close_worker(true);
          return std::nullopt;
        }
      } else {
        if (WaitForSingleObject(process.hProcess, 0) == WAIT_OBJECT_0) {
          failure = "Caissa worker exited before returning a result";
          close_worker(true);
          return std::nullopt;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
      }
    }
  }
#endif
};

IsolatedCaissaBrain::IsolatedCaissaBrain(
    std::filesystem::path executable_path,
    std::filesystem::path network_path,
    std::atomic_bool& stopped, std::size_t hash_bytes)
    : impl_(std::make_unique<Impl>(
          std::move(executable_path), std::move(network_path),
          stopped, hash_bytes)) {
#ifndef _WIN32
  impl_->permanently_unavailable = true;
  impl_->failure = "isolated Caissa worker is Windows-only";
#endif
}

IsolatedCaissaBrain::~IsolatedCaissaBrain() {
#ifdef _WIN32
  std::scoped_lock lock(impl_->mutex);
  impl_->close_worker(false);
#endif
}

BrainIdentity IsolatedCaissaBrain::identity() const noexcept {
  return BrainIdentity::caissa_1_26;
}

bool IsolatedCaissaBrain::available() const noexcept {
  return !impl_->permanently_unavailable &&
         !impl_->executable.empty() &&
         std::filesystem::is_regular_file(impl_->executable);
}

BrainResponse IsolatedCaissaBrain::search(
    Board board, SearchLimits limits, const BrainInfoCallback& info) {
  BrainResponse response;
  response.requested = response.selected = BrainIdentity::caissa_1_26;
#ifndef _WIN32
  response.status = BrainStatus::unavailable;
  response.detail = impl_->failure;
#else
  std::scoped_lock lock(impl_->mutex);
  if (!impl_->start_worker()) {
    response.status = impl_->permanently_unavailable
        ? BrainStatus::unavailable : BrainStatus::failed;
    response.detail = impl_->failure;
    if (info) info(response);
    return response;
  }
  const auto [base_fen, history] = board_wire(board);
  if (base_fen.empty()) {
    response.status = BrainStatus::failed;
    response.detail = "Caissa worker could not serialize Eloi history";
    if (info) info(response);
    return response;
  }
  long long deadline_ms = -1;
  std::optional<std::chrono::steady_clock::time_point> watchdog =
      std::chrono::steady_clock::now() + std::chrono::milliseconds(2500);
  if (limits.deadline) {
    deadline_ms = std::max<long long>(
        0, std::chrono::duration_cast<std::chrono::milliseconds>(
               *limits.deadline - std::chrono::steady_clock::now()).count());
    watchdog = *limits.deadline + std::chrono::milliseconds(100);
  }
  std::ostringstream request;
  request << "SEARCH\t" << limits.depth << '\t' << limits.nodes << '\t'
          << limits.remaining_ms << '\t' << limits.increment_ms << '\t'
          << limits.moves_to_go << '\t' << limits.move_overhead_ms << '\t'
          << deadline_ms << '\t' << base_fen << '\t' << history << '\n';
  if (!impl_->write_line(request.str())) {
    impl_->failure = "Caissa worker request write failed";
    impl_->close_worker(true);
    response.status = BrainStatus::failed;
    response.detail = impl_->failure;
    if (info) info(response);
    return response;
  }
  const auto line = impl_->read_line(watchdog);
  if (!line) {
    response.status =
        impl_->stopped ? BrainStatus::stopped : BrainStatus::failed;
    response.detail = impl_->failure;
    if (info) info(response);
    return response;
  }
  const auto fields = split(*line, '\t');
  int status = 0;
  long long elapsed = 0;
  if (fields.size() != 9 || fields[0] != "RESULT" ||
      !integer(fields[1], status) ||
      status < static_cast<int>(BrainStatus::complete) ||
      status > static_cast<int>(BrainStatus::failed) ||
      !integer(fields[2], response.search.score_cp) ||
      !integer(fields[3], response.search.mate) ||
      !integer(fields[4], response.search.depth) ||
      !integer(fields[5], response.search.nodes) ||
      !integer(fields[6], response.search.qnodes) ||
      !integer(fields[7], elapsed)) {
    impl_->failure = "Caissa worker returned a malformed response";
    impl_->close_worker(true);
    response.status = BrainStatus::failed;
    response.detail = impl_->failure;
    if (info) info(response);
    return response;
  }
  response.status = static_cast<BrainStatus>(status);
  response.search.elapsed = std::chrono::milliseconds(elapsed);
  response.search.pv = pv_from_wire(board, fields[8]);
  if (!fields[8].empty() && response.search.pv.empty()) {
    response.status = BrainStatus::invalid_move;
    response.detail = "Caissa worker PV failed Eloi legal translation";
  } else {
    response.detail = "Caissa result returned through isolated worker";
    if (!response.search.pv.empty())
      response.lines.push_back(
          {response.search.pv, response.search.score_cp,
           response.search.mate});
  }
#endif
  if (info) info(response);
  return response;
}

void IsolatedCaissaBrain::release_hash() {
#ifdef _WIN32
  std::scoped_lock lock(impl_->mutex);
  impl_->close_worker(false);
#endif
}

}  // namespace eloi
