#pragma once

#include <array>
#include <string_view>

namespace tactical_data {
struct Case { std::string_view fen; std::string_view best; };
inline constexpr std::array<Case, 12> mateIn1{{
  {"2kr1b1r/p1p2pp1/2pqN3/7p/6n1/2NPB3/PPP2PPP/R2Q1RK1 b - - 0 13", "d6h2"},
  {"6k1/p1p3pp/4N3/1p6/2q1r1n1/2B5/PP4PP/3R1R1K w - - 0 29", "f1f8"},
  {"8/3B2pp/p5k1/6P1/1ppp1K2/8/1P6/8 w - - 0 39", "d7e8"},
  {"N6r/1p1k1ppp/2np4/b3p3/4P1b1/N1Q5/P4PPP/R3KB1R b KQ - 0 18", "a5c3"},
  {"r4rk1/pp3ppp/3b4/2p1pPB1/7N/2PP3n/PP4PP/R2Q2RK b - - 0 18", "h3f2"},
  {"r3k2r/pb1p1ppp/1b4q1/1Q2P3/8/2NP1PP1/PP4P1/R1B2R1K b kq - 0 17", "g6h5"},
  {"r5k1/pp4pp/4p1q1/4p3/3n4/P3Q1P1/1PP4P/2KR1R2 b - - 5 24", "g6c2"},
  {"1qr2rk1/1p1p1ppp/pB2p1n1/7n/2P1P3/1Q2NP1P/PP2BKPb/3R1R2 b - - 2 20", "b8g3"},
  {"7k/p4R1p/3p3B/2pN1n2/2PbB1b1/3P2P1/P3r3/5R1K b - - 0 28", "f5g3"},
  {"4r1k1/1p2R1p1/p2p2Pp/P1pP4/8/1R3p2/1P1q3P/5B1K w - - 0 35", "e7e8"},
  {"8/6k1/1R5p/5p1P/5P1K/6P1/8/r7 b - - 3 58", "a1h1"},
  {"2r2rk1/5ppp/bq2p3/p2pP1N1/Pb1p2P1/1P2P2P/2QN4/2R1K2R w K - 0 19", "c2h7"},
}};
inline constexpr std::array<Case, 24> mateIn2{{
  {"4r3/1k6/pp3P2/1b5p/3R1p2/P1R2P2/1P4PP/6K1 b - - 0 35", "e8e1"},
  {"r1bq3r/pp1nbkp1/2p1p2p/8/2BP4/1PN3P1/P3QP1P/3R1RK1 w - - 0 20", "e2e6"},
  {"6k1/5ppp/r1p5/p1n1rP2/8/2P2N1P/2P3P1/3R2K1 w - - 0 22", "d1d8"},
  {"5r1k/pp4pp/5p2/1BbQp1r1/7K/7P/1PP3P1/3R3R b - - 3 26", "c5f2"},
  {"1rb3k1/q4rP1/4p2p/3p3p/3P1P2/2P5/2QK3P/3R2R1 w - - 1 30", "c2h7"},
  {"rn1qrk2/ppp3pQ/3p1pP1/3Pp3/2P1P3/8/PP3PP1/R1B1K3 w Q - 3 17", "h7h8"},
  {"6k1/2q2p1p/4pPp1/4P3/p1pP1P2/r1P5/6QP/4B1K1 w - - 0 34", "g2a8"},
  {"r1bqr1k1/pp1nbpp1/2p5/3n2P1/2BP4/P7/1PQNNPP1/R3K2R w KQ - 1 14", "c2h7"},
  {"6k1/5ppp/5n2/pp6/4b1rP/5N1Q/Pq2r1P1/3R2RK w - - 5 33", "d1d8"},
  {"2r5/pR5p/5p1k/4p3/4R3/B4nPP/PP3P2/1K6 b - - 0 27", "f3d2"},
  {"3r2k1/4nppp/pq3b2/1p2p3/2r2P2/2P1NR2/PP1Q2BP/3R2K1 w - - 0 25", "d2d8"},
  {"1r4k1/p4ppp/2Q5/3pq3/8/P6P/2PR1PP1/1R4K1 b - - 0 26", "b8b1"},
  {"8/3k1p2/4p3/p2p4/3P1P2/q3P1rP/7r/1QR2K2 w - - 2 35", "b1b7"},
  {"4rk2/p4q2/1p3Q1b/8/1p5N/2P1p3/P3P3/2K5 w - - 1 44", "h4g6"},
  {"r6k/2q3pp/8/2p5/R1np4/7P/2PB1PP1/6K1 w - - 0 33", "a4a8"},
  {"3rk2r/2qn2p1/p1Q1p3/3n3p/8/8/PP4PP/5R1K w k - 0 24", "c6e6"},
  {"6k1/pp3pp1/2p1q1Pp/3b4/8/6Q1/PB3Pp1/3r1NK1 w - - 0 28", "g3b8"},
  {"1r6/5k2/2Q1pNp1/p5Pp/1p2P2P/2P4R/KP3P2/3q4 b - - 0 31", "b4b3"},
  {"r4r2/2q1Nb2/5Qpk/2n4p/pp5P/8/1PP2PP1/2KR3R w - - 0 29", "e7f5"},
  {"6k1/p4pp1/1p5p/4b3/4B3/4P1P1/P1R2PKP/1q1r4 w - - 0 31", "c2c8"},
  {"4r1k1/p4p1p/1p6/6B1/3P2n1/P4Q2/1P4P1/7K b - - 0 34", "e8e1"},
  {"2kr3r/p1p1Rpp1/2p2n1p/8/8/1P6/P1P2PPP/RNB3K1 b - - 0 16", "d8d1"},
  {"r1bq3Q/1np3p1/p5k1/1p1Pp3/1Pn2BP1/2b2P2/P3K3/R4N2 w - - 0 36", "h8h5"},
  {"5k2/p2r3p/1p4pP/3r1q2/4R3/2P5/PP3PQ1/K3R3 b - - 0 33", "d5d1"},
}};
inline constexpr std::array<Case, 12> mateIn3{{
  {"6nr/p4p1p/k1p5/1p6/1QN5/2P1P3/4KPqP/8 w - - 0 27", "b4a5"},
  {"4rr1k/p1Qn2pp/3p1q2/8/8/2P5/PP3PPP/RN3RK1 b - - 0 16", "f6f2"},
  {"1r6/pp2kppQ/2n1p1n1/3p2P1/5P2/2PqP3/PP1N4/2KR3R b - - 4 27", "c6b4"},
  {"rn3rk1/4pp1p/3p2pB/2q4P/3QP1b1/Pp6/1P2B3/1K1R2NR b - - 0 20", "c5c2"},
  {"2k1r3/pppn1pp1/3b2b1/3B2Pp/5P2/3P3P/PPPR4/2K3NR b - - 0 18", "e8e1"},
  {"r6r/pp2kb2/3p1p2/1N1Pp3/3bP3/P2B2P1/1P1Q2PP/7K b - - 7 28", "h8h2"},
  {"2k3r1/pppb1prp/1q6/8/Q7/2P1R1P1/P4P1P/4R1K1 w - - 4 24", "e3e8"},
  {"1n5k/6p1/p2q1rPp/1ppB4/8/3P4/PPP1rPQ1/2K4R w - - 0 26", "h1h6"},
  {"3R4/1pp1r1kp/4r1p1/p1P5/5Q2/P4PPq/1P5P/3R2K1 b - - 3 32", "e6e1"},
  {"8/2p4r/1p3k2/p2PR1p1/P1P2pP1/1P3P1r/4R1K1/8 b - - 0 46", "h3h2"},
  {"r1qr3k/pp3pb1/1np1p3/8/3P3P/2N2PR1/PP1Q2P1/2KR4 w - - 0 23", "d2g5"},
  {"r5k1/pp2q1p1/2p1p2p/3nP1pP/3P2P1/2PQ1r2/PPB5/R5K1 w - - 0 24", "d3h7"},
}};
}  // namespace tactical_data
