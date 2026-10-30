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
    BI_RGB, BITMAPINFO, BITMAPINFOHEADER, BeginPaint, CLEARTYPE_QUALITY, CreateFontW,
    DEFAULT_CHARSET, DIB_RGB_COLORS, DT_CENTER, DT_END_ELLIPSIS, DT_NOPREFIX, DT_SINGLELINE,
    DT_VCENTER, DeleteObject, DrawTextW, EndPaint, InvalidateRect, PAINTSTRUCT, SRCCOPY,
    SelectObject, SetBkMode, SetTextColor, StretchDIBits, UpdateWindow,
};
use windows_sys::Win32::System::LibraryLoader::GetModuleHandleW;
use windows_sys::Win32::System::Threading::CreateMutexW;
use windows_sys::Win32::UI::Controls::WM_MOUSELEAVE;
use windows_sys::Win32::UI::Input::KeyboardAndMouse::{
    TME_LEAVE, TRACKMOUSEEVENT, TrackMouseEvent,
};
use windows_sys::Win32::UI::WindowsAndMessaging::{
    CREATESTRUCTW, CS_HREDRAW, CS_VREDRAW, CW_USEDEFAULT, CreateWindowExW, DefWindowProcW,
    DestroyWindow, DispatchMessageW, FindWindowW, GWLP_USERDATA, GetClientRect, GetMessageW,
    GetWindowLongPtrW, IDC_ARROW, IDYES, KillTimer, LoadCursorW, MB_ICONWARNING, MB_YESNO,
    MINMAXINFO, MSG, MessageBoxW, PostMessageW, PostQuitMessage, RegisterClassW, SW_RESTORE,
    SW_SHOW, SetForegroundWindow, SetTimer, SetWindowLongPtrW, ShowWindow, TranslateMessage,
    WM_CLOSE, WM_DESTROY, WM_ERASEBKGND, WM_GETMINMAXINFO, WM_LBUTTONUP, WM_MOUSEMOVE, WM_NCCREATE,
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
    four: Option<crate::four_player::FourTable>,
    started: std::time::Instant,
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
        let class = wide(if kind == SurfaceKind::Operations && operations.is_none() {
            "EloiRustOperationsPreviewWindow"
        } else if kind == SurfaceKind::Operations {
            "EloiRustOperationsCenterWindow"
        } else {
            "EloiRustTinySkiaWindow"
        });
        let mutex_name = wide("Local\\EloiRustOperationsCenter");
        if kind == SurfaceKind::Operations && operations.is_some() {
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
        let name = match kind {
            SurfaceKind::Chess => "Native Chess",
            SurfaceKind::FourPlayer => "Four-Player Teams",
            SurfaceKind::Operations if operations.is_none() => {
                "Lichess Operations Center — Offline Preview"
            }
            SurfaceKind::Operations => "Lichess Operations Center",
        };
        let title = wide(&format!("Eloi {} — {name}", env!("CARGO_PKG_VERSION")));
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
            four: (kind == SurfaceKind::FourPlayer).then(crate::four_player::FourTable::new),
            started: std::time::Instant::now(),
        }));
        let window = CreateWindowExW(
            0,
            class.as_ptr(),
            title.as_ptr(),
            WS_OVERLAPPEDWINDOW | WS_VISIBLE,
            CW_USEDEFAULT,
            CW_USEDEFAULT,
            if kind == SurfaceKind::Operations {
                1120
            } else {
                1040
            },
            if kind == SurfaceKind::Operations {
                820
            } else {
                780
            },
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
        WM_GETMINMAXINFO
            if !state.is_null() && unsafe { (*state).kind == SurfaceKind::FourPlayer } =>
        {
            let sizing = unsafe { &mut *(lparam as *mut MINMAXINFO) };
            sizing.ptMinTrackSize.x = 900;
            sizing.ptMinTrackSize.y = 760;
            0
        }
        WM_GETMINMAXINFO
            if !state.is_null() && unsafe { (*state).kind == SurfaceKind::Operations } =>
        {
            let sizing = unsafe { &mut *(lparam as *mut MINMAXINFO) };
            sizing.ptMinTrackSize.x = 940;
            sizing.ptMinTrackSize.y = 740;
            0
        }
        WM_PAINT if !state.is_null() => {
            unsafe { paint(window, &*state) };
            0
        }
        WM_MOUSEMOVE if !state.is_null() => {
            if unsafe { (*state).kind != SurfaceKind::Chess } {
                let mut tracking = TRACKMOUSEEVENT {
                    cbSize: std::mem::size_of::<TRACKMOUSEEVENT>() as u32,
                    dwFlags: TME_LEAVE,
                    hwndTrack: window,
                    dwHoverTime: 0,
                };
                unsafe { TrackMouseEvent(&mut tracking) };
            }
            let x = (lparam as i16) as i32;
            let y = ((lparam >> 16) as i16) as i32;
            let mut rect = Default::default();
            unsafe { GetClientRect(window, &mut rect) };
            let hover = if unsafe { (*state).kind == SurfaceKind::Operations } {
                crate::operations_view::hit(rect.right as u32, rect.bottom as u32, x, y)
            } else if unsafe { (*state).kind == SurfaceKind::FourPlayer } {
                if x >= rect.right - 240 && x <= rect.right - 32 {
                    (0..9).find(|i| {
                        let top = 196 + *i as i32 * 40;
                        (top..top + 34).contains(&y)
                    })
                } else {
                    None
                }
            } else if x >= rect.right - 240 && x <= rect.right - 32 {
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
        WM_MOUSELEAVE if !state.is_null() => {
            unsafe {
                (*state).hover_control = None;
                InvalidateRect(window, null(), 0)
            };
            0
        }
        WM_LBUTTONUP if !state.is_null() => {
            let x = (lparam as i16) as i32;
            let y = ((lparam >> 16) as i16) as i32;
            unsafe { board_click(window, &mut *state, x, y) };
            if unsafe { (*state).kind == SurfaceKind::Operations } {
                let mut rect = Default::default();
                unsafe { GetClientRect(window, &mut rect) };
                if let Some(control) =
                    crate::operations_view::hit(rect.right as u32, rect.bottom as u32, x, y)
                {
                    if control == 5 {
                        unsafe { PostMessageW(window, WM_CLOSE, 0, 0) };
                    } else {
                        unsafe { operations_click(&*state, control) };
                    }
                }
            }
            unsafe { (*state).hover_control = None };
            unsafe { InvalidateRect(window, null(), 0) };
            0
        }
        WM_TIMER if !state.is_null() => {
            if let Some(table) = unsafe { &mut (*state).four } {
                if table.tick() || unsafe { (*state).tick % 60 == 0 } {
                    unsafe { InvalidateRect(window, null(), 0) };
                }
            }
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
                if model.snapshot().state == 3
                    && unsafe {
                        MessageBoxW(window,wide("A game is active. Stopping now may forfeit the game. Exit immediately?").as_ptr(),wide("Stop Eloi Lichess").as_ptr(),MB_YESNO|MB_ICONWARNING)
                    } != IDYES
                {
                    return 0;
                }
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
    let surface = if state.kind == SurfaceKind::Operations {
        Surface::render_operations(
            width,
            height,
            state.hover_amount,
            state.hover_control,
            state
                .operations
                .as_ref()
                .map_or(0, |model| model.snapshot().state),
        )
    } else if let Some(table) = &state.four {
        Surface::render_four_hover(
            width,
            height,
            table.session.position(),
            table.selected,
            state.hover_amount,
            state.hover_control,
        )
        .map(|surface| surface.with_four_suggestion(width, height, table.suggestion()))
    } else {
        Surface::render(
            width,
            height,
            state.kind,
            state.hover_amount,
            state.hover_control,
            state.game.as_ref().map(Game::position),
        )
    };
    if let Some(surface) = surface {
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
    if let Some(table) = &state.four {
        unsafe { draw_four(dc, width, height, table) };
    }
    unsafe { EndPaint(window, &paint_state) };
}

unsafe fn ui_text(
    dc: windows_sys::Win32::Graphics::Gdi::HDC,
    value: &str,
    bounds: crate::operations_view::Bounds,
    size: i32,
    color: (u8, u8, u8),
    bold: bool,
    center: bool,
) {
    let face = wide("Segoe UI");
    let font = unsafe {
        CreateFontW(
            -size,
            0,
            0,
            0,
            if bold { 600 } else { 400 },
            0,
            0,
            0,
            DEFAULT_CHARSET as u32,
            0,
            0,
            CLEARTYPE_QUALITY as u32,
            0,
            face.as_ptr(),
        )
    };
    let previous = if font.is_null() {
        null_mut()
    } else {
        unsafe { SelectObject(dc, font) }
    };
    let text: Vec<u16> = value.encode_utf16().collect();
    let mut rect = windows_sys::Win32::Foundation::RECT {
        left: bounds.x as i32,
        top: bounds.y as i32,
        right: (bounds.x + bounds.w) as i32,
        bottom: (bounds.y + bounds.h) as i32,
    };
    unsafe {
        SetBkMode(dc, 1);
        SetTextColor(
            dc,
            u32::from(color.0) | (u32::from(color.1) << 8) | (u32::from(color.2) << 16),
        );
        DrawTextW(
            dc,
            text.as_ptr(),
            text.len() as i32,
            &mut rect,
            DT_SINGLELINE
                | DT_END_ELLIPSIS
                | DT_NOPREFIX
                | DT_VCENTER
                | if center { DT_CENTER } else { 0 },
        );
        if !font.is_null() {
            SelectObject(dc, previous);
            DeleteObject(font);
        }
    }
}

unsafe fn draw_operations(
    window: HWND,
    dc: windows_sys::Win32::Graphics::Gdi::HDC,
    state: &WindowState,
) {
    use crate::operations_view::Bounds;
    let mut client = Default::default();
    unsafe { GetClientRect(window, &mut client) };
    let (w, h) = (client.right as f32, client.bottom as f32);
    let snapshot = state
        .operations
        .as_ref()
        .map(|m| m.snapshot())
        .unwrap_or_default();
    let ink = (235, 239, 248);
    let muted = (144, 153, 176);
    let mint = (62, 211, 166);
    let state_name = match snapshot.state {
        1 => "Connecting",
        2 => "Connected",
        3 => "Playing",
        4 => "Backing off",
        5 => "Fatal",
        6 => "Stopping",
        _ if state.operations.is_none() => "Preview",
        _ => "Stopped",
    };
    let state_color = match snapshot.state {
        2 | 3 => mint,
        5 => (255, 99, 112),
        0 | 6 => muted,
        _ => (255, 205, 92),
    };
    let text = |value: &str, x: f32, y: f32, width: f32, size: i32, color, bold| unsafe {
        ui_text(
            dc,
            value,
            Bounds {
                x,
                y,
                w: width,
                h: size as f32 + 8.0,
            },
            size,
            color,
            bold,
            false,
        )
    };
    text("ELOI", 32.0, 19.0, 94.0, 32, ink, true);
    text(
        "LICHESS OPERATIONS CENTER",
        132.0,
        30.0,
        w - 360.0,
        14,
        muted,
        true,
    );
    let seconds = state.started.elapsed().as_secs();
    text(
        &format!(
            "v{}  ·  {:02}:{:02}:{:02}",
            env!("CARGO_PKG_VERSION"),
            seconds / 3600,
            seconds / 60 % 60,
            seconds % 60
        ),
        w - 225.0,
        29.0,
        200.0,
        15,
        muted,
        false,
    );
    text(state_name, 70.0, 82.0, 150.0, 22, state_color, true);
    text(
        if snapshot.account.is_empty() {
            "Awaiting account"
        } else {
            &snapshot.account
        },
        240.0,
        86.0,
        w - 500.0,
        17,
        ink,
        true,
    );
    let open = snapshot.accepting && matches!(snapshot.state, 1..=4);
    text(
        if open {
            "CHALLENGES OPEN"
        } else {
            "CHALLENGES PAUSED"
        },
        w - 226.0,
        87.0,
        198.0,
        14,
        if open { mint } else { muted },
        true,
    );
    let mid = (w - 16.0) / 2.0;
    let right = mid + 36.0;
    let cw = mid - 68.0;
    text("ACTIVE GAME", 48.0, 155.0, cw, 14, muted, true);
    text(
        if snapshot.game.is_empty() {
            "No game in progress"
        } else {
            &snapshot.game
        },
        48.0,
        185.0,
        cw,
        24,
        ink,
        true,
    );
    text(
        if snapshot.game.is_empty() {
            "Ready for the next challenge"
        } else {
            &snapshot.variant
        },
        48.0,
        222.0,
        cw,
        17,
        muted,
        false,
    );
    let clock = |ms: u64| format!("{:02}:{:02}", ms / 60000, ms / 1000 % 60);
    text(
        &format!(
            "WHITE  {}",
            if snapshot.game.is_empty() {
                "—".into()
            } else {
                clock(snapshot.white_ms)
            }
        ),
        48.0,
        263.0,
        cw / 2.0,
        17,
        ink,
        true,
    );
    text(
        &format!(
            "BLACK  {}",
            if snapshot.game.is_empty() {
                "—".into()
            } else {
                clock(snapshot.black_ms)
            }
        ),
        48.0 + cw / 2.0,
        263.0,
        cw / 2.0,
        17,
        ink,
        true,
    );
    text(
        &format!(
            "Ply {}  ·  HTTP {}  ·  Retry {}s",
            snapshot.ply, snapshot.http_status, snapshot.retry_seconds
        ),
        48.0,
        301.0,
        cw,
        15,
        muted,
        false,
    );
    text("SEARCH TELEMETRY", right, 155.0, cw, 14, muted, true);
    text(
        if snapshot.route.is_empty() {
            "Awaiting search"
        } else {
            &snapshot.route
        },
        right,
        185.0,
        cw,
        24,
        ink,
        true,
    );
    text(
        &format!("Network  {}", clipped(&snapshot.network, 32)),
        right,
        223.0,
        cw,
        15,
        muted,
        false,
    );
    text(
        &format!(
            "{}  ·  d{}  ·  {:+.2}  ·  {} nodes  ·  {} ms",
            display_or_dash(&snapshot.latest_move),
            snapshot.depth,
            snapshot.score as f64 / 100.0,
            snapshot.nodes,
            snapshot.elapsed_ms
        ),
        right,
        261.0,
        cw,
        17,
        ink,
        true,
    );
    text(
        &format!("PV  {}", display_or_dash(&snapshot.pv)),
        right,
        294.0,
        cw,
        15,
        muted,
        false,
    );
    text(
        &format!("Stop  {}", display_or_dash(&snapshot.stop_reason)),
        right,
        315.0,
        cw,
        13,
        muted,
        false,
    );
    text("SESSION", 46.0, 358.0, 160.0, 13, muted, true);
    text(
        &format!(
            "{}W  {}D  {}L",
            snapshot.wins, snapshot.draws, snapshot.losses
        ),
        46.0,
        385.0,
        210.0,
        22,
        ink,
        true,
    );
    text(
        &format!("CHALLENGES  {} / {}", snapshot.accepted, snapshot.declined),
        260.0,
        387.0,
        245.0,
        16,
        muted,
        true,
    );
    text(
        &format!(
            "RECONNECTS  {}     PROTOCOL  {}",
            snapshot.attempts, snapshot.incidents
        ),
        w - 430.0,
        387.0,
        370.0,
        15,
        if snapshot.incidents > 0 {
            (255, 205, 92)
        } else {
            muted
        },
        true,
    );
    text(
        "LIVE EVENT TIMELINE",
        46.0,
        446.0,
        w - 92.0,
        14,
        muted,
        true,
    );
    let max_rows = ((h - 568.0) / 24.0).max(1.0) as usize;
    let events = if snapshot.events.is_empty() {
        vec![if snapshot.latest_event.is_empty() {
            "Waiting for bridge events".into()
        } else {
            snapshot.latest_event.clone()
        }]
    } else {
        snapshot.events.clone()
    };
    let start = events.len().saturating_sub(max_rows);
    for (row, event) in events.iter().skip(start).enumerate() {
        text(
            &format!("•  {event}"),
            46.0,
            480.0 + row as f32 * 24.0,
            w - 92.0,
            15,
            muted,
            false,
        );
    }
    let labels = [
        if snapshot.accepting {
            "STOP ACCEPTING"
        } else {
            "START ACCEPTING"
        },
        "RECONNECT NOW",
        "CONFIGURE",
        "COPY DIAGNOSTICS",
        "OPEN LOGS",
        "EXIT",
    ];
    for (i, bounds) in crate::operations_view::actions(client.right as u32, client.bottom as u32)
        .into_iter()
        .enumerate()
    {
        unsafe { ui_text(dc, labels[i], bounds, 13, ink, true, true) };
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
    if let Some(table) = &mut state.four {
        let mut client = Default::default();
        unsafe { GetClientRect(window, &mut client) };
        if x >= client.right - 240 && x <= client.right - 32 {
            if (196..196 + 9 * 40).contains(&y) && (y - 196) % 40 < 34 {
                table.control(((y - 196) / 40) as usize);
            }
            return;
        }
        let size = (client.right.min(client.bottom).saturating_sub(180) as f32).max(210.0);
        let file = ((x as f32 - 44.0) / (size / 14.0)).floor() as i32;
        let row = ((y as f32 - 156.0) / (size / 14.0)).floor() as i32;
        if (0..14).contains(&file) && (0..14).contains(&row) {
            if let Some(sq) = eloi_core::Square14::new(file as u8, (13 - row) as u8) {
                table.click(sq);
            }
        }
        return;
    }
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

unsafe fn draw_four(
    dc: windows_sys::Win32::Graphics::Gdi::HDC,
    width: u32,
    height: u32,
    table: &crate::four_player::FourTable,
) {
    use crate::operations_view::Bounds;
    let ink = (235, 239, 248);
    let muted = (144, 153, 176);
    let text = |value: &str, x: f32, y: f32, w: f32, size: i32, color, bold| unsafe {
        ui_text(
            dc,
            value,
            Bounds {
                x,
                y,
                w,
                h: size as f32 + 7.0,
            },
            size,
            color,
            bold,
            false,
        )
    };
    let snapshot = table.session.snapshot();
    text("ELOI", 44.0, 22.0, 94.0, 30, ink, true);
    text("FOUR-PLAYER TEAMS", 146.0, 32.0, 280.0, 15, muted, true);
    text(
        "YOU  ·  RED + YELLOW",
        44.0,
        57.0,
        260.0,
        15,
        (250, 221, 95),
        true,
    );
    text(
        "ELOI  ·  BLUE + GREEN",
        320.0,
        57.0,
        280.0,
        15,
        (100, 224, 148),
        true,
    );
    let status = snapshot.outcome.as_ref().map_or_else(
        || {
            if table.paused {
                "Paused".into()
            } else {
                format!("Turn: {:?}", snapshot.turn)
            }
        },
        |outcome| match outcome {
            eloi_core::four_player::FourOutcome::TeamWin { red_yellow: true } => {
                "RED + YELLOW WIN".into()
            }
            eloi_core::four_player::FourOutcome::TeamWin { red_yellow: false } => {
                "BLUE + GREEN WIN".into()
            }
            _ => "DRAW".into(),
        },
    );
    text(
        &format!("{status}   ·   Ply {}", table.session.position().ply),
        54.0,
        90.0,
        width as f32 - 108.0,
        19,
        ink,
        true,
    );
    text(
        &table.message,
        54.0,
        119.0,
        width as f32 - 108.0,
        14,
        muted,
        false,
    );
    let think_label = format!("THINK: {} ms", table.budget_ms);
    let promotion_label = format!("PROMOTION: {:?}", table.promotion);
    let labels = [
        "NEW TEAM GAME",
        "PAUSE / RESUME",
        "UNDO TO YOUR TURN",
        "RESIGN YOUR TEAM",
        "FOUR HUMANS",
        "ALL ELOI DEMO",
        &think_label,
        &promotion_label,
        if table.show_suggestion {
            "SHOW SUGGESTION: ON"
        } else {
            "SHOW SUGGESTION: OFF"
        },
    ];
    text(
        "HANDCRAFTED TEAMS",
        width as f32 - 240.0,
        166.0,
        208.0,
        14,
        (177, 163, 255),
        true,
    );
    for (i, label) in labels.into_iter().enumerate() {
        unsafe {
            ui_text(
                dc,
                label,
                Bounds {
                    x: width as f32 - 240.0,
                    y: 196.0 + i as f32 * 40.0,
                    w: 208.0,
                    h: 34.0,
                },
                13,
                ink,
                true,
                true,
            )
        };
    }
    text(
        "WATCH ELOI THINK",
        width as f32 - 234.0,
        560.0,
        212.0,
        15,
        (177, 163, 255),
        true,
    );
    let line_gap = ((height as f32 - 634.0) / 7.0).clamp(12.0, 19.0);
    for (index, line) in table.think_lines().iter().enumerate() {
        text(
            line,
            width as f32 - 234.0,
            588.0 + index as f32 * line_gap,
            212.0,
            12,
            if index == 0 { ink } else { muted },
            index == 0,
        );
    }
    let clock = |i: usize| {
        let s = snapshot.clocks[i].remaining_ms / 1000;
        format!("{:02}:{:02}", s / 60, s % 60)
    };
    text(
        &format!(
            "RED {}   +   YELLOW {}       |       BLUE {}   +   GREEN {}",
            clock(0),
            clock(2),
            clock(1),
            clock(3)
        ),
        44.0,
        height as f32 - 27.0,
        width as f32 - 88.0,
        15,
        ink,
        true,
    );
}
