//! Deterministic safe renderer shared by native paint and snapshot tests.
#![allow(
    clippy::cast_possible_truncation,
    clippy::cast_precision_loss,
    clippy::cast_sign_loss,
    clippy::field_reassign_with_default
)]

use eloi_core::position::Position;
use eloi_core::{PieceKind, Player};
use tiny_skia::{Color, Paint, PathBuilder, Pixmap, Rect, Transform};

/// Which top-level Eloi surface is visible.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SurfaceKind {
    /// Interactive chessboard shell.
    Chess,
    /// Lichess Operations Center.
    Operations,
}

/// Rendered premultiplied RGBA surface.
pub struct Surface {
    pixmap: Pixmap,
}

impl Surface {
    /// Render a deterministic responsive frame.
    #[must_use]
    pub fn render(
        width: u32,
        height: u32,
        kind: SurfaceKind,
        hover: f32,
        hover_control: Option<usize>,
        position: Option<&Position>,
    ) -> Option<Self> {
        let mut pixmap = Pixmap::new(width.max(1), height.max(1))?;
        pixmap.fill(Color::from_rgba8(8, 15, 27, 255));
        let mut paint = Paint::default();
        paint.anti_alias = true;
        paint.set_color_rgba8(17, 29, 46, 255);
        fill(
            &mut pixmap,
            18.0,
            18.0,
            width as f32 - 36.0,
            height as f32 - 36.0,
            &paint,
        );
        paint.set_color_rgba8(24, 42, 64, 255);
        fill(&mut pixmap, 38.0, 82.0, width as f32 - 76.0, 92.0, &paint);
        match kind {
            SurfaceKind::Chess => board(&mut pixmap, width, height, position),
            SurfaceKind::Operations => cards(&mut pixmap, width, height),
        }
        let hover = hover.clamp(0.0, 1.0);
        let controls = if kind == SurfaceKind::Operations {
            5
        } else {
            1
        };
        for index in 0..controls {
            let active = hover_control == Some(index);
            let amount = if active { hover } else { 0.0 };
            paint.set_color_rgba8((35.0 + amount * 20.0) as u8, 196, 145, 255);
            let scale = 1.0 + amount * 0.03;
            let button_width = 176.0 * scale;
            fill(
                &mut pixmap,
                width as f32 - button_width - 42.0,
                108.0 + index as f32 * 58.0 - (scale - 1.0) * 24.0,
                button_width,
                46.0 * scale,
                &paint,
            );
        }
        Some(Self { pixmap })
    }

    /// Premultiplied RGBA bytes.
    #[must_use]
    pub fn rgba(&self) -> &[u8] {
        self.pixmap.data()
    }
}

fn fill(pixmap: &mut Pixmap, x: f32, y: f32, width: f32, height: f32, paint: &Paint) {
    if let Some(rect) = Rect::from_xywh(x, y, width.max(1.0), height.max(1.0)) {
        pixmap.fill_rect(rect, paint, Transform::identity(), None);
    }
}

fn board(pixmap: &mut Pixmap, width: u32, height: u32, position: Option<&Position>) {
    let size = (width.min(height).saturating_sub(230) as f32).max(160.0);
    let origin_x = 44.0;
    let origin_y = 196.0;
    let square = size / 8.0;
    let mut paint = Paint::default();
    for rank in 0..8 {
        for file in 0..8 {
            let light = (rank + file) % 2 == 0;
            paint.set_color_rgba8(
                if light { 210 } else { 89 },
                if light { 220 } else { 117 },
                if light { 202 } else { 129 },
                255,
            );
            fill(
                pixmap,
                origin_x + file as f32 * square,
                origin_y + rank as f32 * square,
                square,
                square,
                &paint,
            );
        }
    }
    if let Some(position) = position {
        for (index, piece) in position.cells.iter().enumerate() {
            let Some(piece) = piece else { continue };
            let file = index % 8;
            let rank = index / 8;
            let cx = origin_x + (file as f32 + 0.5) * square;
            let cy = origin_y + ((7 - rank) as f32 + 0.5) * square;
            let radius = square
                * match piece.kind {
                    PieceKind::Pawn => 0.22,
                    PieceKind::Knight | PieceKind::Bishop => 0.27,
                    PieceKind::Rook => 0.29,
                    PieceKind::Queen | PieceKind::King => 0.32,
                };
            let mut piece_paint = Paint::default();
            if piece.owner == Player::White {
                piece_paint.set_color_rgba8(242, 244, 235, 255);
            } else {
                piece_paint.set_color_rgba8(24, 31, 42, 255);
            }
            if let Some(path) = PathBuilder::from_circle(cx, cy, radius) {
                pixmap.fill_path(
                    &path,
                    &piece_paint,
                    tiny_skia::FillRule::Winding,
                    Transform::identity(),
                    None,
                );
            }
            if matches!(
                piece.kind,
                PieceKind::Rook | PieceKind::Queen | PieceKind::King
            ) {
                fill(
                    pixmap,
                    cx - radius,
                    cy - radius,
                    radius * 2.0,
                    (radius * 0.52).max(2.0),
                    &piece_paint,
                );
            }
        }
    }
}

fn cards(pixmap: &mut Pixmap, width: u32, height: u32) {
    let mut paint = Paint::default();
    paint.set_color_rgba8(13, 25, 40, 255);
    let gap = 18.0;
    let card_width = (width as f32 - 116.0) / 2.0;
    for row in 0..3 {
        for column in 0..2 {
            fill(
                pixmap,
                40.0 + column as f32 * (card_width + gap),
                196.0 + row as f32 * 116.0,
                card_width,
                96.0_f32.min(height as f32 - 210.0),
                &paint,
            );
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn both_surfaces_render_deterministically_and_hover_changes_pixels() {
        for kind in [SurfaceKind::Chess, SurfaceKind::Operations] {
            let normal = Surface::render(960, 700, kind, 0.0, None, None).unwrap();
            let again = Surface::render(960, 700, kind, 0.0, None, None).unwrap();
            let hover = Surface::render(960, 700, kind, 1.0, Some(0), None).unwrap();
            assert_eq!(normal.rgba(), again.rgba());
            assert_ne!(normal.rgba(), hover.rgba());
        }
    }
}
