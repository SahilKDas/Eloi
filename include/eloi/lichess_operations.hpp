#pragma once

#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <filesystem>
#include <functional>
#include <mutex>
#include <string>
#include <string_view>
#include <vector>

namespace eloi {

enum class BridgeState {
  stopped, connecting, connected, playing, backing_off, fatal, stopping
};

std::string_view bridge_state_name(BridgeState state);
int bridge_backoff_seconds(int retry_count);
bool bridge_http_retryable(int status);
bool bridge_http_fatal(int status);
std::string redact_bridge_text(std::string_view text);

struct BridgeEvent {
  std::chrono::system_clock::time_point at;
  BridgeState state{BridgeState::stopped};
  std::string message;
  bool error{};
};

struct BridgeSnapshot {
  BridgeState state{BridgeState::stopped};
  std::string version;
  std::string executable_sha256;
  std::string account;
  std::string enabled_variants;
  std::string last_error;
  std::string active_game_id;
  std::string opponent;
  std::string color;
  std::string variant;
  std::string brain_route;
  std::string network_sha256;
  std::string latest_move;
  std::string pv;
  std::string stop_reason;
  std::string last_result;
  int last_http_status{};
  int reconnect_attempts{};
  int next_retry_seconds{};
  int ply{};
  int depth{};
  int score_cp{};
  std::uint64_t nodes{};
  std::int64_t elapsed_ms{};
  std::int64_t white_time_ms{-1};
  std::int64_t black_time_ms{-1};
  std::uint64_t accepted{};
  std::uint64_t declined{};
  std::uint64_t completed_wins{};
  std::uint64_t completed_draws{};
  std::uint64_t completed_losses{};
  std::uint64_t caissa_failures{};
  std::uint64_t eloi_fallbacks{};
  std::uint64_t emergency_moves{};
  std::uint64_t protocol_incidents{};
  bool accepting{true};
  bool active_game{};
  bool stop_requested{};
  std::chrono::system_clock::time_point started_at;
  std::vector<BridgeEvent> events;
};

class BridgeEventSink {
 public:
  virtual ~BridgeEventSink() = default;
  virtual void publish(BridgeEvent event) = 0;
};

// Internal seam used by the bridge supervisor and offline transport tests.
// Implementations must make cancel() safe from a different thread.
class LichessTransport {
 public:
  virtual ~LichessTransport() = default;
  virtual bool valid() const = 0;
  virtual int last_status() const = 0;
  virtual int retry_after_seconds() const = 0;
  virtual void cancel() = 0;
  virtual bool get(std::wstring_view path, std::string& output) = 0;
  virtual bool post(std::wstring_view path, std::string_view body = {}) = 0;
  virtual bool stream(
      std::wstring_view path,
      const std::function<bool(std::string_view)>& handler) = 0;
};

class BridgeController final : public BridgeEventSink {
 public:
  BridgeController(std::filesystem::path executable,
                   std::filesystem::path config);
  ~BridgeController();

  BridgeController(const BridgeController&) = delete;
  BridgeController& operator=(const BridgeController&) = delete;

  void publish(BridgeEvent event) override;
  void transition(BridgeState state, std::string message = {}, bool error = false);
  void set_account(std::string account);
  void set_configuration(std::string enabled_variants);
  void set_http_status(int status);
  void set_retry(int attempts, int seconds);
  void begin_game(std::string id, std::string variant,
                  std::string opponent = {}, std::string color = {});
  void update_game_clock(int ply, std::int64_t white_ms, std::int64_t black_ms);
  void record_search(std::string route, std::string network,
                     std::string move, int depth, int score_cp,
                     std::uint64_t nodes, std::int64_t elapsed_ms,
                     std::string pv, std::string stop_reason);
  void end_game(std::string result);
  void record_challenge(bool accepted);
  void record_caissa_failure(bool fallback, bool emergency);
  void protocol_incident(std::string message);

  BridgeSnapshot snapshot() const;
  const std::filesystem::path& config_path() const { return config_path_; }
  const std::filesystem::path& log_directory() const { return log_directory_; }

  bool accepting() const;
  void toggle_accepting();
  bool stop_requested() const;
  bool reconnect_requested() const;
  void clear_reconnect();
  void request_reconnect();
  void request_stop();
  void set_cancel_callback(std::function<void()> callback);
  bool wait_backoff(int seconds);

 private:
  void persist_event_locked(const BridgeEvent& event);
  void write_snapshot_locked() const;
  void rotate_logs();

  mutable std::mutex mutex_;
  std::condition_variable condition_;
  BridgeSnapshot snapshot_;
  std::filesystem::path executable_;
  std::filesystem::path config_path_;
  std::filesystem::path log_directory_;
  std::filesystem::path status_path_;
  std::filesystem::path log_path_;
  std::function<void()> cancel_callback_;
  bool reconnect_requested_{};
};

int run_lichess_operations_center(int argc, char** argv);

}  // namespace eloi
