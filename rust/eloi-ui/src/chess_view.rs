//! Classic Eloi charcoal/purple composition, shared drawing and hit testing.
#![allow(
    clippy::cast_precision_loss,
    clippy::cast_possible_truncation,
    clippy::cast_sign_loss
)]
use crate::{
    chess::{ChessTable, PROMOTIONS, VARIANTS, side, variant_name},
    operations_view::{Bounds, round},
};
use eloi_core::{PieceKind, Player, Square8, position::Piece};
use tiny_skia::{Color, Paint, Pixmap, Transform};

pub(crate) struct Label {
    pub text: String,
    pub bounds: Bounds,
    pub size: i32,
    pub color: (u8, u8, u8),
    pub bold: bool,
    pub center: bool,
}
pub(crate) struct Button {
    pub id: usize,
    pub bounds: Bounds,
    pub text: String,
    pub active: bool,
}
pub(crate) struct Layout {
    pub board: Bounds,
    pub panel: Bounds,
}
pub(crate) fn layout(width: u32, height: u32) -> Layout {
    let size = (height as f32 - 190.0).min(width as f32 - 430.0).max(320.0);
    Layout {
        board: Bounds {
            x: 64.0,
            y: 140.0,
            w: size,
            h: size,
        },
        panel: Bounds {
            x: size + 100.0,
            y: 110.0,
            w: width as f32 - size - 138.0,
            h: height as f32 - 150.0,
        },
    }
}
pub(crate) fn square_center(board: Bounds, square: Square8, flipped: bool) -> (f32, f32) {
    let file = square.index() % 8;
    let rank = square.index() / 8;
    let (f, r) = if flipped {
        (7 - file, rank)
    } else {
        (file, 7 - rank)
    };
    (
        board.x + (f32::from(f) + 0.5) * board.w / 8.0,
        board.y + (f32::from(r) + 0.5) * board.h / 8.0,
    )
}
pub(crate) fn square_at(board: Bounds, x: i32, y: i32, flipped: bool) -> Option<Square8> {
    if !board.contains(x as f32, y as f32)
        || x as f32 >= board.x + board.w
        || y as f32 >= board.y + board.h
    {
        return None;
    }
    let f = ((x as f32 - board.x) / (board.w / 8.0)) as u8;
    let r = ((y as f32 - board.y) / (board.h / 8.0)) as u8;
    Square8::new(if flipped {
        (7 - f) + r * 8
    } else {
        f + (7 - r) * 8
    })
}
fn modal(l: &Layout, height: u32) -> Bounds {
    Bounds {
        x: l.board.x + 12.0,
        y: 108.0,
        w: l.board.w - 24.0,
        h: (height as f32 - 150.0).min(590.0),
    }
}
pub(crate) fn buttons(width: u32, height: u32, table: &ChessTable) -> Vec<Button> {
    let l = layout(width, height);
    let mut out = Vec::new();
    let mut add = |id, x, y, w, h, text: String, active| {
        out.push(Button {
            id,
            bounds: Bounds { x, y, w, h },
            text,
            active,
        })
    };
    if !table.promotion.is_empty() {
        let choices: Vec<_> = PROMOTIONS
            .iter()
            .enumerate()
            .filter(|(_, kind)| table.promotion.iter().any(|m| m.promotion == Some(**kind)))
            .collect();
        let s = (l.board.w - 56.0) / choices.len() as f32 - 8.0;
        let left = l.board.x + 28.0;
        for (column, (i, kind)) in choices.into_iter().enumerate() {
            add(
                30 + i,
                left + column as f32 * (s + 8.0),
                l.board.y + l.board.h / 2.0,
                s,
                72.0,
                format!("{kind:?}"),
                false,
            );
        }
    } else if let Some(setup) = &table.setup {
        let m = modal(&l, height);
        let x = m.x + 22.0;
        let w = m.w - 44.0;
        add(50, x, m.y + 91.0, 42.0, 36.0, "−".into(), false);
        add(
            51,
            x + w / 2.0 - 46.0,
            m.y + 91.0,
            42.0,
            36.0,
            "+".into(),
            false,
        );
        add(
            52,
            x + w / 2.0 + 10.0,
            m.y + 91.0,
            42.0,
            36.0,
            "−".into(),
            false,
        );
        add(53, x + w - 42.0, m.y + 91.0, 42.0, 36.0, "+".into(), false);
        let names = [
            "FIDE",
            "960",
            "HORDE",
            "KOTH",
            "ATOMIC",
            "ANTI",
            "CRAZYHOUSE",
        ];
        for (i, v) in VARIANTS.iter().enumerate() {
            add(
                60 + i,
                x + (i % 4) as f32 * (w / 4.0),
                m.y + 175.0 + (i / 4) as f32 * 43.0,
                w / 4.0 - 6.0,
                35.0,
                names[i].into(),
                setup.variant == *v,
            );
        }
        add(
            58,
            x,
            m.y + 269.0,
            w,
            30.0,
            format!("CHESS960 POSITION #{} · NEXT", setup.chess960),
            setup.variant == eloi_core::Variant::Chess960,
        );
        add(
            56,
            x,
            m.y + 340.0,
            w / 2.0 - 4.0,
            38.0,
            "CAISSA 2.0".into(),
            setup.caissa,
        );
        add(
            57,
            x + w / 2.0 + 4.0,
            m.y + 340.0,
            w / 2.0 - 4.0,
            38.0,
            "ELOI NATIVE".into(),
            !setup.caissa,
        );
        add(
            54,
            x,
            m.y + 439.0,
            w / 2.0 - 4.0,
            38.0,
            "YOU WHITE".into(),
            setup.human == Player::White,
        );
        add(
            55,
            x + w / 2.0 + 4.0,
            m.y + 439.0,
            w / 2.0 - 4.0,
            38.0,
            "YOU BLACK".into(),
            setup.human == Player::Black,
        );
        add(
            40,
            x,
            m.y + m.h - 58.0,
            w / 2.0 - 4.0,
            38.0,
            "CANCEL".into(),
            false,
        );
        add(
            41,
            x + w / 2.0 + 4.0,
            m.y + m.h - 58.0,
            w / 2.0 - 4.0,
            38.0,
            "START GAME".into(),
            true,
        );
    } else {
        let x = l.panel.x + 20.0;
        let w = l.panel.w - 40.0;
        add(7, x, 345.0, 42.0, 34.0, "−".into(), false);
        add(8, x + w - 42.0, 345.0, 42.0, 34.0, "+".into(), false);
        add(0, x, 401.0, w, 39.0, "NEW GAME".into(), true);
        add(1, x, 449.0, w / 2.0 - 4.0, 39.0, "UNDO TURN".into(), false);
        add(
            2,
            x + w / 2.0 + 4.0,
            449.0,
            w / 2.0 - 4.0,
            39.0,
            if table.flipped {
                "NORMAL VIEW"
            } else {
                "FLIP BOARD"
            }
            .into(),
            false,
        );
        add(
            3,
            x,
            497.0,
            w,
            39.0,
            if table.human == Player::White {
                "PLAY AS BLACK"
            } else {
                "PLAY AS WHITE"
            }
            .into(),
            false,
        );
        add(
            4,
            x,
            545.0,
            w / 2.0 - 4.0,
            39.0,
            if table.paused { "RESUME" } else { "PAUSE" }.into(),
            false,
        );
        add(
            6,
            x + w / 2.0 + 4.0,
            545.0,
            w / 2.0 - 4.0,
            39.0,
            "RESIGN".into(),
            false,
        );
        add(
            5,
            x,
            593.0,
            w,
            39.0,
            if table.analysis_open {
                "CLOSE ENGINE LAB"
            } else {
                "ENGINE LAB"
            }
            .into(),
            table.analysis_open,
        );
        if table.settings.variant == eloi_core::Variant::Crazyhouse {
            for (i, kind) in [
                PieceKind::Pawn,
                PieceKind::Knight,
                PieceKind::Bishop,
                PieceKind::Rook,
                PieceKind::Queen,
            ]
            .iter()
            .enumerate()
            {
                let count = table.game.position().pockets[side(table.human)][i];
                add(
                    20 + i,
                    x + i as f32 * w / 5.0,
                    646.0,
                    w / 5.0 - 4.0,
                    34.0,
                    format!("{} {count}", ["P", "N", "B", "R", "Q"][i]),
                    table.drop_piece == Some(*kind),
                );
            }
        }
        if table.analysis_open {
            let x = l.board.x + 26.0;
            let w = l.board.w - 52.0;
            let y = l.board.y + l.board.h - 70.0;
            add(80, x, y, w / 3.0 - 5.0, 36.0, "ANALYZE".into(), true);
            add(
                81,
                x + w / 3.0,
                y,
                w / 3.0 - 5.0,
                36.0,
                "COPY REPORT".into(),
                false,
            );
            add(
                82,
                x + 2.0 * w / 3.0,
                y,
                w / 3.0 - 5.0,
                36.0,
                "EXPORT".into(),
                false,
            );
        }
    }
    out
}
pub(crate) fn hit(width: u32, height: u32, table: &ChessTable, x: i32, y: i32) -> Option<usize> {
    buttons(width, height, table)
        .into_iter()
        .find(|b| b.bounds.contains(x as f32, y as f32))
        .map(|b| b.id)
}

fn label(
    labels: &mut Vec<Label>,
    text: impl Into<String>,
    x: f32,
    y: f32,
    w: f32,
    size: i32,
    color: (u8, u8, u8),
    bold: bool,
) {
    labels.push(Label {
        text: text.into(),
        bounds: Bounds {
            x,
            y,
            w,
            h: size as f32 + 8.0,
        },
        size,
        color,
        bold,
        center: false,
    });
}
pub(crate) fn labels(width: u32, height: u32, table: &ChessTable) -> Vec<Label> {
    let l = layout(width, height);
    let mut labels = Vec::new();
    let ink = (235, 239, 248);
    let muted = (144, 153, 176);
    let mint = (62, 211, 166);
    let accent = (177, 163, 255);
    let eval = table.white_score().map_or_else(
        || "Evaluation not reported".into(),
        |cp| format!("WHITE EVAL {:+.2}", cp as f32 / 100.0),
    );
    label(
        &mut labels,
        eval,
        l.board.x,
        105.0,
        l.board.w,
        13,
        muted,
        false,
    );
    label(&mut labels, "ELOI", 48.0, 26.0, 120.0, 30, ink, true);
    label(
        &mut labels,
        format!("{} · THREE THREADS", variant_name(table.settings.variant)),
        165.0,
        35.0,
        430.0,
        14,
        muted,
        true,
    );
    let x = l.panel.x + 20.0;
    let w = l.panel.w - 40.0;
    label(
        &mut labels,
        table.outcome().unwrap_or_else(|| table.message.clone()),
        x,
        124.0,
        w,
        16,
        if table.busy() { (255, 205, 92) } else { mint },
        true,
    );
    label(
        &mut labels,
        format!(
            "{:?} to move · you play {:?}",
            table.game.position().turn,
            table.human
        ),
        x,
        153.0,
        w,
        13,
        muted,
        false,
    );
    let clock = |i: usize| {
        let s = table.clocks[i] / 1000;
        format!("{:02}:{:02}", s / 60, s % 60)
    };
    label(
        &mut labels,
        format!("WHITE {}    BLACK {}", clock(0), clock(1)),
        x,
        181.0,
        w,
        18,
        ink,
        true,
    );
    let values = [100, 320, 330, 500, 900, 0];
    let mut material = [0; 2];
    for p in table.game.position().cells.iter().flatten() {
        let i = match p.kind {
            PieceKind::Pawn => 0,
            PieceKind::Knight => 1,
            PieceKind::Bishop => 2,
            PieceKind::Rook => 3,
            PieceKind::Queen => 4,
            PieceKind::King => 5,
        };
        material[side(p.owner)] += values[i];
    }
    label(
        &mut labels,
        format!(
            "Material  W {}  ·  B {}  ·  {:+.1}",
            material[0] / 100,
            material[1] / 100,
            (material[0] - material[1]) as f32 / 100.0
        ),
        x,
        214.0,
        w,
        13,
        muted,
        false,
    );
    label(
        &mut labels,
        if table.info.route.is_empty() {
            table.route()
        } else {
            &table.info.route
        },
        x,
        242.0,
        w,
        13,
        accent,
        true,
    );
    let r = &table.info;
    label(
        &mut labels,
        if !r.depth_reported {
            if r.route.is_empty() {
                "No search yet".into()
            } else if r.route.starts_with("Caissa") {
                "Depth not reported by donor".into()
            } else {
                "No completed native iteration".into()
            }
        } else {
            format!(
                "d{} · {} nodes · {} ms",
                r.depth,
                r.nodes,
                r.elapsed.as_millis()
            )
        },
        x,
        271.0,
        w,
        14,
        ink,
        false,
    );
    let pv =
        r.pv.iter()
            .take(7)
            .map(|m| m.uci(table.settings.variant == eloi_core::Variant::Chess960))
            .collect::<Vec<_>>()
            .join(" ");
    label(
        &mut labels,
        format!("PV {pv}"),
        x,
        298.0,
        w,
        12,
        muted,
        false,
    );
    label(
        &mut labels,
        if table.depth == 0 {
            format!(
                "AUTO · {}+{}",
                table.settings.minutes, table.settings.increment
            )
        } else {
            format!("DEPTH {}", table.depth)
        },
        x + 48.0,
        350.0,
        w - 96.0,
        17,
        ink,
        true,
    );
    label(
        &mut labels,
        "Maestro BW · Kadagaden · CC BY 4.0",
        l.panel.x,
        height as f32 - 48.0,
        l.panel.w,
        11,
        muted,
        false,
    );
    label(
        &mut labels,
        "Rust · tiny-skia · Segoe UI",
        l.panel.x,
        height as f32 - 28.0,
        l.panel.w,
        11,
        muted,
        false,
    );
    for i in 0..8 {
        let rank = if table.flipped { i } else { 7 - i };
        let file = if table.flipped { 7 - i } else { i };
        label(
            &mut labels,
            ((b'a' + file) as char).to_string(),
            l.board.x + (f32::from(i) + 0.85) * l.board.w / 8.0,
            l.board.y + l.board.h - 20.0,
            18.0,
            11,
            ink,
            true,
        );
        label(
            &mut labels,
            (rank + 1).to_string(),
            l.board.x + 5.0,
            l.board.y + f32::from(i) * l.board.h / 8.0 + 4.0,
            18.0,
            11,
            ink,
            true,
        );
    }
    if table.analysis_open && table.setup.is_none() {
        let x = l.board.x + 26.0;
        let w = l.board.w - 52.0;
        label(
            &mut labels,
            "ENGINE LAB · SESSION DIAGNOSTICS",
            x,
            180.0,
            w,
            20,
            ink,
            true,
        );
        label(
            &mut labels,
            "No match or training job starts automatically.",
            x,
            217.0,
            w,
            13,
            muted,
            false,
        );
        label(
            &mut labels,
            format!("Requested brain: {}", table.route()),
            x,
            250.0,
            w,
            13,
            accent,
            false,
        );
        label(
            &mut labels,
            format!("Actual last route: {}", r.route),
            x,
            281.0,
            w,
            13,
            mint,
            false,
        );
        label(
            &mut labels,
            format!("Stop: {} · emergency: {}", r.stop_reason, r.emergency),
            x,
            312.0,
            w,
            13,
            muted,
            false,
        );
        label(
            &mut labels,
            if r.score_known {
                format!("Score {:+} cp · mate {:?}", r.score, r.mate)
            } else {
                "Evaluation not reported by donor".into()
            },
            x,
            343.0,
            w,
            15,
            ink,
            true,
        );
        label(&mut labels, "MOVES (UCI)", x, 385.0, w, 13, muted, true);
        let moves = table
            .game
            .moves()
            .map(|m| m.uci(table.settings.variant == eloi_core::Variant::Chess960))
            .collect::<Vec<_>>();
        for (i, row) in moves
            .chunks(8)
            .rev()
            .take(3)
            .collect::<Vec<_>>()
            .into_iter()
            .rev()
            .enumerate()
        {
            label(
                &mut labels,
                row.join(" "),
                x,
                412.0 + i as f32 * 23.0,
                w,
                13,
                ink,
                false,
            );
        }
    }
    if let Some(setup) = &table.setup {
        let m = modal(&l, height);
        let x = m.x + 22.0;
        let w = m.w - 44.0;
        label(
            &mut labels,
            "NEW CLOCKED GAME",
            x,
            m.y + 19.0,
            w,
            21,
            ink,
            true,
        );
        label(
            &mut labels,
            "BASE MINUTES                         INCREMENT",
            x,
            m.y + 62.0,
            w,
            12,
            muted,
            true,
        );
        label(
            &mut labels,
            format!("{} min", setup.minutes),
            x + 50.0,
            m.y + 96.0,
            w / 2.0 - 100.0,
            18,
            ink,
            true,
        );
        label(
            &mut labels,
            format!("{} sec", setup.increment),
            x + w / 2.0 + 58.0,
            m.y + 96.0,
            w / 2.0 - 110.0,
            18,
            ink,
            true,
        );
        label(&mut labels, "VARIANT", x, m.y + 145.0, w, 12, muted, true);
        label(&mut labels, "BRAIN", x, m.y + 311.0, w, 12, muted, true);
        label(
            &mut labels,
            if setup.variant == eloi_core::Variant::Standard {
                "Caissa 2.0 is Standard-only"
            } else {
                "Variant requires Eloi's matching evaluator"
            },
            x,
            m.y + 384.0,
            w,
            11,
            mint,
            false,
        );
        label(&mut labels, "SIDES", x, m.y + 411.0, w, 12, muted, true);
    }
    if !table.promotion.is_empty() {
        label(
            &mut labels,
            "CHOOSE PROMOTION",
            l.board.x + 24.0,
            l.board.y + l.board.h / 2.0 - 44.0,
            l.board.w - 48.0,
            20,
            ink,
            true,
        );
    }
    for b in buttons(width, height, table) {
        labels.push(Label {
            text: b.text,
            bounds: b.bounds,
            size: 13,
            color: ink,
            bold: true,
            center: true,
        });
    }
    labels
}

pub(crate) fn render(
    width: u32,
    height: u32,
    table: &ChessTable,
    hover: f32,
    control: Option<usize>,
) -> Option<Pixmap> {
    let l = layout(width, height);
    let mut pixmap = Pixmap::new(width, height)?;
    pixmap.fill(Color::from_rgba8(16, 17, 31, 255));
    round(
        &mut pixmap,
        Bounds {
            x: 18.0,
            y: 18.0,
            w: width as f32 - 36.0,
            h: height as f32 - 36.0,
        },
        18.0,
        (27, 31, 46, 255),
    );
    round(
        &mut pixmap,
        Bounds {
            x: l.board.x - 10.0,
            y: l.board.y - 10.0,
            w: l.board.w + 20.0,
            h: l.board.h + 20.0,
        },
        15.0,
        (90, 78, 137, 255),
    );
    round(
        &mut pixmap,
        Bounds {
            x: l.panel.x,
            y: 110.0,
            w: l.panel.w,
            h: height as f32 - 175.0,
        },
        20.0,
        (31, 35, 52, 255),
    );
    let position = table.game.position();
    let square = l.board.w / 8.0;
    let legal = position.legal_moves();
    let last = table.game.moves().last();
    for i in 0..64 {
        let sq = Square8::new(i).unwrap();
        let (cx, cy) = square_center(l.board, sq, table.flipped);
        let mut paint = Paint::default();
        let light = (i % 8 + i / 8) % 2 == 1;
        paint.set_color_rgba8(
            if light { 222 } else { 101 },
            if light { 223 } else { 91 },
            if light { 231 } else { 154 },
            255,
        );
        let rect =
            tiny_skia::Rect::from_xywh(cx - square / 2.0, cy - square / 2.0, square, square)?;
        pixmap.fill_rect(rect, &paint, Transform::identity(), None);
        if last.is_some_and(|m| m.from == Some(sq) || m.to == sq) {
            paint.set_color_rgba8(255, 210, 77, 95);
            pixmap.fill_rect(rect, &paint, Transform::identity(), None);
        }
        if table.selected == Some(sq) {
            paint.set_color_rgba8(61, 220, 177, 135);
            pixmap.fill_rect(rect, &paint, Transform::identity(), None);
        }
        if position
            .at(sq)
            .is_some_and(|p| p.kind == PieceKind::King && position.in_check(p.owner))
        {
            paint.set_color_rgba8(234, 76, 102, 145);
            pixmap.fill_rect(rect, &paint, Transform::identity(), None);
        }
        let moving = table
            .animation
            .as_ref()
            .is_some_and(|a| a.mv.to == sq || a.rook.is_some_and(|(_, to, _)| to == sq));
        if !moving && let Some(piece) = position.at(sq) {
            draw_piece(&mut pixmap, piece, cx, cy, square);
        }
        if legal.iter().any(|m| {
            m.to == sq
                && (table.selected.is_some() && m.from == table.selected
                    || table
                        .drop_piece
                        .is_some_and(|kind| m.kind == eloi_core::rules::MoveKind::Drop(kind)))
        }) {
            paint.set_color_rgba8(38, 44, 60, 170);
            let capture = position.at(sq).is_some();
            if let Some(path) = tiny_skia::PathBuilder::from_circle(
                cx,
                cy,
                square * if capture { 0.39 } else { 0.1 },
            ) {
                if capture {
                    pixmap.stroke_path(
                        &path,
                        &paint,
                        &tiny_skia::Stroke {
                            width: square * 0.06,
                            ..Default::default()
                        },
                        Transform::identity(),
                        None,
                    );
                } else {
                    pixmap.fill_path(
                        &path,
                        &paint,
                        tiny_skia::FillRule::Winding,
                        Transform::identity(),
                        None,
                    );
                }
            }
        }
    }
    if let Some(a) = &table.animation {
        let t = a.fraction();
        let t = t * t * (3.0 - 2.0 * t);
        let dest = square_center(l.board, a.mv.to, table.flipped);
        let from =
            a.mv.from
                .map_or(dest, |sq| square_center(l.board, sq, table.flipped));
        draw_piece(
            &mut pixmap,
            a.piece,
            from.0 + (dest.0 - from.0) * t,
            from.1 + (dest.1 - from.1) * t,
            square,
        );
        if let Some((from, to, piece)) = a.rook {
            let from = square_center(l.board, from, table.flipped);
            let to = square_center(l.board, to, table.flipped);
            draw_piece(
                &mut pixmap,
                piece,
                from.0 + (to.0 - from.0) * t,
                from.1 + (to.1 - from.1) * t,
                square,
            );
        }
    }
    // Eval bar is White-relative, independent of whose turn produced the score.
    let fraction = table.displayed_eval;
    round(
        &mut pixmap,
        Bounds {
            x: 32.0,
            y: l.board.y,
            w: 12.0,
            h: l.board.h,
        },
        5.0,
        (20, 22, 29, 255),
    );
    round(
        &mut pixmap,
        Bounds {
            x: 32.0,
            y: if table.flipped {
                l.board.y
            } else {
                l.board.y + l.board.h * (1.0 - fraction)
            },
            w: 12.0,
            h: l.board.h * fraction,
        },
        5.0,
        (238, 240, 246, 255),
    );
    if table.analysis_open && table.setup.is_none() {
        round(
            &mut pixmap,
            Bounds {
                x: l.board.x + 12.0,
                y: 150.0,
                w: l.board.w - 24.0,
                h: l.board.h - 30.0,
            },
            18.0,
            (31, 35, 52, 248),
        );
    }
    if table.setup.is_some() {
        round(&mut pixmap, modal(&l, height), 20.0, (27, 31, 48, 255));
    }
    if !table.promotion.is_empty() {
        round(
            &mut pixmap,
            Bounds {
                x: l.board.x + 12.0,
                y: l.board.y + l.board.h / 2.0 - 55.0,
                w: l.board.w - 24.0,
                h: 150.0,
            },
            18.0,
            (27, 31, 48, 255),
        );
    }
    for b in buttons(width, height, table) {
        let amount = if control == Some(b.id) {
            hover.clamp(0.0, 1.0)
        } else {
            0.0
        };
        let mut r = b.bounds;
        r.y -= amount * 2.0;
        r.x -= amount;
        r.w += amount * 2.0;
        round(
            &mut pixmap,
            r,
            12.0,
            if b.active {
                (121, 101, 255, 255)
            } else {
                (
                    35 + (amount * 20.0) as u8,
                    40 + (amount * 20.0) as u8,
                    57 + (amount * 20.0) as u8,
                    255,
                )
            },
        );
    }
    Some(pixmap)
}

fn draw_piece(pixmap: &mut Pixmap, piece: Piece, cx: f32, cy: f32, square: f32) {
    let image = crate::render::classic_piece_image(piece, square * 0.92);
    let size = square * 0.92;
    let scale = size / image.width() as f32;
    pixmap.draw_pixmap(
        0,
        0,
        image.as_ref(),
        &tiny_skia::PixmapPaint {
            quality: tiny_skia::FilterQuality::Bicubic,
            ..Default::default()
        },
        Transform::from_row(scale, 0.0, 0.0, scale, cx - size / 2.0, cy - size / 2.0),
        None,
    );
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn flipped_geometry_roundtrips_and_controls_are_named() {
        for (w, h) in [(1040, 780), (1920, 1080)] {
            let l = layout(w, h);
            for flip in [false, true] {
                for i in 0..64 {
                    let s = Square8::new(i).unwrap();
                    let (x, y) = square_center(l.board, s, flip);
                    assert_eq!(square_at(l.board, x as i32, y as i32, flip), Some(s));
                }
            }
            let t = ChessTable::new(None);
            for b in buttons(w, h, &t) {
                assert!(!b.text.is_empty());
                assert_eq!(
                    hit(
                        w,
                        h,
                        &t,
                        (b.bounds.x + b.bounds.w / 2.0) as i32,
                        (b.bounds.y + b.bounds.h / 2.0) as i32
                    ),
                    Some(b.id)
                );
            }
        }
    }
    #[test]
    fn original_artwork_differentiates_every_piece_and_render_is_deterministic() {
        let t = ChessTable::new(None);
        let a = render(1040, 780, &t, 0.0, None).unwrap();
        let b = render(1040, 780, &t, 0.0, None).unwrap();
        assert_eq!(a.data(), b.data());
        let mut images = std::collections::HashSet::new();
        for owner in [Player::White, Player::Black] {
            for kind in [
                PieceKind::Pawn,
                PieceKind::Knight,
                PieceKind::Bishop,
                PieceKind::Rook,
                PieceKind::Queen,
                PieceKind::King,
            ] {
                let image = crate::render::classic_piece_image(
                    Piece {
                        owner,
                        kind,
                        promoted: false,
                    },
                    64.0,
                );
                assert!(images.insert(image.data().to_vec()));
            }
        }
        if let Some(path) = std::env::var_os("ELOI_CLASSIC_FRAME") {
            a.save_png(path).unwrap();
        }
    }
}
