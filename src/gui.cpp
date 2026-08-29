#include "eloi/chess.hpp"

#ifdef _WIN32

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <windowsx.h>

#include "include/core/SkCanvas.h"
#include "include/core/SkColor.h"
#include "include/core/SkFont.h"
#include "include/core/SkGraphics.h"
#include "include/core/SkImageInfo.h"
#include "include/core/SkPaint.h"
#include "include/core/SkPath.h"
#include "include/core/SkPixmap.h"
#include "include/core/SkStream.h"
#include "include/core/SkSurface.h"
#include "include/core/SkTileMode.h"
#include "include/effects/SkGradientShader.h"

#define NANOSVG_IMPLEMENTATION
#include "nanosvg.h"

#include <algorithm>
#include <array>
#include <atomic>
#include <filesystem>
#include <fstream>
#include <format>
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
  bool flipped{false};
  int depth{7};
  int selected{-1};
  std::atomic_bool stop{false};
  std::atomic_bool thinking{false};
  std::atomic_uint64_t search_generation{0};
  std::thread worker;
  std::mutex result_mutex;
  std::optional<SearchResult> pending_result;
  SearchResult last_result;
  std::string status{"Your move"};
  struct SvgDeleter {
    void operator()(NSVGimage* image) const { nsvgDelete(image); }
  };
  std::array<std::unique_ptr<NSVGimage, SvgDeleter>, 12> pieces;

  ~App() {
    stop.store(true);
    if (worker.joinable()) worker.join();
  }
};

void start_engine(App& app);

std::filesystem::path executable_directory() {
  std::wstring path(32768, L'\0');
  const DWORD length = GetModuleFileNameW(nullptr, path.data(),
                                          static_cast<DWORD>(path.size()));
  path.resize(length);
  return std::filesystem::path(path).parent_path();
}

void load_pieces(App& app) {
  constexpr std::array names{
      "wB.svg", "wK.svg", "wN.svg", "wP.svg", "wQ.svg", "wR.svg",
      "bB.svg", "bK.svg", "bN.svg", "bP.svg", "bQ.svg", "bR.svg"};
  const auto root = executable_directory() / "assets" / "chess_maestro_bw";
  for (std::size_t i = 0; i < names.size(); ++i) {
    app.pieces[i].reset(
        nsvgParseFromFile((root / names[i]).string().c_str(), "px", 96.0f));
  }
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
    app.status = app.board.position.in_check(app.board.turn)
        ? (app.board.turn == app.human ? "Checkmate — Eloi wins" : "Checkmate — you win")
        : "Draw by stalemate";
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
  if (app.worker.joinable()) app.worker.join();
  app.thinking.store(false);
  std::scoped_lock lock(app.result_mutex);
  app.pending_result.reset();
}

void start_engine(App& app) {
  if (app.animation.active || app.thinking.load() ||
      app.board.turn == app.human || game_over(app)) return;
  if (app.worker.joinable()) app.worker.join();

  const Board root = app.board;
  const int depth = std::clamp(app.depth, 1, maximum_search_depth);
  app.stop.store(false);
  app.thinking.store(true);
  const auto generation = app.search_generation.fetch_add(1) + 1;
  app.status = std::format("Eloi is thinking · {} plies", depth);
  InvalidateRect(app.window, nullptr, FALSE);

  app.worker = std::thread([&app, root, depth, generation] {
    auto config = default_config(EngineKind::eloi);
    config.depth = depth;
    Searcher searcher(config, app.stop);
    SearchLimits limits;
    limits.depth = depth;
    auto result = searcher.iterative(root, limits);
    if (!app.stop.load()) {
      std::scoped_lock lock(app.result_mutex);
      app.pending_result = std::move(result);
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

SkColor svg_color(unsigned int color, float opacity) {
  const auto alpha = static_cast<unsigned char>(
      std::clamp(((color >> 24) & 0xff) * opacity, 0.0f, 255.0f));
  return SkColorSetARGB(alpha, color & 0xff, (color >> 8) & 0xff,
                        (color >> 16) & 0xff);
}

SkTileMode svg_tile_mode(char spread) {
  if (spread == NSVG_SPREAD_REPEAT) return SkTileMode::kRepeat;
  if (spread == NSVG_SPREAD_REFLECT) return SkTileMode::kMirror;
  return SkTileMode::kClamp;
}

SkPaint svg_paint(const NSVGpaint& source, const NSVGshape& shape, bool stroke) {
  SkPaint paint;
  paint.setAntiAlias(true);
  paint.setStyle(stroke ? SkPaint::kStroke_Style : SkPaint::kFill_Style);
  if (stroke) {
    paint.setStrokeWidth(shape.strokeWidth);
    paint.setStrokeJoin(shape.strokeLineJoin == NSVG_JOIN_ROUND
                            ? SkPaint::kRound_Join
                            : shape.strokeLineJoin == NSVG_JOIN_BEVEL
                                  ? SkPaint::kBevel_Join : SkPaint::kMiter_Join);
    paint.setStrokeCap(shape.strokeLineCap == NSVG_CAP_ROUND
                           ? SkPaint::kRound_Cap
                           : shape.strokeLineCap == NSVG_CAP_SQUARE
                                 ? SkPaint::kSquare_Cap : SkPaint::kButt_Cap);
  }
  if (source.type == NSVG_PAINT_COLOR) {
    paint.setColor(svg_color(source.color, shape.opacity));
  } else if ((source.type == NSVG_PAINT_LINEAR_GRADIENT ||
              source.type == NSVG_PAINT_RADIAL_GRADIENT) &&
             source.gradient && source.gradient->nstops > 0) {
    std::vector<SkColor> colors;
    std::vector<SkScalar> offsets;
    for (int i = 0; i < source.gradient->nstops; ++i) {
      colors.push_back(svg_color(source.gradient->stops[i].color, shape.opacity));
      offsets.push_back(source.gradient->stops[i].offset);
    }
    if (colors.size() == 1) {
      paint.setColor(colors.front());
    } else if (source.type == NSVG_PAINT_RADIAL_GRADIENT) {
      const SkPoint center{(shape.bounds[0] + shape.bounds[2]) / 2,
                           (shape.bounds[1] + shape.bounds[3]) / 2};
      const float radius = std::max(shape.bounds[2] - shape.bounds[0],
                                    shape.bounds[3] - shape.bounds[1]) / 2;
      paint.setShader(SkGradientShader::MakeRadial(
          center, radius, colors.data(), offsets.data(),
          static_cast<int>(colors.size()), svg_tile_mode(source.gradient->spread)));
    } else {
      const SkPoint points[] = {{shape.bounds[0], shape.bounds[1]},
                                {shape.bounds[2], shape.bounds[1]}};
      paint.setShader(SkGradientShader::MakeLinear(
          points, colors.data(), offsets.data(), static_cast<int>(colors.size()),
          svg_tile_mode(source.gradient->spread)));
    }
  }
  return paint;
}

void render_piece(SkCanvas& canvas, App& app, std::int8_t cell,
                  float x, float y, float size) {
  const int slot = piece_slot(cell);
  if (slot < 0 || !app.pieces[slot]) return;
  NSVGimage& image = *app.pieces[slot];
  canvas.save();
  const float inset = size * 0.07f;
  canvas.translate(x + inset, y + inset);
  canvas.scale((size - inset * 2) / image.width,
               (size - inset * 2) / image.height);
  for (const NSVGshape* shape = image.shapes; shape; shape = shape->next) {
    if (!(shape->flags & NSVG_FLAGS_VISIBLE)) continue;
    SkPath path;
    path.setFillType(shape->fillRule == NSVG_FILLRULE_EVENODD
                         ? SkPathFillType::kEvenOdd : SkPathFillType::kWinding);
    for (const NSVGpath* source = shape->paths; source; source = source->next) {
      path.moveTo(source->pts[0], source->pts[1]);
      for (int i = 1; i + 2 < source->npts; i += 3) {
        path.cubicTo(source->pts[i * 2], source->pts[i * 2 + 1],
                     source->pts[(i + 1) * 2], source->pts[(i + 1) * 2 + 1],
                     source->pts[(i + 2) * 2], source->pts[(i + 2) * 2 + 1]);
      }
      if (source->closed) path.close();
    }
    if (shape->fill.type != NSVG_PAINT_NONE)
      canvas.drawPath(path, svg_paint(shape->fill, *shape, false));
    if (shape->stroke.type != NSVG_PAINT_NONE)
      canvas.drawPath(path, svg_paint(shape->stroke, *shape, true));
  }
  canvas.restore();
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
  text(canvas, app.board.turn == Color::white ? "White to move" : "Black to move",
       layout.panel_left + 24, 180, 14, muted);

  text(canvas, "SEARCH DEPTH", layout.panel_left + 24, 251, 12, muted, true);
  text(canvas, std::format("{} plies", app.depth),
       layout.panel_left + 80, 325, 25, ink, true);
  text(canvas, "Hard ceiling: 40 plies", layout.panel_left + 24, 360, 13, muted);
  button(canvas, layout.depth_minus, "−");
  button(canvas, layout.depth_plus, "+");

  text(canvas, "LAST SEARCH", layout.panel_left + 24, 398, 12, muted, true);
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

  button(canvas, layout.new_game, "NEW GAME", accent);
  button(canvas, layout.undo, "UNDO TURN");
  button(canvas, layout.flip, app.flipped ? "NORMAL VIEW" : "FLIP BOARD");
  button(canvas, layout.side,
         app.human == Color::white ? "PLAY AS BLACK" : "PLAY AS WHITE");

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
  if (app.animation.active || app.thinking.load() ||
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
    app.depth = std::min(maximum_search_depth, app.depth + 1);
  } else if (layout.new_game.contains(x, y)) {
    reset_game(app, app.human);
    return;
  } else if (layout.undo.contains(x, y)) {
    undo_turn(app);
    return;
  } else if (layout.flip.contains(x, y)) {
    if (!app.animation.active) app.flipped = !app.flipped;
  } else if (layout.side.contains(x, y)) {
    reset_game(app, opponent(app.human));
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
      info->ptMinTrackSize = {980, 720};
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
        {
          std::scoped_lock lock(app->result_mutex);
          result = std::move(app->pending_result);
          app->pending_result.reset();
        }
        app->thinking.store(false);
        if (result && !result->pv.empty()) {
          app->last_result = *result;
          const Move move = result->pv.front();
          const std::int8_t moving_cell = app->board.position.cells[move.from];
          if (app->board.push(move)) {
            app->status = result->opening_family.empty()
                ? "Eloi moved"
                : std::format("Eloi · {}", result->opening_family);
            begin_animation(*app, move, moving_cell,
                            App::AnimationAfter::finish_engine);
          }
        } else if (!app->stop.load()) {
          app->status = "No legal engine move";
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
      WS_OVERLAPPEDWINDOW, CW_USEDEFAULT, CW_USEDEFAULT, 1180, 850,
      nullptr, nullptr, instance, &app);
  if (!window) return 1;
  ShowWindow(window, SW_SHOW);
  UpdateWindow(window);

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
