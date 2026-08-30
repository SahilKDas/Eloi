#include "eloi/chess.hpp"
#include "eloi/version_match.hpp"

#ifdef _WIN32

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <windowsx.h>
#include <commdlg.h>

#include "include/core/SkCanvas.h"
#include "include/core/SkColor.h"
#include "include/core/SkData.h"
#include "include/core/SkFont.h"
#include "include/core/SkGraphics.h"
#include "include/core/SkImage.h"
#include "include/core/SkImageInfo.h"
#include "include/core/SkPaint.h"
#include "include/core/SkPixmap.h"
#include "include/core/SkSamplingOptions.h"
#include "include/core/SkStream.h"
#include "include/core/SkSurface.h"
#ifndef ELOI_EXTERNAL_ASSETS
#include "resource.h"
#endif

#include <algorithm>
#include <array>
#include <atomic>
#include <filesystem>
#include <fstream>
#include <format>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <thread>
#include <vector>

namespace eloi {
namespace {

constexpr UINT engine_finished_message = WM_APP + 26;
constexpr UINT animation_timer_id = 27;
constexpr auto move_animation_duration = std::chrono::milliseconds(230);
constexpr SkColor ink = SkColorSetRGB(235, 239, 248);
constexpr SkColor muted = SkColorSetRGB(144, 153, 176);
constexpr SkColor accent = SkColorSetRGB(121, 101, 255);
constexpr SkColor mint = SkColorSetRGB(62, 211, 166);

struct UiRect {
  float left{};
  float top{};
  float right{};
  float bottom{};

  bool contains(float x, float y) const {
    return x >= left && x <= right && y >= top && y <= bottom;
  }
  SkRect sk() const { return SkRect::MakeLTRB(left, top, right, bottom); }
};

struct Layout {
  float board_left{};
  float board_top{};
  float board_size{};
  float square{};
  float panel_left{};
  UiRect depth_minus;
  UiRect depth_plus;
  UiRect new_game;
  UiRect undo;
  UiRect flip;
  UiRect side;
  UiRect version_match;
};

Layout make_layout(int width, int height) {
  Layout layout;
  layout.board_left = 42.0f;
  layout.board_top = 112.0f;
  layout.board_size = std::clamp(
      std::min(static_cast<float>(height) - 154.0f,
               static_cast<float>(width) - 430.0f),
      400.0f, 696.0f);
  layout.square = layout.board_size / 8.0f;
  layout.panel_left = layout.board_left + layout.board_size + 38.0f;
  const float right = static_cast<float>(width) - 38.0f;
  layout.depth_minus = {layout.panel_left, 291, layout.panel_left + 46, 337};
  layout.depth_plus = {right - 46, 291, right, 337};
  layout.new_game = {layout.panel_left, 478, right, 526};
  layout.undo = {layout.panel_left, 538, right, 586};
  layout.flip = {layout.panel_left, 598, right, 646};
  layout.side = {layout.panel_left, 658, right, 706};
  layout.version_match = {layout.panel_left, 718, right, 766};
  return layout;
}

void text(SkCanvas& canvas, std::string_view value, float x, float y, float size,
          SkColor color = ink, bool bold = false) {
  SkPaint paint;
  paint.setAntiAlias(true);
  paint.setColor(color);
  SkFont font(nullptr, size);
  font.setEmbolden(bold);
  canvas.drawSimpleText(value.data(), value.size(), SkTextEncoding::kUTF8,
                        x, y, font, paint);
}

void round_rect(SkCanvas& canvas, const UiRect& rect, float radius, SkColor color) {
  SkPaint paint;
  paint.setAntiAlias(true);
  paint.setColor(color);
  canvas.drawRoundRect(rect.sk(), radius, radius, paint);
}

void button(SkCanvas& canvas, const UiRect& rect, std::string_view label,
            SkColor fill = SkColorSetRGB(35, 40, 57)) {
  round_rect(canvas, {rect.left + 2, rect.top + 4, rect.right + 2, rect.bottom + 4},
             13, SkColorSetARGB(80, 0, 0, 0));
  round_rect(canvas, rect, 13, fill);
  const float label_width = static_cast<float>(label.size()) * 7.1f;
  text(canvas, label, (rect.left + rect.right - label_width) / 2,
       rect.top + 30, 15, ink, true);
}

int piece_slot(std::int8_t cell) {
  if (cell == 0) return -1;
  const int color_offset = cell < 0 ? 6 : 0;
  switch (std::abs(static_cast<int>(cell))) {
    case static_cast<int>(Piece::bishop): return color_offset + 0;
    case static_cast<int>(Piece::king): return color_offset + 1;
    case static_cast<int>(Piece::knight): return color_offset + 2;
    case static_cast<int>(Piece::pawn): return color_offset + 3;
    case static_cast<int>(Piece::queen): return color_offset + 4;
    case static_cast<int>(Piece::rook): return color_offset + 5;
    default: return -1;
  }
}

struct App {
  enum class AnimationAfter { none, start_engine, finish_engine };
  struct MoveAnimation {
    bool active{false};
    Move move{};
    std::int8_t moving_cell{};
    std::int8_t rook_cell{};
    int rook_from{-1};
    int rook_to{-1};
    std::chrono::steady_clock::time_point started{};
    AnimationAfter after{AnimationAfter::none};
  } animation;
  struct PromotionPicker {
    bool active{false};
    std::vector<Move> moves;
  } promotion;
  HWND window{};
  Board board{*parse_fen(initial_fen)};
  Color human{Color::white};
  Color current_version_side{Color::white};
  bool flipped{false};
  bool version_match{false};
  int depth{7};
  int selected{-1};
  std::atomic_bool stop{false};
  std::atomic_bool thinking{false};
  std::atomic_uint64_t search_generation{0};
  std::thread worker;
  std::unique_ptr<UciVersionEngine> current_version_engine;
  std::unique_ptr<UciVersionEngine> previous_version_engine;
  std::filesystem::path previous_version_path;
  std::string previous_version_label;
  std::mutex result_mutex;
  std::optional<SearchResult> pending_result;
  std::string pending_error;
  SearchResult last_result;
  std::string last_engine{"Eloi"};
  std::string status{"Your move"};
  std::array<sk_sp<SkImage>, 12> pieces;

  ~App() {
    stop.store(true);
    if (current_version_engine) current_version_engine->request_stop();
    if (previous_version_engine) previous_version_engine->request_stop();
    if (worker.joinable()) worker.join();
  }
};

void start_engine(App& app);

void load_pieces(App& app) {
#ifdef ELOI_EXTERNAL_ASSETS
  constexpr std::array names{
      "wB.png", "wK.png", "wN.png", "wP.png", "wQ.png", "wR.png",
      "bB.png", "bK.png", "bN.png", "bP.png", "bQ.png", "bR.png"};
  std::wstring executable(32768, L'\0');
  const DWORD length = GetModuleFileNameW(
      nullptr, executable.data(), static_cast<DWORD>(executable.size()));
  executable.resize(length);
  const auto asset_root = std::filesystem::path(executable).parent_path() /
      "assets" / "chess_maestro_bw";
  for (std::size_t i = 0; i < names.size(); ++i) {
    const auto path = asset_root / names[i];
    app.pieces[i] = SkImage::MakeFromEncoded(
        SkData::MakeFromFileName(path.string().c_str()));
  }
#else
  constexpr std::array ids{
      IDR_PIECE_WB, IDR_PIECE_WK, IDR_PIECE_WN, IDR_PIECE_WP,
      IDR_PIECE_WQ, IDR_PIECE_WR, IDR_PIECE_BB, IDR_PIECE_BK,
      IDR_PIECE_BN, IDR_PIECE_BP, IDR_PIECE_BQ, IDR_PIECE_BR};
  for (std::size_t i = 0; i < ids.size(); ++i) {
    const HRSRC resource = FindResourceW(
        nullptr, MAKEINTRESOURCEW(ids[i]), L"PNG");
    if (!resource) continue;
    const HGLOBAL loaded = LoadResource(nullptr, resource);
    const DWORD size = SizeofResource(nullptr, resource);
    const void* bytes = LockResource(loaded);
    if (!bytes || !size) continue;
    app.pieces[i] = SkImage::MakeFromEncoded(
        SkData::MakeWithCopy(bytes, static_cast<std::size_t>(size)));
  }
#endif
}

std::filesystem::path running_executable() {
  std::wstring path(32768, L'\0');
  const DWORD length = GetModuleFileNameW(
      nullptr, path.data(), static_cast<DWORD>(path.size()));
  path.resize(length);
  return std::filesystem::path(path);
}

std::optional<std::filesystem::path> choose_previous_executable(HWND owner) {
  std::array<wchar_t, 32768> selected{};
  const std::wstring initial = running_executable().parent_path().wstring();
  OPENFILENAMEW dialog{};
  dialog.lStructSize = sizeof(dialog);
  dialog.hwndOwner = owner;
  dialog.lpstrFilter = L"Eloi executables (*.exe)\0*.exe\0All files\0*.*\0\0";
  dialog.lpstrFile = selected.data();
  dialog.nMaxFile = static_cast<DWORD>(selected.size());
  dialog.lpstrInitialDir = initial.c_str();
  dialog.lpstrTitle = L"Choose the earlier Eloi executable";
  dialog.Flags = OFN_FILEMUSTEXIST | OFN_PATHMUSTEXIST |
                 OFN_HIDEREADONLY | OFN_NOCHANGEDIR;
  if (!GetOpenFileNameW(&dialog)) return std::nullopt;
  return std::filesystem::path(selected.data());
}

bool write_bmp(const std::filesystem::path& path, const SkPixmap& pixels) {
  BITMAPFILEHEADER file_header{};
  BITMAPINFOHEADER image_header{};
  const auto pixel_bytes = static_cast<DWORD>(pixels.rowBytes() * pixels.height());
  file_header.bfType = 0x4d42;
  file_header.bfOffBits = sizeof(file_header) + sizeof(image_header);
  file_header.bfSize = file_header.bfOffBits + pixel_bytes;
  image_header.biSize = sizeof(image_header);
  image_header.biWidth = pixels.width();
  image_header.biHeight = -pixels.height();
  image_header.biPlanes = 1;
  image_header.biBitCount = 32;
  image_header.biCompression = BI_RGB;
  image_header.biSizeImage = pixel_bytes;
  std::ofstream output(path, std::ios::binary);
  output.write(reinterpret_cast<const char*>(&file_header), sizeof(file_header));
  output.write(reinterpret_cast<const char*>(&image_header), sizeof(image_header));
  output.write(static_cast<const char*>(pixels.addr()), pixel_bytes);
  return output.good();
}

bool game_over(App& app) {
  const auto moves = app.board.legal_moves();
  if (moves.empty()) {
    if (!app.board.position.in_check(app.board.turn)) {
      app.status = "Draw by stalemate";
    } else if (app.version_match) {
      const Color winner = opponent(app.board.turn);
      app.status = winner == app.current_version_side
          ? "Checkmate — current Eloi wins"
          : "Checkmate — previous Eloi wins";
    } else {
      app.status = app.board.turn == app.human
          ? "Checkmate — Eloi wins" : "Checkmate — you win";
    }
    return true;
  }
  if (app.board.is_threefold_repetition()) {
    app.status = "Draw by threefold repetition";
    return true;
  }
  if (app.board.is_fifty_move_draw()) {
    app.status = "Draw by fifty-move rule";
    return true;
  }
  if (app.board.position.insufficient_material()) {
    app.status = "Draw by insufficient material";
    return true;
  }
  return false;
}

void cancel_animation(App& app) {
  if (app.window) KillTimer(app.window, animation_timer_id);
  app.animation = {};
  app.promotion = {};
}

void begin_animation(App& app, const Move& move, std::int8_t moving_cell,
                     App::AnimationAfter after) {
  app.animation = {};
  app.animation.active = true;
  app.animation.move = move;
  app.animation.moving_cell = moving_cell;
  app.animation.started = std::chrono::steady_clock::now();
  app.animation.after = after;
  if (move.is_castle()) {
    const int rank = rank_of(move.from);
    app.animation.rook_from = square_of(
        move.type == MoveType::king_castle ? 7 : 0, rank);
    app.animation.rook_to = square_of(
        move.type == MoveType::king_castle ? 5 : 3, rank);
    const int sign = moving_cell < 0 ? -1 : 1;
    app.animation.rook_cell = static_cast<std::int8_t>(
        sign * static_cast<int>(Piece::rook));
  }
  if (app.window) SetTimer(app.window, animation_timer_id, 16, nullptr);
}

void stop_engine(App& app) {
  app.search_generation.fetch_add(1);
  app.stop.store(true);
  if (app.current_version_engine) app.current_version_engine->request_stop();
  if (app.previous_version_engine) app.previous_version_engine->request_stop();
  if (app.worker.joinable()) app.worker.join();
  app.thinking.store(false);
  std::scoped_lock lock(app.result_mutex);
  app.pending_result.reset();
  app.pending_error.clear();
}

std::optional<Move> legal_uci_move(const Board& board,
                                   std::string_view text) {
  const auto parsed = parse_uci_move(text);
  if (!parsed) return std::nullopt;
  for (const Move& move : board.legal_moves())
    if (move.same_coordinates(*parsed)) return move;
  return std::nullopt;
}

void start_engine(App& app) {
  if (app.animation.active || app.thinking.load() ||
      (!app.version_match && app.board.turn == app.human) || game_over(app))
    return;
  if (app.version_match &&
      (!app.current_version_engine || !app.previous_version_engine)) return;
  if (app.worker.joinable()) app.worker.join();

  const Board root = app.board;
  const int depth = std::clamp(app.depth, 1, maximum_gui_search_depth);
  const bool version_mode = app.version_match;
  const bool current_turn = root.turn == app.current_version_side;
  app.stop.store(false);
  app.thinking.store(true);
  const auto generation = app.search_generation.fetch_add(1) + 1;
  app.status = version_mode
      ? std::format("{} is thinking · {} plies",
                    current_turn ? "Current Eloi" : "Previous Eloi", depth)
      : std::format("Eloi is thinking · {} plies", depth);
  InvalidateRect(app.window, nullptr, FALSE);

  app.worker = std::thread(
      [&app, root, depth, generation, version_mode, current_turn] {
    if (version_mode) {
      UciVersionEngine* engine = current_turn
          ? app.current_version_engine.get()
          : app.previous_version_engine.get();
      UciVersionResult uci = engine->choose_move(root, depth);
      SearchResult result;
      result.depth = uci.depth;
      result.nodes = uci.nodes;
      result.score_cp = uci.score_cp;
      if (const auto move = legal_uci_move(root, uci.bestmove))
        result.pv.push_back(*move);
      else if (uci.error.empty())
        uci.error = "Engine returned an illegal move: " + uci.bestmove;
      if (!app.stop.load()) {
        std::scoped_lock lock(app.result_mutex);
        if (!result.pv.empty()) app.pending_result = std::move(result);
        app.pending_error = std::move(uci.error);
      }
      PostMessageW(app.window, engine_finished_message,
                   static_cast<WPARAM>(generation), 0);
      return;
    }
    auto config = default_config(EngineKind::eloi);
    config.depth = depth;
    Searcher searcher(config, app.stop);
    SearchLimits limits;
    limits.depth = depth;
    auto result = searcher.iterative(root, limits);
    if (!app.stop.load()) {
      std::scoped_lock lock(app.result_mutex);
      app.pending_result = std::move(result);
      app.pending_error.clear();
    }
    PostMessageW(app.window, engine_finished_message,
                 static_cast<WPARAM>(generation), 0);
  });
}

void finish_animation(App& app) {
  if (!app.animation.active) return;
  const auto after = app.animation.after;
  KillTimer(app.window, animation_timer_id);
  app.animation = {};
  if (game_over(app)) {
    InvalidateRect(app.window, nullptr, FALSE);
    return;
  }
  if (after == App::AnimationAfter::start_engine) {
    app.status = "Eloi is ready";
    start_engine(app);
  } else if (after == App::AnimationAfter::finish_engine) {
    app.status = "Your move";
  }
  InvalidateRect(app.window, nullptr, FALSE);
}

void reset_game(App& app, Color human) {
  cancel_animation(app);
  stop_engine(app);
  app.board = *parse_fen(initial_fen);
  app.human = human;
  app.selected = -1;
  app.last_result = {};
  app.status = human == Color::white ? "Your move" : "Eloi opens";
  InvalidateRect(app.window, nullptr, FALSE);
  start_engine(app);
}

void reset_version_game(App& app) {
  cancel_animation(app);
  stop_engine(app);
  app.board = *parse_fen(initial_fen);
  app.selected = -1;
  app.last_result = {};
  app.last_engine = "No moves yet";
  if (app.current_version_engine) app.current_version_engine->begin_new_game();
  if (app.previous_version_engine) app.previous_version_engine->begin_new_game();
  app.status = app.current_version_side == Color::white
      ? "Version match · current Eloi opens"
      : "Version match · previous Eloi opens";
  InvalidateRect(app.window, nullptr, FALSE);
  start_engine(app);
}

void toggle_version_match(App& app) {
  if (app.version_match) {
    cancel_animation(app);
    stop_engine(app);
    app.current_version_engine.reset();
    app.previous_version_engine.reset();
    app.previous_version_path.clear();
    app.previous_version_label.clear();
    app.version_match = false;
    reset_game(app, app.human);
    return;
  }

  const std::filesystem::path current = running_executable();
  std::filesystem::path previous =
      current.parent_path() / "Eloi.previous.exe";
  if (!std::filesystem::is_regular_file(previous)) {
    const auto selected = choose_previous_executable(app.window);
    if (!selected) {
      app.status = "Version match canceled · no previous executable selected";
      InvalidateRect(app.window, nullptr, FALSE);
      return;
    }
    previous = *selected;
  }
  std::error_code error;
  if (std::filesystem::equivalent(current, previous, error)) {
    MessageBoxW(app.window,
        L"Choose an earlier Eloi executable, not the currently running one.",
        L"Eloi Version Match", MB_OK | MB_ICONWARNING);
    return;
  }

  cancel_animation(app);
  stop_engine(app);
  app.current_version_engine = std::make_unique<UciVersionEngine>(current);
  app.previous_version_engine = std::make_unique<UciVersionEngine>(previous);
  app.previous_version_path = previous;
  app.previous_version_label = previous.filename().string();
  const std::filesystem::path metadata = previous.parent_path() /
      (previous.stem().string() + ".commit.txt");
  if (std::ifstream input(metadata); input) {
    std::string commit;
    if (std::getline(input, commit) && !commit.empty())
      app.previous_version_label += " · " + commit;
  }
  app.current_version_side = Color::white;
  app.version_match = true;
  reset_version_game(app);
}

void undo_turn(App& app) {
  cancel_animation(app);
  stop_engine(app);
  if (!app.board.history.empty()) app.board.pop();
  if (!app.board.history.empty() && app.board.turn != app.human) app.board.pop();
  app.selected = -1;
  app.status = app.board.turn == app.human ? "Your move" : "Eloi is ready";
  InvalidateRect(app.window, nullptr, FALSE);
  start_engine(app);
}

void render_piece(SkCanvas& canvas, App& app, std::int8_t cell,
                  float x, float y, float size) {
  const int slot = piece_slot(cell);
  if (slot < 0 || !app.pieces[slot]) return;
  const float inset = size * 0.07f;
  const SkRect destination = SkRect::MakeXYWH(
      x + inset, y + inset, size - inset * 2, size - inset * 2);
  canvas.drawImageRect(app.pieces[slot], destination,
                       SkSamplingOptions(SkFilterMode::kLinear), nullptr);
}

constexpr int material_points(Piece piece) {
  switch (piece) {
    case Piece::pawn: return 1;
    case Piece::bishop:
    case Piece::knight: return 3;
    case Piece::rook: return 5;
    case Piece::queen: return 9;
    default: return 0;
  }
}

struct MaterialDisplay {
  // First index is the side that made the capture; second is the piece type.
  std::array<std::array<int, 7>, 2> captured{};
  std::array<int, 2> remaining{};
};

MaterialDisplay material_display(const Board& board) {
  MaterialDisplay result;
  for (const std::int8_t cell : board.position.cells) {
    if (!cell) continue;
    const int side = cell > 0 ? 0 : 1;
    result.remaining[side] += material_points(
        static_cast<Piece>(std::abs(static_cast<int>(cell))));
  }
  for (const Board::Snapshot& state : board.history) {
    if (state.move.capture == Piece::none) continue;
    const int capturer = state.turn == Color::white ? 0 : 1;
    ++result.captured[capturer][static_cast<std::size_t>(state.move.capture)];
  }
  return result;
}

void render_material(SkCanvas& canvas, App& app, float left, float right) {
  const MaterialDisplay material = material_display(app.board);
  const int balance = material.remaining[0] - material.remaining[1];
  text(canvas, "MATERIAL", left, 204, 11, muted, true);
  const std::string balance_text = balance == 0
      ? "EVEN"
      : std::format("{} +{}", balance > 0 ? "WHITE" : "BLACK",
                    std::abs(balance));
  text(canvas, balance_text,
       right - static_cast<float>(balance_text.size()) * 7.0f,
       204, 11, balance == 0 ? muted : mint, true);

  SkPaint divider;
  divider.setColor(SkColorSetARGB(90, 93, 101, 128));
  divider.setStrokeWidth(1.0f);
  canvas.drawLine(left, 211, right, 211, divider);

  constexpr std::array order{
      Piece::pawn, Piece::knight, Piece::bishop, Piece::rook, Piece::queen};
  auto row = [&](Color capturer, float top) {
    const int side = capturer == Color::white ? 0 : 1;
    text(canvas, capturer == Color::white ? "WHITE" : "BLACK",
         left, top + 16, 10, ink, true);
    float x = left + 55;
    int icons = 0;
    const int victim_sign = capturer == Color::white ? -1 : 1;
    for (const Piece piece : order) {
      const int count = material.captured[side][static_cast<std::size_t>(piece)];
      for (int i = 0; i < count; ++i) {
        render_piece(canvas, app,
                     static_cast<std::int8_t>(victim_sign *
                                              static_cast<int>(piece)),
                     x, top, 22);
        x += 11.5f;
        ++icons;
      }
    }
    if (!icons) text(canvas, "—", x + 2, top + 16, 11, muted);
    const int advantage = side == 0 ? balance : -balance;
    if (advantage > 0)
      text(canvas, std::format("+{}", advantage), right - 25,
           top + 16, 12, mint, true);
  };
  row(Color::black, 214);
  row(Color::white, 237);
}

SkPoint square_origin(const App& app, const Layout& layout, int square) {
  const int display_file = app.flipped ? 7 - file_of(square) : file_of(square);
  const int display_rank = app.flipped ? rank_of(square) : 7 - rank_of(square);
  return {layout.board_left + display_file * layout.square,
          layout.board_top + display_rank * layout.square};
}

std::array<UiRect, 4> promotion_rects(const Layout& layout) {
  const float gap = 10.0f;
  const float card = std::min(layout.square * 1.18f, 92.0f);
  const float width = card * 4 + gap * 3;
  const float left = layout.board_left + (layout.board_size - width) / 2;
  const float top = layout.board_top + (layout.board_size - card) / 2 + 18;
  std::array<UiRect, 4> result{};
  for (int i = 0; i < 4; ++i) {
    const float x = left + i * (card + gap);
    result[i] = {x, top, x + card, top + card};
  }
  return result;
}

float animation_progress(const App& app) {
  if (!app.animation.active) return 1.0f;
  const float raw = std::chrono::duration<float>(
      std::chrono::steady_clock::now() - app.animation.started).count() /
      std::chrono::duration<float>(move_animation_duration).count();
  const float t = std::clamp(raw, 0.0f, 1.0f);
  return t * t * (3.0f - 2.0f * t);
}

void render_animation(App& app, SkCanvas& canvas, const Layout& layout) {
  if (!app.animation.active) return;
  const float t = animation_progress(app);
  auto moving_piece = [&](std::int8_t cell, int from, int to) {
    const SkPoint a = square_origin(app, layout, from);
    const SkPoint b = square_origin(app, layout, to);
    const float x = a.x() + (b.x() - a.x()) * t;
    const float y = a.y() + (b.y() - a.y()) * t;
    SkPaint shadow;
    shadow.setAntiAlias(true);
    shadow.setColor(SkColorSetARGB(70, 0, 0, 0));
    canvas.drawOval(SkRect::MakeXYWH(x + layout.square * .18f,
                                     y + layout.square * .78f,
                                     layout.square * .64f,
                                     layout.square * .13f), shadow);
    render_piece(canvas, app, cell, x, y, layout.square);
  };
  moving_piece(app.animation.moving_cell, app.animation.move.from,
               app.animation.move.to);
  if (app.animation.rook_from >= 0)
    moving_piece(app.animation.rook_cell, app.animation.rook_from,
                 app.animation.rook_to);
}

void render_promotion_picker(App& app, SkCanvas& canvas, const Layout& layout) {
  if (!app.promotion.active) return;
  SkPaint veil;
  veil.setColor(SkColorSetARGB(170, 10, 11, 21));
  canvas.drawRoundRect(
      SkRect::MakeXYWH(layout.board_left, layout.board_top,
                       layout.board_size, layout.board_size),
      10, 10, veil);
  const auto cards = promotion_rects(layout);
  const float panel_left = cards.front().left - 22;
  const float panel_right = cards.back().right + 22;
  round_rect(canvas, {panel_left, cards.front().top - 61,
                      panel_right, cards.front().bottom + 22},
             20, SkColorSetRGB(28, 31, 48));
  text(canvas, "CHOOSE PROMOTION", panel_left + 22,
       cards.front().top - 25, 16, ink, true);
  constexpr std::array order{
      Piece::queen, Piece::rook, Piece::bishop, Piece::knight};
  const int sign = app.human == Color::white ? 1 : -1;
  for (std::size_t i = 0; i < cards.size(); ++i) {
    round_rect(canvas, cards[i], 14,
               i == 0 ? SkColorSetRGB(65, 57, 105)
                      : SkColorSetRGB(39, 43, 62));
    render_piece(canvas, app,
                 static_cast<std::int8_t>(sign * static_cast<int>(order[i])),
                 cards[i].left, cards[i].top,
                 cards[i].right - cards[i].left);
  }
}

void render(App& app, SkCanvas& canvas, int width, int height) {
  const Layout layout = make_layout(width, height);
  SkPaint background;
  background.setColor(SkColorSetRGB(16, 17, 31));
  canvas.drawPaint(background);

  text(canvas, "ELOI", 42, 57, 34, ink, true);
  text(canvas, "A modern chess mind", 151, 54, 17, muted);
  round_rect(canvas, {42, 75, 356, 94}, 9, SkColorSetRGB(31, 35, 52));
  text(canvas, "C++26  ·  ALPHA-BETA  ·  LMR  ·  NNUE", 55, 89, 11, mint, true);

  round_rect(canvas,
             {layout.board_left - 10, layout.board_top - 10,
              layout.board_left + layout.board_size + 10,
              layout.board_top + layout.board_size + 10},
             20, SkColorSetRGB(31, 35, 50));

  std::vector<int> destinations;
  if (app.selected >= 0) {
    for (const auto& move : app.board.legal_moves())
      if (move.from == app.selected) destinations.push_back(move.to);
  }
  const auto previous = app.board.last_move();

  for (int display_rank = 0; display_rank < 8; ++display_rank) {
    for (int display_file = 0; display_file < 8; ++display_file) {
      const int file = app.flipped ? 7 - display_file : display_file;
      const int rank = app.flipped ? display_rank : 7 - display_rank;
      const int square = square_of(file, rank);
      const float x = layout.board_left + display_file * layout.square;
      const float y = layout.board_top + display_rank * layout.square;
      const bool light = ((file + rank) & 1) != 0;
      SkPaint tile;
      tile.setColor(light ? SkColorSetRGB(222, 223, 231)
                          : SkColorSetRGB(101, 91, 154));
      canvas.drawRect(SkRect::MakeXYWH(x, y, layout.square, layout.square), tile);

      if (previous && (square == previous->from || square == previous->to)) {
        SkPaint highlight;
        highlight.setColor(SkColorSetARGB(95, 255, 210, 77));
        canvas.drawRect(SkRect::MakeXYWH(x, y, layout.square, layout.square), highlight);
      }
      if (square == app.selected) {
        SkPaint selected;
        selected.setColor(SkColorSetARGB(135, 61, 220, 177));
        canvas.drawRect(SkRect::MakeXYWH(x, y, layout.square, layout.square), selected);
      }
      if (std::ranges::find(destinations, square) != destinations.end()) {
        SkPaint marker;
        marker.setAntiAlias(true);
        marker.setColor(SkColorSetARGB(185, 33, 39, 55));
        const float radius = app.board.position.empty(square)
            ? layout.square * 0.105f : layout.square * 0.39f;
        marker.setStyle(app.board.position.empty(square)
                            ? SkPaint::kFill_Style : SkPaint::kStroke_Style);
        marker.setStrokeWidth(layout.square * 0.07f);
        canvas.drawCircle(x + layout.square / 2, y + layout.square / 2, radius, marker);
      }

      const bool moving_destination = app.animation.active &&
          square == app.animation.move.to;
      const bool rook_destination = app.animation.active &&
          square == app.animation.rook_to;
      if (!moving_destination && !rook_destination)
        render_piece(canvas, app, app.board.position.cells[square],
                     x, y, layout.square);
      if (display_rank == 7) {
        const char file_label = static_cast<char>('a' + file);
        text(canvas, std::string_view(&file_label, 1), x + layout.square - 13,
             y + layout.square - 7, 11,
             light ? SkColorSetRGB(101, 91, 154) : SkColorSetRGB(222, 223, 231),
             true);
      }
      if (display_file == 0) {
        const char rank_label = static_cast<char>('1' + rank);
        text(canvas, std::string_view(&rank_label, 1), x + 5, y + 14, 11,
             light ? SkColorSetRGB(101, 91, 154) : SkColorSetRGB(222, 223, 231),
             true);
      }
    }
  }

  render_animation(app, canvas, layout);
  render_promotion_picker(app, canvas, layout);

  const float panel_right = static_cast<float>(width) - 38;
  round_rect(canvas, {layout.panel_left, 112, panel_right, 448}, 22,
             SkColorSetARGB(230, 27, 31, 46));
  text(canvas, app.status, layout.panel_left + 24, 151, 18,
       app.thinking.load() ? SkColorSetRGB(255, 205, 92) : mint, true);
  const std::string turn_text = app.version_match
      ? std::format("{} to move · current is {}",
                    app.board.turn == Color::white ? "White" : "Black",
                    app.current_version_side == Color::white ? "White" : "Black")
      : (app.board.turn == Color::white ? "White to move" : "Black to move");
  text(canvas, turn_text, layout.panel_left + 24, 180, 14, muted);

  render_material(canvas, app, layout.panel_left + 24, panel_right - 24);

  text(canvas, app.version_match ? "MATCH DEPTH · BOTH ENGINES" : "SEARCH DEPTH",
       layout.panel_left + 24, 276, 12, muted, true);
  text(canvas, std::format("{} plies", app.depth),
       layout.panel_left + 80, 325, 25, ink, true);
  text(canvas,
       app.depth > recommended_search_depth
           ? "Warning: 40+ may take hours or days"
           : "Recommended limit: 40 plies",
       layout.panel_left + 24, 360, 13,
       app.depth > recommended_search_depth
           ? SkColorSetRGB(255, 205, 92) : muted,
       app.depth > recommended_search_depth);
  button(canvas, layout.depth_minus, "−");
  button(canvas, layout.depth_plus, "+");

  text(canvas, app.version_match
                   ? std::format("LAST MOVE · {}", app.last_engine)
                   : "LAST SEARCH",
       layout.panel_left + 24, 398, 12, muted, true);
  const std::string stats = app.last_result.depth == 0
      ? (app.last_result.opening_family.empty()
             ? "No search yet"
             : std::format("Book · {}", app.last_result.opening_family))
      : std::format("d{}  ·  {} nodes  ·  {:+.2f}",
                    app.last_result.depth, app.last_result.nodes,
                    app.last_result.score_cp / 100.0);
  text(canvas, stats, layout.panel_left + 24, 427, 14, ink);
  if (app.last_result.depth > 0)
    text(canvas, std::format("{} late-move reductions",
                            app.last_result.lmr_reductions),
         layout.panel_left + 24, 446, 12, muted);

  button(canvas, layout.new_game,
         app.version_match ? "RESTART VERSION MATCH" : "NEW GAME", accent);
  button(canvas, layout.undo,
         app.version_match ? "AUTOPLAY ACTIVE" : "UNDO TURN");
  button(canvas, layout.flip, app.flipped ? "NORMAL VIEW" : "FLIP BOARD");
  button(canvas, layout.side,
         app.version_match
             ? "SWAP CURRENT / PREVIOUS COLORS"
             : (app.human == Color::white ? "PLAY AS BLACK" : "PLAY AS WHITE"));
  button(canvas, layout.version_match,
         app.version_match ? "EXIT VERSION MATCH" : "VERSION MATCH",
         app.version_match ? SkColorSetRGB(65, 57, 105) : accent);

  if (app.version_match && !app.previous_version_path.empty())
    text(canvas,
         std::format("Previous: {}", app.previous_version_label),
         layout.panel_left, static_cast<float>(height) - 67, 11, muted);

  text(canvas, "Maestro BW pieces · Kadagaden · CC BY 4.0",
       layout.panel_left, static_cast<float>(height) - 48, 11, muted);
  text(canvas, "Board and interface rendered in code with Skia",
       layout.panel_left, static_cast<float>(height) - 27, 11, muted);
}

std::optional<int> square_at(const App& app, const Layout& layout, float x, float y) {
  if (x < layout.board_left || y < layout.board_top ||
      x >= layout.board_left + layout.board_size ||
      y >= layout.board_top + layout.board_size) return std::nullopt;
  const int display_file = static_cast<int>((x - layout.board_left) / layout.square);
  const int display_rank = static_cast<int>((y - layout.board_top) / layout.square);
  const int file = app.flipped ? 7 - display_file : display_file;
  const int rank = app.flipped ? display_rank : 7 - display_rank;
  return square_of(file, rank);
}

void play_human_move(App& app, int target) {
  if (app.version_match || app.animation.active || app.thinking.load() ||
      app.board.turn != app.human || game_over(app)) return;
  const auto moves = app.board.legal_moves();
  if (app.selected >= 0) {
    std::vector<Move> matches;
    for (const Move& move : moves)
      if (move.from == app.selected && move.to == target)
        matches.push_back(move);
    if (!matches.empty() && matches.front().is_promotion()) {
      app.promotion.active = true;
      app.promotion.moves = std::move(matches);
      app.status = "Choose a promotion piece";
      InvalidateRect(app.window, nullptr, FALSE);
      return;
    }
    if (!matches.empty()) {
      const Move move = matches.front();
      const std::int8_t moving_cell = app.board.position.cells[move.from];
      if (!app.board.push(move)) return;
      app.selected = -1;
      app.status = "Move played";
      begin_animation(app, move, moving_cell,
                      App::AnimationAfter::start_engine);
      InvalidateRect(app.window, nullptr, FALSE);
      return;
    }
  }
  const auto color = app.board.position.color_at(target);
  app.selected = color && *color == app.human ? target : -1;
  InvalidateRect(app.window, nullptr, FALSE);
}

void on_click(App& app, float x, float y) {
  RECT client{};
  GetClientRect(app.window, &client);
  const auto layout = make_layout(client.right, client.bottom);
  if (app.promotion.active) {
    constexpr std::array order{
        Piece::queen, Piece::rook, Piece::bishop, Piece::knight};
    const auto cards = promotion_rects(layout);
    for (std::size_t i = 0; i < cards.size(); ++i) {
      if (!cards[i].contains(x, y)) continue;
      const auto chosen = std::ranges::find_if(
          app.promotion.moves,
          [&](const Move& move) { return move.promotion == order[i]; });
      if (chosen != app.promotion.moves.end()) {
        const Move move = *chosen;
        const std::int8_t moving_cell = app.board.position.cells[move.from];
        app.promotion = {};
        if (app.board.push(move)) {
          app.selected = -1;
          app.status = "Move played";
          begin_animation(app, move, moving_cell,
                          App::AnimationAfter::start_engine);
        }
      }
      InvalidateRect(app.window, nullptr, FALSE);
      return;
    }
    app.promotion = {};
    app.status = "Your move";
    InvalidateRect(app.window, nullptr, FALSE);
    return;
  }
  if (const auto square = square_at(app, layout, x, y)) {
    play_human_move(app, *square);
    return;
  }
  if (layout.depth_minus.contains(x, y)) {
    app.depth = std::max(1, app.depth - 1);
  } else if (layout.depth_plus.contains(x, y)) {
    app.depth = std::min(maximum_gui_search_depth, app.depth + 1);
    if (app.depth > recommended_search_depth)
      app.status = std::format("Warning · depth {} may take a very long time",
                               app.depth);
  } else if (layout.new_game.contains(x, y)) {
    if (app.version_match) reset_version_game(app);
    else reset_game(app, app.human);
    return;
  } else if (layout.undo.contains(x, y)) {
    if (!app.version_match) undo_turn(app);
    return;
  } else if (layout.flip.contains(x, y)) {
    if (!app.animation.active) app.flipped = !app.flipped;
  } else if (layout.side.contains(x, y)) {
    if (app.version_match) {
      app.current_version_side = opponent(app.current_version_side);
      reset_version_game(app);
    } else {
      reset_game(app, opponent(app.human));
    }
    return;
  } else if (layout.version_match.contains(x, y)) {
    toggle_version_match(app);
    return;
  }
  InvalidateRect(app.window, nullptr, FALSE);
}

LRESULT CALLBACK window_proc(HWND window, UINT message, WPARAM wparam, LPARAM lparam) {
  App* app = reinterpret_cast<App*>(GetWindowLongPtrW(window, GWLP_USERDATA));
  if (message == WM_NCCREATE) {
    const auto* create = reinterpret_cast<CREATESTRUCTW*>(lparam);
    app = static_cast<App*>(create->lpCreateParams);
    app->window = window;
    SetWindowLongPtrW(window, GWLP_USERDATA, reinterpret_cast<LONG_PTR>(app));
  }

  switch (message) {
    case WM_GETMINMAXINFO: {
      auto* info = reinterpret_cast<MINMAXINFO*>(lparam);
      info->ptMinTrackSize = {980, 910};
      return 0;
    }
    case WM_LBUTTONDOWN:
      if (app) on_click(*app, static_cast<float>(GET_X_LPARAM(lparam)),
                        static_cast<float>(GET_Y_LPARAM(lparam)));
      return 0;
    case WM_TIMER:
      if (app && wparam == animation_timer_id) {
        if (std::chrono::steady_clock::now() - app->animation.started >=
            move_animation_duration)
          finish_animation(*app);
        else
          InvalidateRect(window, nullptr, FALSE);
      }
      return 0;
    case engine_finished_message:
      if (app) {
        if (static_cast<std::uint64_t>(wparam) != app->search_generation.load())
          return 0;
        if (app->worker.joinable()) app->worker.join();
        std::optional<SearchResult> result;
        std::string pending_error;
        {
          std::scoped_lock lock(app->result_mutex);
          result = std::move(app->pending_result);
          app->pending_result.reset();
          pending_error = std::move(app->pending_error);
          app->pending_error.clear();
        }
        app->thinking.store(false);
        if (result && !result->pv.empty()) {
          app->last_result = *result;
          const bool current_moved = app->version_match &&
              app->board.turn == app->current_version_side;
          if (app->version_match)
            app->last_engine = current_moved ? "CURRENT" : "PREVIOUS";
          const Move move = result->pv.front();
          const std::int8_t moving_cell = app->board.position.cells[move.from];
          if (app->board.push(move)) {
            if (app->version_match) {
              app->status = current_moved
                  ? "Current Eloi moved" : "Previous Eloi moved";
            } else {
              app->status = result->opening_family.empty()
                  ? "Eloi moved"
                  : std::format("Eloi · {}", result->opening_family);
            }
            begin_animation(*app, move, moving_cell,
                            app->version_match
                                ? App::AnimationAfter::start_engine
                                : App::AnimationAfter::finish_engine);
          }
        } else if (!app->stop.load()) {
          app->status = pending_error.empty()
              ? "No legal engine move" : std::move(pending_error);
        }
        InvalidateRect(window, nullptr, FALSE);
      }
      return 0;
    case WM_ERASEBKGND:
      return 1;
    case WM_PAINT: {
      PAINTSTRUCT paint_struct{};
      HDC dc = BeginPaint(window, &paint_struct);
      RECT client{};
      GetClientRect(window, &client);
      const int width = std::max(1L, client.right);
      const int height = std::max(1L, client.bottom);
      auto surface = SkSurface::MakeRaster(
          SkImageInfo::MakeN32Premul(width, height));
      if (surface && app) {
        render(*app, *surface->getCanvas(), width, height);
        SkPixmap pixels;
        if (surface->peekPixels(&pixels)) {
          BITMAPINFO bitmap{};
          bitmap.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
          bitmap.bmiHeader.biWidth = width;
          bitmap.bmiHeader.biHeight = -height;
          bitmap.bmiHeader.biPlanes = 1;
          bitmap.bmiHeader.biBitCount = 32;
          bitmap.bmiHeader.biCompression = BI_RGB;
          StretchDIBits(dc, 0, 0, width, height, 0, 0, width, height,
                        pixels.addr(), &bitmap, DIB_RGB_COLORS, SRCCOPY);
        }
      }
      EndPaint(window, &paint_struct);
      return 0;
    }
    case WM_CLOSE:
      if (app) {
        cancel_animation(*app);
        stop_engine(*app);
      }
      DestroyWindow(window);
      return 0;
    case WM_DESTROY:
      PostQuitMessage(0);
      return 0;
    default:
      return DefWindowProcW(window, message, wparam, lparam);
  }
}

}  // namespace

int run_gui(int argc, char** argv) {
  if (HWND console = GetConsoleWindow()) ShowWindow(console, SW_HIDE);
  SkGraphics::Init();

  App app;
  load_pieces(app);
  bool launch_version_match = false;
  for (int i = 1; i < argc; ++i)
    if (std::string_view(argv[i]) == "--version-match")
      launch_version_match = true;
  for (int i = 1; i + 1 < argc; ++i) {
    if (std::string_view(argv[i]) != "--screenshot") continue;
    constexpr int width = 1180;
    constexpr int height = 850;
    auto surface = SkSurface::MakeRaster(SkImageInfo::MakeN32Premul(width, height));
    if (!surface) return 2;
    render(app, *surface->getCanvas(), width, height);
    SkPixmap pixels;
    if (!surface->peekPixels(&pixels)) return 2;
    return write_bmp(argv[i + 1], pixels) ? 0 : 2;
  }
  const HINSTANCE instance = GetModuleHandleW(nullptr);
  constexpr wchar_t class_name[] = L"EloiSkiaWindow";
  WNDCLASSEXW window_class{};
  window_class.cbSize = sizeof(window_class);
  window_class.style = CS_HREDRAW | CS_VREDRAW;
  window_class.lpfnWndProc = window_proc;
  window_class.hInstance = instance;
  window_class.hCursor = LoadCursorW(nullptr, MAKEINTRESOURCEW(32512));
  window_class.hIcon = LoadIconW(nullptr, MAKEINTRESOURCEW(32512));
  window_class.hbrBackground = nullptr;
  window_class.lpszClassName = class_name;
  RegisterClassExW(&window_class);

  const HWND window = CreateWindowExW(
      0, class_name, L"Eloi — C++26 Chess",
      WS_OVERLAPPEDWINDOW, CW_USEDEFAULT, CW_USEDEFAULT, 1180, 910,
      nullptr, nullptr, instance, &app);
  if (!window) return 1;
  ShowWindow(window, SW_SHOW);
  UpdateWindow(window);
  if (launch_version_match) toggle_version_match(app);

  MSG message{};
  while (GetMessageW(&message, nullptr, 0, 0) > 0) {
    TranslateMessage(&message);
    DispatchMessageW(&message);
  }
  return static_cast<int>(message.wParam);
}

}  // namespace eloi

#else

namespace eloi {
int run_gui(int, char**) { return 1; }
}  // namespace eloi

#endif
