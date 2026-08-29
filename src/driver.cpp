#include "eloi/chess.hpp"

#include <algorithm>
#include <chrono>
#include <cstdlib>
#include <fstream>
#include <iostream>
#include <mutex>
#include <sstream>
#include <thread>

namespace eloi {
namespace {

std::vector<std::string> words(std::string_view line) {
  std::istringstream input{std::string(line)};
  std::vector<std::string> result;
  for (std::string word; input >> word;) result.push_back(word);
  return result;
}

std::optional<int> integer(std::string_view text) {
  try {
    std::size_t used = 0;
    int value = std::stoi(std::string(text), &used);
    if (used == text.size()) return value;
  } catch (...) {}
  return std::nullopt;
}

void print_info(const SearchResult& result, std::mutex& output) {
  std::lock_guard lock(output);
  if (!result.opening_family.empty())
    std::cout << "info string opening " << result.opening_family << '\n';
  std::cout << "info depth " << result.depth << " score ";
  if (result.mate) std::cout << "mate " << result.mate;
  else std::cout << "cp " << result.score_cp;
  std::cout << " nodes " << result.nodes << " time " << result.elapsed.count();
  if (result.elapsed.count() > 0)
    std::cout << " nps " << result.nodes * 1000 / static_cast<std::uint64_t>(result.elapsed.count());
  if (!result.pv.empty()) {
    std::cout << " pv";
    for (const Move& move : result.pv) std::cout << ' ' << move.uci();
  }
  std::cout << '\n'
            << "info string search qnodes " << result.qnodes
            << " tthits " << result.tt_hits
            << " cutoffs " << result.beta_cutoffs
            << " lmr " << result.lmr_reductions << std::endl;
}

void usage(const EngineConfig& config, const char* program) {
  std::cerr << "usage: " << program << " [options]\n\n"
            << config.name << " C++26 NNUE chess engine. Send 'uci' or 'console' on stdin.\n"
            << "  --ply N       default search depth (0-40; 0 searches up to 40)\n"
            << "  --noise N     evaluation noise in millipawns\n"
            << "  --hash N      transposition table size in MB\n"
            << "  --move-overhead N  clock/network safety margin in ms\n";
  if (config.kind == EngineKind::bernstein)
    std::cerr << "  --branch N    plausible-move branch limit\n"
              << "  --material N  material evaluation multiplier\n";
}

void parse_engine_options(EngineConfig& config, int argc, char** argv) {
  for (int i = 1; i < argc; ++i) {
    std::string arg = argv[i];
    auto take = [&](int& target) {
      if (i + 1 < argc) if (auto n = integer(argv[++i])) target = *n;
    };
    if (arg == "--ply" || arg == "-ply") take(config.depth);
    else if (arg == "--noise" || arg == "-noise") take(config.noise_millipawns);
    else if (arg == "--hash" || arg == "-hash") take(config.hash_mb);
    else if (arg == "--move-overhead") take(config.move_overhead_ms);
    else if (arg == "--branch" || arg == "-branch") take(config.branch);
    else if (arg == "--material" || arg == "-material") take(config.material_factor);
    else if (arg == "--help" || arg == "-h" || arg == "-help") {
      usage(config, argv[0]);
      std::exit(0);
    }
  }
  config.depth = std::clamp(config.depth, 0, maximum_search_depth);
  config.move_overhead_ms = std::clamp(config.move_overhead_ms, 0, 5000);
}

int run_console(EngineConfig config, Board board) {
  std::cout << "engine " << config.name << " 1.0.0 (" << config.author << ")\n"
            << board_ascii(board) << std::flush;
  std::atomic_bool stopped{false};
  for (std::string line; std::getline(std::cin, line);) {
    auto args = words(line);
    if (args.empty()) continue;
    std::string cmd = args[0];
    std::transform(cmd.begin(), cmd.end(), cmd.begin(), [](unsigned char c){ return std::tolower(c); });
    if (cmd == "quit" || cmd == "exit" || cmd == "q") break;
    if (cmd == "print" || cmd == "p") std::cout << board_ascii(board);
    else if (cmd == "undo" || cmd == "u") { board.pop(); std::cout << board_ascii(board); }
    else if (cmd == "depth" || cmd == "d") {
      if (args.size() > 1)
        if (auto n = integer(args[1]))
          config.depth = std::clamp(*n, 0, maximum_search_depth);
    }
    else if (cmd == "noise") { if (args.size() > 1) if (auto n=integer(args[1])) config.noise_millipawns=*n; }
    else if (cmd == "hash") { if (args.size() > 1) if (auto n=integer(args[1])) config.hash_mb=*n; }
    else if (cmd == "nonoise") config.noise_millipawns = 0;
    else if (cmd == "nohash") config.hash_mb = 0;
    else if (cmd == "reset" || cmd == "r") {
      std::string fen(initial_fen);
      if (args.size() >= 7) {
        fen.clear(); for (int i=1;i<=6;++i) { if(i>1)fen+=' '; fen+=args[i]; }
      }
      std::string error; auto parsed=parse_fen(fen,&error);
      if (parsed) { board=*parsed; std::cout << board_ascii(board); }
      else std::cout << "invalid position: " << error << '\n';
    } else if (cmd == "analyze" || cmd == "a") {
      SearchLimits limits; limits.depth = config.depth > 0 ? config.depth : 6;
      if (args.size() > 1) if (auto n=integer(args[1]))
        limits.depth=std::clamp(*n, 1, maximum_search_depth);
      stopped = false; Searcher searcher(config, stopped);
      auto result = searcher.iterative(board, limits, [&](const SearchResult& r) {
        std::cout << "depth=" << r.depth << " score=" << r.score_cp << " nodes=" << r.nodes << " pv=";
        for (const auto& m:r.pv) std::cout << m.describe() << ' ';
        std::cout << '\n';
      });
      if (!result.pv.empty()) std::cout << "bestmove " << result.pv.front().describe() << '\n';
    } else if (board.push_uci(args[0])) std::cout << board_ascii(board);
    else std::cout << "invalid move: '" << args[0] << "'\n";
    std::cout.flush();
  }
  return 0;
}

}  // namespace

int run_engine(EngineConfig config, int argc, char** argv) {
  parse_engine_options(config, argc, argv);
  auto initial = parse_fen(initial_fen);
  if (!initial) return 2;
  Board board = *initial;
  std::string first;
  if (!std::getline(std::cin, first)) { usage(config, argv[0]); return 2; }
  if (first == "console") return run_console(config, board);
  if (first != "uci") { usage(config, argv[0]); return 2; }

  std::cout << "id name " << config.name << " 1.0.0\n"
            << "id author " << config.author << "\n"
            << "option name Depth type spin default " << config.depth << " min 0 max " << maximum_search_depth << "\n"
            << "option name Hash type spin default " << config.hash_mb << " min 0 max 16384\n"
            << "option name Move Overhead type spin default " << config.move_overhead_ms << " min 0 max 5000\n"
            << "option name Noise type spin default " << config.noise_millipawns << " min 0 max 10000\n";
  if (config.own_book) std::cout << "option name OwnBook type check default true\n";
  std::cout << "uciok" << std::endl;

  std::atomic_bool stopped{false}, active{false};
  std::thread worker;
  std::mutex output;
  auto stop_worker = [&] {
    stopped = true;
    if (worker.joinable()) worker.join();
    active = false;
  };
  auto launch = [&](SearchLimits limits) {
    stop_worker(); stopped = false; active = true;
    Board snapshot = board; EngineConfig current = config;
    worker = std::thread([&, snapshot=std::move(snapshot), current=std::move(current), limits]() mutable {
      Searcher searcher(current, stopped);
      SearchResult result = searcher.iterative(
          snapshot, limits,
          [&](const SearchResult& info){ print_info(info, output); });
      {
        std::lock_guard lock(output);
        std::cout << "bestmove " << (result.pv.empty() ? "0000" : result.pv.front().uci()) << std::endl;
      }
      active = false;
    });
  };

  for (std::string line; std::getline(std::cin, line);) {
    auto args = words(line); if (args.empty()) continue;
    std::string cmd=args[0];
    std::transform(cmd.begin(),cmd.end(),cmd.begin(),[](unsigned char c){return std::tolower(c);});
    if (cmd == "quit") { stop_worker(); break; }
    if (cmd == "isready") { std::lock_guard lock(output); std::cout << "readyok" << std::endl; continue; }
    if (cmd == "stop") { stop_worker(); continue; }
    if (cmd == "ucinewgame") { stop_worker(); board=*initial; continue; }
    if (cmd == "setoption") {
      stop_worker();
      auto name=std::find(args.begin(),args.end(),"name"), value=std::find(args.begin(),args.end(),"value");
      if(name!=args.end()&&value!=args.end()&&name+1<args.end()&&value+1<args.end()) {
        std::string key=*(name+1), val=*(value+1);
        if(auto n=integer(val)) {
          if(key=="Depth") {
            if(*n < 0 || *n > maximum_search_depth)
              std::cout << "info string Depth must be between 0 and 40; request ignored" << std::endl;
            else config.depth=*n;
          } else if(key=="Hash")config.hash_mb=*n;
          else if(key=="Move Overhead")config.move_overhead_ms=std::clamp(*n,0,5000);
          else if(key=="Noise")config.noise_millipawns=*n;
        }
        if(key=="OwnBook") config.own_book=(val=="true"||val=="1");
      }
      continue;
    }
    if (cmd == "position") {
      stop_worker(); std::size_t index=1;
      if(index<args.size()&&args[index]=="startpos") {board=*initial;++index;}
      else if(index<args.size()&&args[index]=="fen"&&index+6<args.size()) {
        std::string fen; for(int i=0;i<6;++i){if(i)fen+=' ';fen+=args[index+1+i];}
        std::string error; auto parsed=parse_fen(fen,&error);
        if(!parsed){std::lock_guard lock(output);std::cout<<"info string invalid FEN: "<<error<<std::endl;continue;}
        board=*parsed; index+=7;
      }
      if(index<args.size()&&args[index]=="moves")++index;
      for(;index<args.size();++index) if(!board.push_uci(args[index])) {
        std::lock_guard lock(output);std::cout<<"info string invalid move "<<args[index]<<std::endl;break;
      }
      continue;
    }
    if (cmd == "go") {
      SearchLimits limits; limits.depth=config.depth;
      int movetime=0,wtime=0,btime=0,winc=0,binc=0,moves_to_go=0;
      for(std::size_t i=1;i<args.size();++i) {
        auto take=[&](){if(i+1<args.size())return integer(args[++i]).value_or(0);return 0;};
        if(args[i]=="depth")limits.depth=std::clamp(take(),1,maximum_search_depth); else if(args[i]=="nodes")limits.nodes=static_cast<std::uint64_t>(std::max(0,take()));
        else if(args[i]=="movetime")movetime=take(); else if(args[i]=="wtime")wtime=take();
        else if(args[i]=="btime")btime=take(); else if(args[i]=="movestogo")moves_to_go=take();
        else if(args[i]=="winc")winc=take(); else if(args[i]=="binc")binc=take();
        else if(args[i]=="infinite")limits.depth=0;
      }
      limits.move_overhead_ms=config.move_overhead_ms;
      if(movetime>0) {
        limits.deadline=std::chrono::steady_clock::now()+
            std::chrono::milliseconds(std::max(1,movetime-config.move_overhead_ms));
      } else if(wtime||btime) {
        limits.remaining_ms=board.turn==Color::white?wtime:btime;
        limits.increment_ms=board.turn==Color::white?winc:binc;
        limits.moves_to_go=moves_to_go;
      }
      launch(limits); continue;
    }
  }
  stop_worker();
  return 0;
}

int run_perft(int argc, char** argv) {
  int depth=4; bool divide=false; std::string fen(initial_fen);
  for(int i=1;i<argc;++i){std::string arg=argv[i];
    if((arg=="--depth"||arg=="-depth")&&i+1<argc)depth=integer(argv[++i]).value_or(depth);
    else if((arg=="--fen"||arg=="-fen")&&i+1<argc)fen=argv[++i];
    else if(arg=="--divide"||arg=="-divide")divide=true;
    else if(arg=="--help"||arg=="-h"){std::cout<<"usage: perft [--depth N] [--fen FEN] [--divide]\n";return 0;}
  }
  std::string error;auto board=parse_fen(fen,&error);if(!board){std::cerr<<"invalid FEN: "<<error<<'\n';return 2;}
  for(int d=1;d<=depth;++d){auto start=std::chrono::steady_clock::now();std::vector<std::pair<Move,std::uint64_t>> rows;
    auto nodes=perft(board->position,board->turn,d,divide&&d==depth?&rows:nullptr);
    if(divide&&d==depth)for(auto&[m,n]:rows)std::cout<<m.uci()<<": "<<n<<'\n';
    auto us=std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::steady_clock::now()-start).count();
    std::cout<<"perft,"<<fen<<','<<d<<','<<nodes<<','<<us<<"us\n";
  }
  return 0;
}

int run_benchmark(int argc, char** argv) {
  int depth = 6;
  for (int i = 1; i + 1 < argc; ++i)
    if (std::string_view(argv[i]) == "--depth")
      depth = std::clamp(integer(argv[++i]).value_or(depth), 1,
                         maximum_search_depth);
  constexpr std::array positions{
      initial_fen,
      std::string_view{"r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1"},
      std::string_view{"2r2rk1/pp1bqppp/2n1pn2/1B1p4/3P4/2N1PN2/PPQ2PPP/2RR2K1 w - - 3 14"},
      std::string_view{"8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1"}};
  auto config = default_config(EngineKind::eloi);
  config.own_book = false;
  config.depth = depth;
  std::atomic_bool stopped{false};
  std::uint64_t nodes = 0, qnodes = 0, hits = 0, cutoffs = 0, lmr = 0;
  std::chrono::milliseconds elapsed{};
  std::uint64_t checksum = 0;
  for (std::string_view fen : positions) {
    auto board = parse_fen(fen);
    if (!board) return 2;
    Searcher searcher(config, stopped);
    SearchLimits limits; limits.depth = depth;
    const auto result = searcher.iterative(*board, limits);
    nodes += result.nodes; qnodes += result.qnodes; hits += result.tt_hits;
    cutoffs += result.beta_cutoffs; lmr += result.lmr_reductions;
    elapsed += result.elapsed;
    checksum = checksum * 1315423911ULL +
        static_cast<std::uint64_t>(result.score_cp + 32000);
    if (!result.pv.empty())
      checksum ^= static_cast<std::uint64_t>(result.pv.front().from * 64 +
                                             result.pv.front().to);
    std::cout << "bench depth " << result.depth << " nodes " << result.nodes
              << " time " << result.elapsed.count() << " bestmove "
              << (result.pv.empty() ? "0000" : result.pv.front().uci()) << '\n';
  }
  const auto milliseconds = std::max<std::int64_t>(1, elapsed.count());
  std::cout << "bench summary depth " << depth << " nodes " << nodes
            << " qnodes " << qnodes << " time " << elapsed.count()
            << " nps " << nodes * 1000 / static_cast<std::uint64_t>(milliseconds)
            << " tthits " << hits << " cutoffs " << cutoffs
            << " lmr " << lmr << " checksum " << checksum << '\n';
  return 0;
}

int run_livechess_adapter(int argc, char** argv) {
  std::string feed;
  for(int i=1;i<argc;++i)if((std::string(argv[i])=="--feed"||std::string(argv[i])=="-feed")&&i+1<argc)feed=argv[++i];
  if(feed.empty()) {
    std::cerr << "livechess-uci uses a dependency-free line feed. Pass --feed FILE, where FILE emits one FEN piece-placement field per line.\n";
    return 2;
  }
  std::ifstream input(feed);
  if(!input){std::cerr<<"cannot open live board feed: "<<feed<<'\n';return 2;}
  auto initial=parse_fen(initial_fen);if(!initial)return 2;Board board=*initial;
  std::string line;if(!std::getline(std::cin,line)||line!="uci")return 2;
  std::cout<<"id name livechess-uci 0.91.3\nid author herohde\nuciok"<<std::endl;
  for(;std::getline(std::cin,line);){auto args=words(line);if(args.empty())continue;
    if(args[0]=="quit")break;
    if(args[0]=="isready"){std::cout<<"readyok"<<std::endl;continue;}
    if(args[0]=="ucinewgame"){board=*initial;continue;}
    if(args[0]=="position"){
      std::size_t index=1;
      if(index<args.size()&&args[index]=="startpos"){board=*initial;++index;}
      else if(index<args.size()&&args[index]=="fen"&&index+6<args.size()){
        std::string fen;for(int i=0;i<6;++i){if(i)fen+=' ';fen+=args[index+1+i];}
        auto parsed=parse_fen(fen);if(!parsed){std::cout<<"info string invalid FEN"<<std::endl;continue;}
        board=*parsed;index+=7;
      }
      if(index<args.size()&&args[index]=="moves")++index;
      for(;index<args.size();++index)if(!board.push_uci(args[index]))
        std::cout<<"info string invalid move "<<args[index]<<std::endl;
      continue;
    }
    if(args[0]=="go"){
      std::unordered_map<std::string,Move> candidates;
      for(const Move& move:board.legal_moves()){
        Board next=board;next.push(move);auto fields=words(to_fen(next));candidates[fields.front()]=move;
      }
      if(candidates.empty()){std::cout<<"bestmove 0000"<<std::endl;continue;}
      bool found=false;
      for(std::string observed;std::getline(input,observed);){auto fields=words(observed);if(fields.empty())continue;
        if(auto match=candidates.find(fields.front());match!=candidates.end()){
          std::cout<<"info depth 1 score cp 0 nodes 1 pv "<<match->second.uci()<<'\n'
                   <<"bestmove "<<match->second.uci()<<std::endl;found=true;break;
        }
      }
      if(!found)std::cout<<"info string live board feed ended before a legal move was observed\nbestmove 0000"<<std::endl;
    }
  }
  return 0;
}

}  // namespace eloi
