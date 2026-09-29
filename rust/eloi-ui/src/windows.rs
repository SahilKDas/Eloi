//! Narrow audited Win32 leaf. Chess, networking, and rendering remain safe Rust.
#![allow(
    clippy::borrow_as_ptr,
    clippy::cast_lossless,
    clippy::cast_possible_truncation,
    clippy::cast_precision_loss,
    clippy::chunks_exact_to_as_chunks,
    clippy::collapsible_if,
    clippy::default_trait_access
)]

use std::io;
use std::ptr::{null, null_mut};

use windows_sys::Win32::Foundation::{
    ERROR_ALREADY_EXISTS, GetLastError, HWND, LPARAM, LRESULT, WPARAM,
};
use windows_sys::Win32::Graphics::Gdi::{
    BI_RGB, BITMAPINFO, BITMAPINFOHEADER, BeginPaint, DIB_RGB_COLORS, EndPaint, InvalidateRect,
    PAINTSTRUCT, SRCCOPY, StretchDIBits, UpdateWindow,
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

use crate::{Surface, SurfaceKind};
use eloi_core::Square8;
use eloi_core::Variant;
use eloi_core::game::Game;
use eloi_core::position::INITIAL_FEN;

struct WindowState {
    kind: SurfaceKind,
    hover_target: bool,
    hover_amount: f32,
    game: Option<Game>,
    selected: Option<Square8>,
}

fn wide(value: &str) -> Vec<u16> {
    value.encode_utf16().chain(Some(0)).collect()
}

pub(super) fn run(kind: SurfaceKind, start: Option<Box<dyn FnOnce() + Send>>) -> io::Result<()> {
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
            SurfaceKind::Operations => "Eloi 3.9 — Lichess Operations Center",
        });
        let state = Box::into_raw(Box::new(WindowState {
            kind,
            hover_target: false,
            hover_amount: 0.0,
            game: (kind == SurfaceKind::Chess)
                .then(|| Game::from_fen(INITIAL_FEN, Variant::Standard).ok())
                .flatten(),
            selected: None,
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
            let hover = x >= rect.right - 240 && x <= rect.right - 32 && (82..=170).contains(&y);
            unsafe { (*state).hover_target = hover };
            0
        }
        WM_LBUTTONUP if !state.is_null() => {
            unsafe { (*state).hover_target = false };
            let x = (lparam as i16) as i32;
            let y = ((lparam >> 16) as i16) as i32;
            unsafe { board_click(window, &mut *state, x, y) };
            unsafe { InvalidateRect(window, null(), 0) };
            0
        }
        WM_TIMER if !state.is_null() => {
            let target = if unsafe { (*state).hover_target } {
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
            0
        }
        WM_ERASEBKGND => 1,
        WM_CLOSE => {
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
    unsafe { EndPaint(window, &paint_state) };
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
