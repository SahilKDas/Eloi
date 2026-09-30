//! Narrow audited Win32 leaf. Chess, networking, and rendering remain safe Rust.
#![allow(
    clippy::borrow_as_ptr,
    clippy::cast_lossless,
    clippy::cast_possible_truncation,
    clippy::cast_precision_loss,
    clippy::chunks_exact_to_as_chunks,
    clippy::collapsible_if,
    clippy::default_trait_access,
    clippy::too_many_lines
)]

use std::io;
use std::io::Write;
use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::ptr::{null, null_mut};
use std::sync::Arc;

use windows_sys::Win32::Foundation::{
    ERROR_ALREADY_EXISTS, GetLastError, HWND, LPARAM, LRESULT, WPARAM,
};
use windows_sys::Win32::Graphics::Gdi::{
    BI_RGB, BITMAPINFO, BITMAPINFOHEADER, BeginPaint, DIB_RGB_COLORS, EndPaint, InvalidateRect,
    PAINTSTRUCT, SRCCOPY, SetBkMode, SetTextColor, StretchDIBits, TextOutW, UpdateWindow,
};
use windows_sys::Win32::System::LibraryLoader::GetModuleHandleW;
use windows_sys::Win32::System::Threading::CreateMutexW;
use windows_sys::Win32::UI::WindowsAndMessaging::{
    CREATESTRUCTW, CS_HREDRAW, CS_VREDRAW, CW_USEDEFAULT, CreateWindowExW, DefWindowProcW,
    DestroyWindow, DispatchMessageW, FindWindowW, GWLP_USERDATA, GetClientRect, GetMessageW,
    GetWindowLongPtrW, IDC_ARROW, KillTimer, LoadCursorW, MSG, PostQuitMessage, RegisterClassW,
    SW_RESTORE, SW_SHOW, SetForegroundWindow, SetTimer, SetWindowLongPtrW, ShowWindow,
    TranslateMessage, WM_CLOSE, WM_DESTROY, WM_ERASEBKGND, WM_LBUTTONUP, WM_MOUSEMOVE, WM_NCCREATE,
    WM_PAINT, WM_TIMER, WNDCLASSW, WS_OVERLAPPEDWINDOW, WS_VISIBLE,
};

use crate::{OperationsModel, Surface, SurfaceKind};
use eloi_core::Square8;
use eloi_core::Variant;
use eloi_core::game::Game;
use eloi_core::position::INITIAL_FEN;

struct WindowState {
    kind: SurfaceKind,
    hover_control: Option<usize>,
    hover_amount: f32,
    game: Option<Game>,
    selected: Option<Square8>,
    operations: Option<Arc<OperationsModel>>,
    config_path: Option<PathBuf>,
    tick: u8,
}

fn wide(value: &str) -> Vec<u16> {
    value.encode_utf16().chain(Some(0)).collect()
}

pub(super) fn run(
    kind: SurfaceKind,
    operations: Option<Arc<OperationsModel>>,
    config_path: Option<PathBuf>,
    start: Option<Box<dyn FnOnce() + Send>>,
) -> io::Result<()> {
    // SAFETY: this module is the sole platform leaf; every pointer comes from
    // Win32 or a Box retained until WM_DESTROY, and all strings are NUL-terminated.
    unsafe {
        let class = wide("EloiRustTinySkiaWindow");
        let mutex_name = wide("Local\\EloiRustOperationsCenter");
        if kind == SurfaceKind::Operations {
            let _mutex = CreateMutexW(null(), 0, mutex_name.as_ptr());
            if GetLastError() == ERROR_ALREADY_EXISTS {
                let existing = FindWindowW(class.as_ptr(), null());
                if !existing.is_null() {
                    ShowWindow(existing, SW_RESTORE);
                    SetForegroundWindow(existing);
                }
                return Ok(());
            }
        }
        let instance = GetModuleHandleW(null());
        let registration = WNDCLASSW {
            style: CS_HREDRAW | CS_VREDRAW,
            lpfnWndProc: Some(window_proc),
            hInstance: instance,
            hCursor: LoadCursorW(null_mut(), IDC_ARROW),
            lpszClassName: class.as_ptr(),
            ..Default::default()
        };
        if RegisterClassW(&registration) == 0 && GetLastError() != 1410 {
            return Err(io::Error::last_os_error());
        }
        let title = wide(match kind {
            SurfaceKind::Chess => "Eloi 3.9 — Native Chess",
            SurfaceKind::FourPlayer => "Eloi 4.0 — Four-Player Chess",
            SurfaceKind::Operations => "Eloi 3.9 — Lichess Operations Center",
        });
        let state = Box::into_raw(Box::new(WindowState {
            kind,
            hover_control: None,
            hover_amount: 0.0,
            game: (kind == SurfaceKind::Chess)
                .then(|| Game::from_fen(INITIAL_FEN, Variant::Standard).ok())
                .flatten(),
            selected: None,
            operations,
            config_path,
            tick: 0,
        }));
        let window = CreateWindowExW(
            0,
            class.as_ptr(),
            title.as_ptr(),
            WS_OVERLAPPEDWINDOW | WS_VISIBLE,
            CW_USEDEFAULT,
            CW_USEDEFAULT,
            1040,
            780,
            null_mut(),
            null_mut(),
            instance,
            state.cast(),
        );
        if window.is_null() {
            drop(Box::from_raw(state));
            return Err(io::Error::last_os_error());
        }
        ShowWindow(window, SW_SHOW);
        UpdateWindow(window);
        SetTimer(window, 1, 16, None);
        if let Some(start) = start {
            std::thread::Builder::new()
                .name("eloi-lichess-supervisor".into())
                .spawn(start)?;
        }
        let mut message = MSG::default();
        loop {
            let result = GetMessageW(&mut message, null_mut(), 0, 0);
            if result == -1 {
                return Err(io::Error::last_os_error());
            }
            if result == 0 {
                break;
            }
            TranslateMessage(&message);
            DispatchMessageW(&message);
        }
    }
    Ok(())
}

unsafe extern "system" fn window_proc(
    window: HWND,
    message: u32,
    wparam: WPARAM,
    lparam: LPARAM,
) -> LRESULT {
    if message == WM_NCCREATE {
        // SAFETY: WM_NCCREATE lParam is a valid CREATESTRUCTW for this call.
        let create = unsafe { &*(lparam as *const CREATESTRUCTW) };
        unsafe { SetWindowLongPtrW(window, GWLP_USERDATA, create.lpCreateParams as isize) };
    }
    let state = unsafe { GetWindowLongPtrW(window, GWLP_USERDATA) as *mut WindowState };
    match message {
        WM_PAINT if !state.is_null() => {
            unsafe { paint(window, &*state) };
            0
        }
        WM_MOUSEMOVE if !state.is_null() => {
            let x = (lparam as i16) as i32;
            let y = ((lparam >> 16) as i16) as i32;
            let mut rect = Default::default();
            unsafe { GetClientRect(window, &mut rect) };
            let hover = if x >= rect.right - 240 && x <= rect.right - 32 {
                (0..5).find(|index| {
                    let top = 108 + i32::try_from(*index).unwrap_or(0) * 58;
                    (top..=top + 46).contains(&y)
                })
            } else {
                None
            };
            unsafe { (*state).hover_control = hover };
            0
        }
        WM_LBUTTONUP if !state.is_null() => {
            let x = (lparam as i16) as i32;
            let y = ((lparam >> 16) as i16) as i32;
            unsafe { board_click(window, &mut *state, x, y) };
            if unsafe { (*state).kind == SurfaceKind::Operations }
                && let Some(control) = unsafe { (*state).hover_control }
            {
                unsafe { operations_click(&*state, control) };
            }
            unsafe { (*state).hover_control = None };
            unsafe { InvalidateRect(window, null(), 0) };
            0
        }
        WM_TIMER if !state.is_null() => {
            unsafe { (*state).tick = (*state).tick.wrapping_add(1) };
            let target = if unsafe { (*state).hover_control.is_some() } {
                1.0
            } else {
                0.0
            };
            let current = unsafe { (*state).hover_amount };
            let next = current + (target - current) * 0.22;
            if (next - current).abs() > 0.001 {
                unsafe { (*state).hover_amount = next };
                unsafe { InvalidateRect(window, null(), 0) };
            }
            if unsafe { (*state).kind == SurfaceKind::Operations && (*state).tick % 15 == 0 } {
                unsafe { InvalidateRect(window, null(), 0) };
            }
            0
        }
        WM_ERASEBKGND => 1,
        WM_CLOSE => {
            if !state.is_null()
                && let Some(model) = unsafe { &(*state).operations }
            {
                model.request_stop();
            }
            unsafe { DestroyWindow(window) };
            0
        }
        WM_DESTROY => {
            unsafe { KillTimer(window, 1) };
            if !state.is_null() {
                unsafe { drop(Box::from_raw(state)) };
                unsafe { SetWindowLongPtrW(window, GWLP_USERDATA, 0) };
            }
            unsafe { PostQuitMessage(0) };
            0
        }
        _ => unsafe { DefWindowProcW(window, message, wparam, lparam) },
    }
}

unsafe fn paint(window: HWND, state: &WindowState) {
    let mut paint_state = PAINTSTRUCT::default();
    let dc = unsafe { BeginPaint(window, &mut paint_state) };
    let mut client = Default::default();
    unsafe { GetClientRect(window, &mut client) };
    let width = u32::try_from(client.right.max(1)).unwrap_or(1);
    let height = u32::try_from(client.bottom.max(1)).unwrap_or(1);
    if let Some(surface) = Surface::render(
        width,
        height,
        state.kind,
        state.hover_amount,
        state.hover_control,
        state.game.as_ref().map(Game::position),
    ) {
        let mut bgra = surface.rgba().to_vec();
        for pixel in bgra.chunks_exact_mut(4) {
            pixel.swap(0, 2);
        }
        let info = BITMAPINFO {
            bmiHeader: BITMAPINFOHEADER {
                biSize: u32::try_from(std::mem::size_of::<BITMAPINFOHEADER>()).unwrap_or(0),
                biWidth: i32::try_from(width).unwrap_or(1),
                biHeight: -i32::try_from(height).unwrap_or(1),
                biPlanes: 1,
                biBitCount: 32,
                biCompression: BI_RGB,
                ..Default::default()
            },
            ..Default::default()
        };
        unsafe {
            StretchDIBits(
                dc,
                0,
                0,
                client.right,
                client.bottom,
                0,
                0,
                i32::try_from(width).unwrap_or(1),
                i32::try_from(height).unwrap_or(1),
                bgra.as_ptr().cast(),
                &info,
                DIB_RGB_COLORS,
                SRCCOPY,
            )
        };
    }
    if state.kind == SurfaceKind::Operations {
        unsafe { draw_operations(window, dc, state) };
    }
    unsafe { EndPaint(window, &paint_state) };
}

unsafe fn draw_operations(
    window: HWND,
    dc: windows_sys::Win32::Graphics::Gdi::HDC,
    state: &WindowState,
) {
    let snapshot = state
        .operations
        .as_ref()
        .map(|model| model.snapshot())
        .unwrap_or_default();
    let state_name = match snapshot.state {
        1 => "Connecting",
        2 => "Connected",
        3 => "Playing",
        4 => "Backing off",
        5 => "Fatal",
        6 => "Stopping",
        _ => "Stopped",
    };
    let lines = [
        "Eloi Lichess Operations Center".to_owned(),
        format!("State: {state_name}"),
        format!(
            "Account: {}  HTTP: {}  reconnects: {}  next retry: {}s",
            display_or_dash(&snapshot.account),
            snapshot.http_status,
            snapshot.attempts,
            snapshot.retry_seconds
        ),
        format!(
            "Accepting challenges: {}",
            if snapshot.accepting { "yes" } else { "no" }
        ),
        format!(
            "Challenges accepted/declined: {}/{}",
            snapshot.accepted, snapshot.declined
        ),
        format!(
            "W/D/L: {}/{}/{}",
            snapshot.wins, snapshot.draws, snapshot.losses
        ),
        format!("Protocol incidents: {}", snapshot.incidents),
        format!(
            "Game: {}  variant: {}  ply: {}  clocks: {} / {} ms",
            display_or_dash(&snapshot.game),
            display_or_dash(&snapshot.variant),
            snapshot.ply,
            snapshot.white_ms,
            snapshot.black_ms
        ),
        format!(
            "Route: {}  network: {}",
            display_or_dash(&snapshot.route),
            clipped(&snapshot.network, 24)
        ),
        format!(
            "Move: {}  depth: {}  score: {}  nodes: {}  time: {} ms",
            display_or_dash(&snapshot.latest_move),
            snapshot.depth,
            snapshot.score,
            snapshot.nodes,
            snapshot.elapsed_ms
        ),
        format!("Stop: {}", display_or_dash(&snapshot.stop_reason)),
        format!("PV: {}", clipped(&snapshot.pv, 72)),
        format!("Latest event: {}", clipped(&snapshot.latest_event, 72)),
        "Controls remain local; diagnostics never include the token.".to_owned(),
    ];
    unsafe { SetBkMode(dc, 1) };
    unsafe { SetTextColor(dc, 0x00E8_E2D8) };
    for (index, line) in lines.iter().enumerate() {
        let text: Vec<u16> = line.encode_utf16().collect();
        unsafe {
            TextOutW(
                dc,
                54,
                28 + i32::try_from(index).unwrap_or(0) * 23,
                text.as_ptr(),
                i32::try_from(text.len()).unwrap_or(0),
            )
        };
    }
    let labels = [
        if snapshot.accepting {
            "Stop accepting"
        } else {
            "Start accepting"
        },
        "Reconnect now",
        "Configure",
        "Copy diagnostics",
        "Open log folder",
    ];
    for (index, label) in labels.iter().enumerate() {
        let text: Vec<u16> = label.encode_utf16().collect();
        let mut client = Default::default();
        unsafe { GetClientRect(window, &mut client) };
        unsafe {
            TextOutW(
                dc,
                client.right - 218,
                122 + i32::try_from(index).unwrap_or(0) * 58,
                text.as_ptr(),
                i32::try_from(text.len()).unwrap_or(0),
            )
        };
    }
}

fn display_or_dash(value: &str) -> &str {
    if value.is_empty() { "—" } else { value }
}

fn clipped(value: &str, maximum: usize) -> String {
    let mut result = value.chars().take(maximum).collect::<String>();
    if value.chars().count() > maximum {
        result.push('…');
    }
    if result.is_empty() {
        "—".into()
    } else {
        result
    }
}

unsafe fn operations_click(state: &WindowState, control: usize) {
    let Some(model) = &state.operations else {
        return;
    };
    match control {
        0 => model.toggle_accepting(),
        1 => model.request_reconnect(),
        2 => {
            if let Some(path) = &state.config_path {
                let _ = Command::new("notepad.exe").arg(path).spawn();
            }
        }
        3 => {
            let snapshot = model.snapshot();
            let diagnostic = format!(
                "Eloi Operations Center\r\nstate={}\r\naccount={}\r\naccepting={}\r\nchallenge_accept/decline={}/{}\r\nW/D/L={}/{}/{}\r\nincidents={}\r\ngame={}\r\nvariant={}\r\nroute={}\r\nnetwork={}\r\nmove={}\r\ndepth={}\r\nscore={}\r\nnodes={}\r\nelapsed_ms={}\r\nstop={}\r\npv={}\r\n",
                snapshot.state,
                snapshot.account,
                snapshot.accepting,
                snapshot.accepted,
                snapshot.declined,
                snapshot.wins,
                snapshot.draws,
                snapshot.losses,
                snapshot.incidents,
                snapshot.game,
                snapshot.variant,
                snapshot.route,
                snapshot.network,
                snapshot.latest_move,
                snapshot.depth,
                snapshot.score,
                snapshot.nodes,
                snapshot.elapsed_ms,
                snapshot.stop_reason,
                snapshot.pv
            );
            if let Ok(mut child) = Command::new("clip.exe").stdin(Stdio::piped()).spawn() {
                if let Some(mut input) = child.stdin.take() {
                    let _ = input.write_all(diagnostic.as_bytes());
                }
            }
        }
        4 => {
            if let Some(local) = std::env::var_os("LOCALAPPDATA") {
                let folder = PathBuf::from(local)
                    .join("Eloi")
                    .join("logs")
                    .join("lichess");
                let _ = std::fs::create_dir_all(&folder);
                let _ = Command::new("explorer.exe").arg(folder).spawn();
            }
        }
        _ => {}
    }
}

unsafe fn board_click(window: HWND, state: &mut WindowState, x: i32, y: i32) {
    let Some(game) = state.game.as_mut() else {
        return;
    };
    let mut client = Default::default();
    unsafe { GetClientRect(window, &mut client) };
    let size = (client.right.min(client.bottom).saturating_sub(230) as f32).max(160.0);
    let file = ((x as f32 - 44.0) / (size / 8.0)).floor() as i32;
    let row = ((y as f32 - 196.0) / (size / 8.0)).floor() as i32;
    if !(0..8).contains(&file) || !(0..8).contains(&row) {
        state.selected = None;
        return;
    }
    let index = (7 - row) * 8 + file;
    let Some(square) = u8::try_from(index).ok().and_then(Square8::new) else {
        return;
    };
    if let Some(from) = state.selected.take() {
        if let Some(mv) = game.position().legal_moves().into_iter().find(|mv| {
            mv.from == Some(from)
                && mv.to == square
                && (mv.promotion.is_none() || mv.promotion == Some(eloi_core::PieceKind::Queen))
        }) {
            let _ = game.push(mv);
            return;
        }
    }
    if game
        .position()
        .at(square)
        .is_some_and(|piece| piece.owner == game.position().turn)
    {
        state.selected = Some(square);
    }
}
