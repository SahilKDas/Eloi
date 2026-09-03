// Test-only translation unit: exercise the real GUI handlers without changing
// production behavior or injecting input into another application.
#include <iostream>
#include "../src/gui.cpp"

int main() {
  using namespace eloi;
  SkGraphics::Init();
  App app;
  app.window = CreateWindowExW(0, L"STATIC", L"Eloi isolated GUI smoke",
                               WS_POPUP, 0, 0, 1180, 850,
                               nullptr, nullptr, GetModuleHandleW(nullptr), nullptr);
  if (!app.window) return 2;
  int failures = 0;
  auto check = [&](bool ok, const char* label) {
    std::cout << (ok ? "PASS: " : "FAIL: ") << label << '\n';
    failures += !ok;
  };
  RECT client{};
  GetClientRect(app.window, &client);
  const auto layout = make_layout(client.right, client.bottom);
  auto click = [&](const UiRect& rect) {
    on_click(app, (rect.left + rect.right) / 2, (rect.top + rect.bottom) / 2);
  };
  load_pieces(app);
  check(std::ranges::all_of(app.pieces, [](const auto& piece) { return bool(piece); }),
        "all twelve real piece images load");
  app.board = *parse_fen("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1");
  const auto before_castle = to_fen(app.board);
  play_human_move(app, *parse_square("e1"));
  play_human_move(app, *parse_square("g1"));
  check(app.animation.active && app.animation.rook_from == *parse_square("h1") &&
            app.animation.rook_to == *parse_square("f1") &&
            app.board.position.cells[*parse_square("g1")] == static_cast<int>(Piece::king) &&
            app.board.position.cells[*parse_square("f1")] == static_cast<int>(Piece::rook),
        "human castling moves king and rook and records rook animation");
  undo_turn(app);
  check(to_fen(app.board) == before_castle, "GUI undo restores the complete castling position");
  const std::array choices{Piece::queen, Piece::rook, Piece::bishop, Piece::knight};
  for (std::size_t i = 0; i < choices.size(); ++i) {
    cancel_animation(app);
    app.board = *parse_fen("7k/P7/8/8/8/8/8/K7 w - - 0 1");
    const auto before = to_fen(app.board);
    play_human_move(app, *parse_square("a7"));
    play_human_move(app, *parse_square("a8"));
    check(app.promotion.active && app.promotion.moves.size() == 4,
          "promotion dialog offers all four legal pieces");
    click(promotion_rects(layout)[i]);
    check(!app.promotion.active &&
              app.board.position.cells[*parse_square("a8")] == static_cast<int>(choices[i]),
          "promotion click commits the selected piece");
    undo_turn(app);
    check(to_fen(app.board) == before, "GUI undo restores promotion position");
  }
  reset_game(app, Color::white);
  open_game_setup(app, 7);
  click(layout.setup_sides[1]);
  check(app.setup.human == Color::black, "setup selects black");
  click(layout.setup_sides[0]);
  click(layout.setup_variants[2]);
  check(app.setup.variant == App::LocalVariant::horde, "setup selects Horde");
  click(layout.setup_variants[0]);
  click(layout.setup_base_plus);
  click(layout.setup_increment_plus);
  click(layout.setup_start);
  check(!app.setup.active && app.human == Color::white && app.clocked_game &&
            app.increment_ms == 1000 && app.clock_ms[0] == 360000,
        "clocked setup applies side, variant, base time and increment");
  click(layout.flip);
  check(app.flipped, "board flip changes view");
  click(layout.flip);
  check(!app.flipped, "board flip restores normal view");
  open_game_setup(app, 7);
  click(layout.setup_cancel);
  check(!app.setup.active && app.depth == 7, "setup cancellation restores prior depth");
  auto surface = SkSurface::MakeRaster(SkImageInfo::MakeN32Premul(1180, 850));
  check(bool(surface), "Skia render surface created");
  if (surface) {
    app.version_match = true;
    render(app, *surface->getCanvas(), 1180, 850);
    SkPixmap pixels;
    check(surface->peekPixels(&pixels), "Engine Lab renders through real GUI code");
  }
  stop_engine(app);
  DestroyWindow(app.window);
  return failures ? 1 : 0;
}
