#include "eloi/lichess_operations.hpp"

#include "eloi/config.hpp"
#include "eloi/version.hpp"
#include "eloi/version_match.hpp"

#ifdef _WIN32

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <windowsx.h>
#include <shellapi.h>

#include "include/core/SkCanvas.h"
#include "include/core/SkColor.h"
#include "include/core/SkFont.h"
#include "include/core/SkGraphics.h"
#include "include/core/SkImageInfo.h"
#include "include/core/SkPaint.h"
#include "include/core/SkPixmap.h"
#include "include/core/SkSurface.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <thread>

namespace eloi {
namespace {

constexpr UINT refresh_timer = 1;
constexpr UINT show_existing_message = WM_APP + 41;
constexpr int toggle_button = 2001;
constexpr int reconnect_button = 2002;
constexpr int configure_button = 2003;
constexpr int copy_button = 2004;
constexpr int logs_button = 2005;
constexpr int exit_button = 2006;
constexpr wchar_t operations_class[] = L"EloiLichessOperationsCenter";

std::wstring wide(std::string_view text) {
  if (text.empty()) return {};
  const int count = MultiByteToWideChar(CP_UTF8, 0, text.data(),
      static_cast<int>(text.size()), nullptr, 0);
  std::wstring result(count, L'\0');
  MultiByteToWideChar(CP_UTF8, 0, text.data(), static_cast<int>(text.size()),
                      result.data(), count);
  return result;
}

std::string iso_time(std::chrono::system_clock::time_point value) {
  const auto raw = std::chrono::system_clock::to_time_t(value);
  std::tm tm{};
  gmtime_s(&tm, &raw);
  std::ostringstream out;
  out << std::put_time(&tm, "%Y-%m-%dT%H:%M:%SZ");
  return out.str();
}

std::string json_escape_ops(std::string_view text) {
  std::string out;
  for (const unsigned char c : text) {
    if (c == '\\') out += "\\\\";
    else if (c == '"') out += "\\\"";
    else if (c == '\n') out += "\\n";
    else if (c == '\r') out += "\\r";
    else if (c == '\t') out += "\\t";
    else if (c >= 0x20) out += static_cast<char>(c);
  }
  return out;
}

std::filesystem::path operations_root() {
  if (const wchar_t* local = _wgetenv(L"LOCALAPPDATA"); local && *local)
    return std::filesystem::path(local) / "Eloi";
  return std::filesystem::temp_directory_path() / "Eloi";
}

std::filesystem::path argument_config(int argc, char** argv) {
  for (int i = 1; i + 1 < argc; ++i)
    if (std::string_view(argv[i]) == "--config") return argv[i + 1];
  std::wstring path(32768, L'\0');
  const DWORD size = GetModuleFileNameW(nullptr, path.data(),
                                        static_cast<DWORD>(path.size()));
  path.resize(size);
  return std::filesystem::path(path).parent_path() / "config.yml";
}

struct Dashboard {
  BridgeController* controller{};
  HWND window{};
  std::filesystem::path executable;
  std::filesystem::path config;
  BridgeSnapshot snapshot;
  POINT mouse{-1, -1};
  bool tracking{};
  std::array<float, 6> hover{};
  std::chrono::steady_clock::time_point visual_tick{std::chrono::steady_clock::now()};
};

struct Rect { float l{}, t{}, r{}, b{}; bool contains(float x,float y) const{return x>=l&&x<=r&&y>=t&&y<=b;} SkRect sk()const{return SkRect::MakeLTRB(l,t,r,b);} };
constexpr SkColor ui_bg=SkColorSetRGB(16,17,31), ui_card=SkColorSetRGB(27,31,46);
constexpr SkColor ui_ink=SkColorSetRGB(235,239,248), ui_muted=SkColorSetRGB(144,153,176);
constexpr SkColor ui_accent=SkColorSetRGB(121,101,255), ui_mint=SkColorSetRGB(62,211,166);

SkColor mix(SkColor a,SkColor b,float x){x=std::clamp(x,0.f,1.f);auto c=[x](int p,int q){return static_cast<U8CPU>(std::lround(p+(q-p)*x));};return SkColorSetARGB(c(SkColorGetA(a),SkColorGetA(b)),c(SkColorGetR(a),SkColorGetR(b)),c(SkColorGetG(a),SkColorGetG(b)),c(SkColorGetB(a),SkColorGetB(b)));}
void sk_text(SkCanvas& c,std::string_view s,float x,float y,float size,SkColor color=ui_ink,bool bold=false){SkPaint p;p.setAntiAlias(true);p.setColor(color);SkFont f(nullptr,size);f.setEmbolden(bold);c.drawSimpleText(s.data(),s.size(),SkTextEncoding::kUTF8,x,y,f,p);}
void card(SkCanvas& c,const Rect& r,float radius=18,SkColor color=ui_card){SkPaint p;p.setAntiAlias(true);p.setColor(color);c.drawRoundRect(r.sk(),radius,radius,p);p.setStyle(SkPaint::kStroke_Style);p.setStrokeWidth(1);p.setColor(SkColorSetARGB(75,125,130,165));c.drawRoundRect(r.sk(),radius,radius,p);}
std::array<Rect,6> action_rects(int w,int h){const float y=static_cast<float>(h)-70.f,g=10.f;const float widths[]={150,138,110,154,112,82};float total=g*5;for(float x:widths)total+=x;float left=(w-total)/2;std::array<Rect,6> out{};for(int i=0;i<6;++i){out[i]={left,y,left+widths[i],y+43};left+=widths[i]+g;}return out;}
void draw_button(SkCanvas& c,const Rect& base,std::string_view label,float hover,SkColor fill){const float z=hover*2.2f,lift=hover*1.5f;Rect r{base.l-z,base.t-z-lift,base.r+z,base.b+z-lift};card(c,{r.l+1,r.t+5,r.r+1,r.b+5},13,SkColorSetARGB(65+static_cast<int>(hover*35),0,0,0));card(c,r,13,mix(fill,SkColorSetRGB(73,78,105),hover*.45f));const float estimate=label.size()*7.0f;sk_text(c,label,(r.l+r.r-estimate)/2,(r.t+r.b)/2+5,14,ui_ink,true);}
std::string shorten(std::string value,std::size_t n){if(value.size()>n&&n>3){value.resize(n-3);value+="...";}return value;}
std::string uptime_text(const BridgeSnapshot& s){auto sec=std::chrono::duration_cast<std::chrono::seconds>(std::chrono::system_clock::now()-s.started_at).count();return std::format("{:02}:{:02}:{:02}",sec/3600,(sec/60)%60,sec%60);}

std::string diagnostics(const BridgeSnapshot& s) {
  std::ostringstream out;
  out << "Eloi " << s.version << "\nstate: " << bridge_state_name(s.state)
      << "\nexecutable: " << s.executable_sha256
      << "\naccount: " << s.account
      << "\nhttp: " << s.last_http_status
      << "\nreconnects: " << s.reconnect_attempts
      << "\naccepting: " << (s.accepting ? "yes" : "no")
      << "\ngame: " << s.active_game_id << " " << s.variant
      << "\nroute: " << s.brain_route << "\nnetwork: " << s.network_sha256
      << "\nsearch: depth " << s.depth << " score " << s.score_cp
      << " nodes " << s.nodes << " time " << s.elapsed_ms << "ms"
      << "\nlast error: " << s.last_error;
  return redact_bridge_text(out.str());
}

void refresh(Dashboard& ui) {
  ui.snapshot=ui.controller->snapshot();
  InvalidateRect(ui.window,nullptr,FALSE);
}

void draw_dashboard(Dashboard& ui,SkCanvas& c,int w,int h){const auto&s=ui.snapshot;SkPaint bg;bg.setColor(ui_bg);c.drawPaint(bg);SkPaint glow;glow.setAntiAlias(true);glow.setColor(SkColorSetARGB(30,121,101,255));c.drawCircle(w-70,30,230,glow);glow.setColor(SkColorSetARGB(15,62,211,166));c.drawCircle(10,h-20,180,glow);
  sk_text(c,"ELOI",32,49,30,ui_ink,true);sk_text(c,"LICHESS OPERATIONS CENTER",131,45,14,ui_muted,true);sk_text(c,"v"+s.version+"  ·  "+uptime_text(s),w-190,44,13,ui_muted);
  const bool healthy=s.state==BridgeState::connected||s.state==BridgeState::playing;SkColor state_color=healthy?ui_mint:(s.state==BridgeState::fatal?SkColorSetRGB(255,99,112):SkColorSetRGB(255,205,92));
  card(c,{28,70,static_cast<float>(w)-28,126},17,SkColorSetRGB(31,35,52));SkPaint dot;dot.setAntiAlias(true);dot.setColor(state_color);c.drawCircle(51,98,7,dot);sk_text(c,std::string(bridge_state_name(s.state)),70,104,20,state_color,true);sk_text(c,s.account.empty()?"awaiting account":s.account,220,103,15,ui_ink,true);const bool operational=s.state!=BridgeState::fatal&&s.state!=BridgeState::stopped&&s.state!=BridgeState::stopping;sk_text(c,operational&&s.accepting?"CHALLENGES OPEN":"CHALLENGES PAUSED",w-210,102,12,operational&&s.accepting?ui_mint:ui_muted,true);
  const float gap=16,left=28,right=w-28,mid=(left+right-gap)/2;card(c,{left,142,mid,334});card(c,{mid+gap,142,right,334});
  sk_text(c,"ACTIVE GAME",left+20,171,12,ui_muted,true);sk_text(c,s.active_game_id.empty()?"No game in progress":s.opponent,left+20,205,22,ui_ink,true);sk_text(c,s.active_game_id.empty()?"Ready for the next challenge":std::format("{} · {} · ply {}",s.variant,s.color,s.ply),left+20,231,14,ui_muted);const auto clock_label=[](std::int64_t ms){return ms<0?std::string("—"):std::format("{} ms",ms);};sk_text(c,"WHITE  "+clock_label(s.white_time_ms),left+20,272,14,ui_ink,true);sk_text(c,"BLACK  "+clock_label(s.black_time_ms),left+210,272,14,ui_ink,true);sk_text(c,"Last result  "+(s.last_result.empty()?std::string("—"):s.last_result),left+20,309,13,ui_muted);
  sk_text(c,"SEARCH TELEMETRY",mid+gap+20,171,12,ui_muted,true);sk_text(c,s.brain_route.empty()?"Awaiting search":s.brain_route,mid+gap+20,205,22,ui_ink,true);sk_text(c,"Network  "+(s.network_sha256.empty()?std::string("—"):s.network_sha256.substr(0,14)),mid+gap+20,231,13,ui_muted);sk_text(c,std::format("{}   d{}   {:+.2f}   {} nodes   {} ms",s.latest_move.empty()?"—":s.latest_move,s.depth,s.score_cp/100.0,s.nodes,s.elapsed_ms),mid+gap+20,270,14,ui_ink,true);sk_text(c,"PV  "+shorten(s.pv,52),mid+gap+20,302,13,ui_muted);sk_text(c,"Stop  "+(s.stop_reason.empty()?std::string("—"):s.stop_reason),mid+gap+20,321,12,ui_muted);
  card(c,{left,350,right,420});sk_text(c,"SESSION",left+18,377,11,ui_muted,true);sk_text(c,std::format("{}W  {}D  {}L",s.completed_wins,s.completed_draws,s.completed_losses),left+18,405,20,ui_ink,true);sk_text(c,std::format("CHALLENGES  {} / {}",s.accepted,s.declined),left+200,402,13,ui_muted,true);sk_text(c,std::format("CAISSA FAILURES  {}    FALLBACKS  {}    EMERGENCY  {}    PROTOCOL  {}",s.caissa_failures,s.eloi_fallbacks,s.emergency_moves,s.protocol_incidents),left+430,402,12,(s.protocol_incidents||s.emergency_moves)?SkColorSetRGB(255,205,92):ui_muted,true);
  card(c,{left,436,right,static_cast<float>(h)-91});sk_text(c,"LIVE EVENT TIMELINE",left+18,464,11,ui_muted,true);float y=491;const std::size_t max_rows=std::max(1,(h-600)/22+4);const std::size_t start=s.events.size()>max_rows?s.events.size()-max_rows:0;for(std::size_t i=start;i<s.events.size();++i){const auto&e=s.events[i];SkPaint d;d.setAntiAlias(true);d.setColor(e.error?SkColorSetRGB(255,99,112):ui_mint);c.drawCircle(left+22,y-5,3,d);sk_text(c,shorten(iso_time(e.at).substr(11,8)+"  "+e.message,120),left+36,y,12,e.error?SkColorSetRGB(255,145,153):ui_muted);y+=22;}
  const auto actions=action_rects(w,h);const std::array<std::string,6> labels{s.accepting?"STOP ACCEPTING":"START ACCEPTING","RECONNECT NOW","CONFIGURE","COPY DIAGNOSTICS","OPEN LOGS","EXIT"};for(int i=0;i<6;++i)draw_button(c,actions[i],labels[i],ui.hover[i],i==0?ui_accent:(i==5?SkColorSetRGB(116,51,67):SkColorSetRGB(35,40,57)));
}

void copy_text(HWND window, const std::string& text) {
  const std::wstring value = wide(text);
  if (!OpenClipboard(window)) return;
  EmptyClipboard();
  const SIZE_T bytes = (value.size() + 1) * sizeof(wchar_t);
  HGLOBAL memory = GlobalAlloc(GMEM_MOVEABLE, bytes);
  if (memory) {
    std::memcpy(GlobalLock(memory), value.c_str(), bytes);
    GlobalUnlock(memory);
    SetClipboardData(CF_UNICODETEXT, memory);
  }
  CloseClipboard();
}

LRESULT CALLBACK dashboard_proc(HWND window, UINT message,
                                WPARAM wparam, LPARAM lparam) {
  auto* ui = reinterpret_cast<Dashboard*>(GetWindowLongPtrW(
      window, GWLP_USERDATA));
  if (message == WM_NCCREATE) {
    ui = static_cast<Dashboard*>(
        reinterpret_cast<CREATESTRUCTW*>(lparam)->lpCreateParams);
    SetWindowLongPtrW(window, GWLP_USERDATA, reinterpret_cast<LONG_PTR>(ui));
    ui->window = window;
  }
  if (!ui) return DefWindowProcW(window, message, wparam, lparam);
  if (message == WM_TIMER) {
    const auto now=std::chrono::steady_clock::now();
    const float dt=std::clamp(std::chrono::duration<float>(now-ui->visual_tick).count(),0.f,.1f);
    ui->visual_tick=now;
    RECT client{};GetClientRect(window,&client);const auto rects=action_rects(client.right,client.bottom);
    bool changed=false;const float response=1.f-std::exp(-dt*14.f);
    for(std::size_t i=0;i<ui->hover.size();++i){const float target=ui->tracking&&rects[i].contains(static_cast<float>(ui->mouse.x),static_cast<float>(ui->mouse.y))?1.f:0.f;const float old=ui->hover[i];ui->hover[i]+=(target-ui->hover[i])*response;changed|=std::abs(old-ui->hover[i])>.002f;}
    static unsigned ticks=0;if((ticks++%30)==0)refresh(*ui);else if(changed)InvalidateRect(window,nullptr,FALSE);
    return 0;
  }
  if (message == show_existing_message) {
    ShowWindow(window, SW_RESTORE);
    SetForegroundWindow(window);
    return 0;
  }
  if(message==WM_MOUSEMOVE){ui->mouse={GET_X_LPARAM(lparam),GET_Y_LPARAM(lparam)};if(!ui->tracking){TRACKMOUSEEVENT t{sizeof(t),TME_LEAVE,window,0};TrackMouseEvent(&t);ui->tracking=true;}return 0;}
  if(message==WM_MOUSELEAVE){ui->tracking=false;ui->mouse={-1,-1};return 0;}
  if(message==WM_LBUTTONUP){RECT client{};GetClientRect(window,&client);const auto buttons=action_rects(client.right,client.bottom);int command=0;for(int i=0;i<6;++i)if(buttons[i].contains(static_cast<float>(GET_X_LPARAM(lparam)),static_cast<float>(GET_Y_LPARAM(lparam))))command=toggle_button+i;switch(command){
      case toggle_button: ui->controller->toggle_accepting(); break;
      case reconnect_button: ui->controller->request_reconnect(); break;
      case configure_button: {
        std::wstring args = L"--lichess --configure --config \"" +
                            ui->config.wstring() + L"\"";
        ShellExecuteW(window, L"open", ui->executable.c_str(), args.c_str(),
                      ui->executable.parent_path().c_str(), SW_SHOWNORMAL);
        break;
      }
      case copy_button: copy_text(window, diagnostics(ui->controller->snapshot())); break;
      case logs_button:
        ShellExecuteW(window, L"open", ui->controller->log_directory().c_str(),
                      nullptr, nullptr, SW_SHOWNORMAL);
        break;
      case exit_button: SendMessageW(window, WM_CLOSE, 0, 0); break;
    }refresh(*ui);return 0;
  }
  if(message==WM_ERASEBKGND)return 1;
  if(message==WM_PAINT){PAINTSTRUCT ps{};HDC dc=BeginPaint(window,&ps);RECT client{};GetClientRect(window,&client);const int w=std::max(1L,client.right),h=std::max(1L,client.bottom);auto surface=SkSurface::MakeRaster(SkImageInfo::MakeN32Premul(w,h));if(surface){draw_dashboard(*ui,*surface->getCanvas(),w,h);SkPixmap pixels;if(surface->peekPixels(&pixels)){BITMAPINFO bitmap{};bitmap.bmiHeader.biSize=sizeof(BITMAPINFOHEADER);bitmap.bmiHeader.biWidth=w;bitmap.bmiHeader.biHeight=-h;bitmap.bmiHeader.biPlanes=1;bitmap.bmiHeader.biBitCount=32;bitmap.bmiHeader.biCompression=BI_RGB;StretchDIBits(dc,0,0,w,h,0,0,w,h,pixels.addr(),&bitmap,DIB_RGB_COLORS,SRCCOPY);}}EndPaint(window,&ps);return 0;}
  if (message == WM_CLOSE) {
    const auto s = ui->controller->snapshot();
    if (s.active_game && MessageBoxW(window,
          L"A game is active. Stopping now may forfeit or time out the game. Exit immediately?",
          L"Stop Eloi Lichess", MB_YESNO | MB_ICONWARNING) != IDYES)
      return 0;
    ui->controller->request_stop();
    DestroyWindow(window);
    return 0;
  }
  if (message == WM_DESTROY) {
    PostQuitMessage(0);
    return 0;
  }
  return DefWindowProcW(window, message, wparam, lparam);
}

}  // namespace

std::string_view bridge_state_name(BridgeState state) {
  switch (state) {
    case BridgeState::stopped: return "stopped";
    case BridgeState::connecting: return "connecting";
    case BridgeState::connected: return "connected";
    case BridgeState::playing: return "playing";
    case BridgeState::backing_off: return "backing off";
    case BridgeState::fatal: return "fatal";
    case BridgeState::stopping: return "stopping";
  }
  return "unknown";
}

BridgeController::BridgeController(std::filesystem::path executable,
                                   std::filesystem::path config)
    : executable_(std::move(executable)), config_path_(std::move(config)) {
  snapshot_.version = std::string(version);
  snapshot_.executable_sha256 = sha256_file(executable_);
  snapshot_.started_at = std::chrono::system_clock::now();
  const auto root = operations_root();
  log_directory_ = root / "logs" / "lichess";
  status_path_ = root / "status" / "lichess.json";
  std::error_code error;
  std::filesystem::create_directories(log_directory_, error);
  std::filesystem::create_directories(status_path_.parent_path(), error);
  rotate_logs();
  const auto stamp = std::chrono::system_clock::to_time_t(snapshot_.started_at);
  log_path_ = log_directory_ / ("bridge-" + std::to_string(stamp) + ".log");
}

BridgeController::~BridgeController() { request_stop(); }

void BridgeController::rotate_logs() {
  std::error_code error;
  std::vector<std::filesystem::directory_entry> files;
  for (const auto& item : std::filesystem::directory_iterator(log_directory_, error))
    if (item.is_regular_file() && item.path().extension() == ".log") files.push_back(item);
  std::ranges::sort(files, {}, [](const auto& item) {
    std::error_code ignored; return item.last_write_time(ignored);
  });
  std::uintmax_t total{};
  for (const auto& item : files) total += item.file_size(error);
  while (files.size() >= 10 || total > 10u * 1024u * 1024u) {
    const auto size = files.front().file_size(error);
    std::filesystem::remove(files.front().path(), error);
    total = total > size ? total - size : 0;
    files.erase(files.begin());
  }
}

void BridgeController::persist_event_locked(const BridgeEvent& event) {
  std::ofstream output(log_path_, std::ios::app);
  output << iso_time(event.at) << ' ' << bridge_state_name(event.state) << ' '
         << (event.error ? "ERROR " : "")
         << redact_bridge_text(event.message) << '\n';
  output.close();
  rotate_logs();
}

void BridgeController::write_snapshot_locked() const {
  const auto temporary = status_path_.string() + ".new";
  std::ofstream out(temporary, std::ios::trunc);
  out << "{\n  \"schema\": \"eloi-lichess-operations-v1\",\n"
      << "  \"version\": \"" << json_escape_ops(snapshot_.version) << "\",\n"
      << "  \"state\": \"" << bridge_state_name(snapshot_.state) << "\",\n"
      << "  \"account\": \"" << json_escape_ops(snapshot_.account) << "\",\n"
      << "  \"accepting\": " << (snapshot_.accepting ? "true" : "false") << ",\n"
      << "  \"active_game_id\": \"" << json_escape_ops(snapshot_.active_game_id) << "\",\n"
      << "  \"variant\": \"" << json_escape_ops(snapshot_.variant) << "\",\n"
      << "  \"brain_route\": \"" << json_escape_ops(snapshot_.brain_route) << "\",\n"
      << "  \"network_sha256\": \"" << json_escape_ops(snapshot_.network_sha256) << "\",\n"
      << "  \"latest_move\": \"" << json_escape_ops(snapshot_.latest_move) << "\",\n"
      << "  \"depth\": " << snapshot_.depth << ",\n"
      << "  \"score_cp\": " << snapshot_.score_cp << ",\n"
      << "  \"nodes\": " << snapshot_.nodes << ",\n"
      << "  \"elapsed_ms\": " << snapshot_.elapsed_ms << ",\n"
      << "  \"last_http_status\": " << snapshot_.last_http_status << ",\n"
      << "  \"reconnect_attempts\": " << snapshot_.reconnect_attempts << ",\n"
      << "  \"accepted_challenges\": " << snapshot_.accepted << ",\n"
      << "  \"declined_challenges\": " << snapshot_.declined << ",\n"
      << "  \"completed_wins\": " << snapshot_.completed_wins << ",\n"
      << "  \"completed_draws\": " << snapshot_.completed_draws << ",\n"
      << "  \"completed_losses\": " << snapshot_.completed_losses << ",\n"
      << "  \"protocol_incidents\": " << snapshot_.protocol_incidents << ",\n"
      << "  \"last_error\": \"" << json_escape_ops(snapshot_.last_error) << "\"\n}\n";
  out.close();
  MoveFileExW(std::filesystem::path(temporary).c_str(), status_path_.c_str(),
              MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH);
}

void BridgeController::publish(BridgeEvent event) {
  std::scoped_lock lock(mutex_);
  event.message = redact_bridge_text(event.message);
  snapshot_.events.push_back(event);
  if (snapshot_.events.size() > 300) snapshot_.events.erase(snapshot_.events.begin());
  if (event.error) snapshot_.last_error = event.message;
  persist_event_locked(event);
  write_snapshot_locked();
  std::cout << event.message << '\n';
}

void BridgeController::transition(BridgeState state, std::string message,
                                  bool error) {
  {
    std::scoped_lock lock(mutex_);
    snapshot_.state = state;
    if (error) snapshot_.last_error = redact_bridge_text(message);
  }
  if (!message.empty()) publish({std::chrono::system_clock::now(), state,
                                 std::move(message), error});
}

#define ELOI_OPS_LOCK std::scoped_lock lock(mutex_)
void BridgeController::set_account(std::string value) { ELOI_OPS_LOCK; snapshot_.account=std::move(value); write_snapshot_locked(); }
void BridgeController::set_configuration(std::string value) { ELOI_OPS_LOCK; snapshot_.enabled_variants=std::move(value); write_snapshot_locked(); }
void BridgeController::set_http_status(int value) { ELOI_OPS_LOCK; snapshot_.last_http_status=value; write_snapshot_locked(); }
void BridgeController::set_retry(int a,int s) { ELOI_OPS_LOCK; snapshot_.reconnect_attempts=a; snapshot_.next_retry_seconds=s; write_snapshot_locked(); }
void BridgeController::begin_game(std::string id,std::string variant,std::string opponent,std::string color) { ELOI_OPS_LOCK; snapshot_.active_game=true; snapshot_.active_game_id=std::move(id); snapshot_.variant=std::move(variant); snapshot_.opponent=std::move(opponent); snapshot_.color=std::move(color); snapshot_.state=BridgeState::playing; write_snapshot_locked(); }
void BridgeController::update_game_clock(int p,std::int64_t w,std::int64_t b) { ELOI_OPS_LOCK; snapshot_.ply=p; snapshot_.white_time_ms=w; snapshot_.black_time_ms=b; }
void BridgeController::record_search(std::string route,std::string network,std::string move,int depth,int score,std::uint64_t nodes,std::int64_t elapsed,std::string pv,std::string reason) { ELOI_OPS_LOCK; snapshot_.brain_route=std::move(route); snapshot_.network_sha256=std::move(network); snapshot_.latest_move=std::move(move); snapshot_.depth=depth; snapshot_.score_cp=score; snapshot_.nodes=nodes; snapshot_.elapsed_ms=elapsed; snapshot_.pv=std::move(pv); snapshot_.stop_reason=std::move(reason); write_snapshot_locked(); }
void BridgeController::end_game(std::string result) { ELOI_OPS_LOCK; if(result=="win")++snapshot_.completed_wins; else if(result=="draw")++snapshot_.completed_draws; else if(result=="loss")++snapshot_.completed_losses; snapshot_.last_result=std::move(result); snapshot_.active_game=false; snapshot_.active_game_id.clear(); snapshot_.state=BridgeState::connected; write_snapshot_locked(); }
void BridgeController::record_challenge(bool accepted) { ELOI_OPS_LOCK; if (accepted) ++snapshot_.accepted; else ++snapshot_.declined; }
void BridgeController::record_caissa_failure(bool fallback,bool emergency) { ELOI_OPS_LOCK; if (fallback) { ++snapshot_.caissa_failures; ++snapshot_.eloi_fallbacks; } if(emergency)++snapshot_.emergency_moves; }
void BridgeController::protocol_incident(std::string message) { { ELOI_OPS_LOCK; ++snapshot_.protocol_incidents; } publish({std::chrono::system_clock::now(),snapshot().state,std::move(message),true}); }
#undef ELOI_OPS_LOCK

BridgeSnapshot BridgeController::snapshot() const { std::scoped_lock lock(mutex_); return snapshot_; }
bool BridgeController::accepting() const { std::scoped_lock lock(mutex_); return snapshot_.accepting; }
void BridgeController::toggle_accepting() { { std::scoped_lock lock(mutex_); snapshot_.accepting=!snapshot_.accepting; write_snapshot_locked(); } condition_.notify_all(); }
bool BridgeController::stop_requested() const { std::scoped_lock lock(mutex_); return snapshot_.stop_requested; }
bool BridgeController::reconnect_requested() const { std::scoped_lock lock(mutex_); return reconnect_requested_; }
void BridgeController::clear_reconnect() { std::scoped_lock lock(mutex_); reconnect_requested_=false; }
void BridgeController::request_reconnect() { std::function<void()> cancel; { std::scoped_lock lock(mutex_); reconnect_requested_=true; cancel=cancel_callback_; } if(cancel)cancel(); condition_.notify_all(); }
void BridgeController::request_stop() { std::function<void()> cancel; { std::scoped_lock lock(mutex_); snapshot_.stop_requested=true; snapshot_.state=BridgeState::stopping; cancel=cancel_callback_; } if(cancel)cancel(); condition_.notify_all(); }
void BridgeController::set_cancel_callback(std::function<void()> cb) { std::scoped_lock lock(mutex_); cancel_callback_=std::move(cb); }
bool BridgeController::wait_backoff(int seconds) { std::unique_lock lock(mutex_); return !condition_.wait_for(lock,std::chrono::seconds(seconds),[&]{return snapshot_.stop_requested||reconnect_requested_;}); }

int run_lichess_operations_center(int argc, char** argv) {
  SkGraphics::Init();
  HANDLE mutex = CreateMutexW(nullptr, FALSE, L"Local\\EloiLichessOperationsCenter-v1");
  if (!mutex) return 2;
  if (GetLastError() == ERROR_ALREADY_EXISTS) {
    if (HWND existing = FindWindowW(operations_class, nullptr))
      PostMessageW(existing, show_existing_message, 0, 0);
    CloseHandle(mutex);
    return 0;
  }
  std::wstring executable_text(32768, L'\0');
  const DWORD length = GetModuleFileNameW(nullptr, executable_text.data(),
                                          static_cast<DWORD>(executable_text.size()));
  executable_text.resize(length);
  const std::filesystem::path executable(executable_text);
  Dashboard ui;
  ui.executable = executable;
  ui.config = argument_config(argc, argv);
  BridgeController controller(executable, ui.config);
  ui.controller = &controller;

  WNDCLASSEXW wc{}; wc.cbSize=sizeof(wc); wc.lpfnWndProc=dashboard_proc;
  wc.hInstance=GetModuleHandleW(nullptr);
  wc.hCursor=LoadCursorW(nullptr, MAKEINTRESOURCEW(32512));
  wc.hbrBackground=nullptr; wc.lpszClassName=operations_class;
  RegisterClassExW(&wc);
  ui.window=CreateWindowExW(0,operations_class,L"Eloi Lichess Operations Center",
      WS_OVERLAPPEDWINDOW,CW_USEDEFAULT,CW_USEDEFAULT,1120,820,nullptr,nullptr,
      GetModuleHandleW(nullptr),&ui);
  refresh(ui);
  SetTimer(ui.window,refresh_timer,16,nullptr);
  ShowWindow(ui.window,SW_SHOW); UpdateWindow(ui.window);

  std::thread worker([&] { run_lichess(argc, argv, &controller); });
  MSG message{};
  while(GetMessageW(&message,nullptr,0,0)>0){TranslateMessage(&message);DispatchMessageW(&message);}
  controller.request_stop();
  if(worker.joinable())worker.join();
  CloseHandle(mutex);
  return 0;
}

}  // namespace eloi

#else
namespace eloi {
std::string_view bridge_state_name(BridgeState){return "unsupported";}
int bridge_backoff_seconds(int retry){return retry<1?2:60;}
bool bridge_http_retryable(int status){return status==0||status==408||status==429||status>=500;}
bool bridge_http_fatal(int status){return status==401||status==403;}
std::string redact_bridge_text(std::string_view value){return std::string(value);}
int run_lichess_operations_center(int,char**){return 2;}
}
#endif
