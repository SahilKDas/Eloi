//! Preserved Operations Center composition from src/lichess_operations.cpp.
//! Rendering and hit testing share the original six-button, bottom-toolbar layout.
use tiny_skia::{Color, FillRule, Paint, PathBuilder, Pixmap, Stroke, Transform};

#[derive(Clone, Copy, Debug)]
pub(crate) struct Bounds {
    pub x: f32,
    pub y: f32,
    pub w: f32,
    pub h: f32,
}
impl Bounds {
    pub fn contains(self, x: f32, y: f32) -> bool {
        x >= self.x && x <= self.x + self.w && y >= self.y && y <= self.y + self.h
    }
}

pub(crate) fn actions(width: u32, height: u32) -> [Bounds; 6] {
    let widths = [150.0, 138.0, 110.0, 154.0, 112.0, 82.0];
    let total = widths.iter().sum::<f32>() + 50.0;
    let mut left = (width as f32 - total) / 2.0;
    std::array::from_fn(|i| {
        let b = Bounds {
            x: left,
            y: height as f32 - 70.0,
            w: widths[i],
            h: 43.0,
        };
        left += widths[i] + 10.0;
        b
    })
}
pub(crate) fn hit(width: u32, height: u32, x: i32, y: i32) -> Option<usize> {
    actions(width, height)
        .iter()
        .position(|b| b.contains(x as f32, y as f32))
}

pub(crate) fn round(pixmap: &mut Pixmap, b: Bounds, r: f32, color: (u8, u8, u8, u8)) {
    let mut path = PathBuilder::new();
    let k = r * 0.5522848;
    let (l, t, rr, bb) = (b.x, b.y, b.x + b.w, b.y + b.h);
    path.move_to(l + r, t);
    path.line_to(rr - r, t);
    path.cubic_to(rr - r + k, t, rr, t + r - k, rr, t + r);
    path.line_to(rr, bb - r);
    path.cubic_to(rr, bb - r + k, rr - r + k, bb, rr - r, bb);
    path.line_to(l + r, bb);
    path.cubic_to(l + r - k, bb, l, bb - r + k, l, bb - r);
    path.line_to(l, t + r);
    path.cubic_to(l, t + r - k, l + r - k, t, l + r, t);
    path.close();
    if let Some(path) = path.finish() {
        let mut paint = Paint::default();
        paint.anti_alias = true;
        paint.set_color_rgba8(color.0, color.1, color.2, color.3);
        pixmap.fill_path(
            &path,
            &paint,
            FillRule::Winding,
            Transform::identity(),
            None,
        );
        paint.set_color_rgba8(125, 130, 165, 75);
        pixmap.stroke_path(
            &path,
            &paint,
            &Stroke {
                width: 1.0,
                ..Default::default()
            },
            Transform::identity(),
            None,
        );
    }
}

pub(crate) fn teams_background(
    width: u32,
    height: u32,
    hover: f32,
    control: Option<usize>,
) -> Option<Pixmap> {
    let mut pixmap = Pixmap::new(width.max(1), height.max(1))?;
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
            x: 38.0,
            y: 82.0,
            w: width as f32 - 76.0,
            h: 62.0,
        },
        17.0,
        (31, 35, 52, 255),
    );
    for i in 0..8 {
        let amount = if control == Some(i) {
            hover.clamp(0.0, 1.0)
        } else {
            0.0
        };
        let b = Bounds {
            x: width as f32 - 240.0 - amount * 2.0,
            y: 196.0 + i as f32 * 48.0 - amount * 2.5,
            w: 208.0 + amount * 4.0,
            h: 40.0 + amount * 4.0,
        };
        round(
            &mut pixmap,
            Bounds { y: b.y + 4.0, ..b },
            13.0,
            (0, 0, 0, 65),
        );
        let fill = if i == 0 {
            (121, 101, 255, 255)
        } else if i == 3 {
            (116, 51, 67, 255)
        } else {
            (
                (35.0 + amount * 20.0) as u8,
                (40.0 + amount * 20.0) as u8,
                (57.0 + amount * 20.0) as u8,
                255,
            )
        };
        round(&mut pixmap, b, 13.0, fill);
    }
    Some(pixmap)
}
pub(crate) fn background(
    width: u32,
    height: u32,
    hover: f32,
    control: Option<usize>,
    state: u8,
) -> Option<Pixmap> {
    let mut pixmap = Pixmap::new(width.max(1), height.max(1))?;
    pixmap.fill(Color::from_rgba8(16, 17, 31, 255));
    let mut paint = Paint::default();
    paint.anti_alias = true;
    for (x, y, r, color) in [
        (width as f32 - 70.0, 30.0, 230.0, (121, 101, 255, 30)),
        (10.0, height as f32 - 20.0, 180.0, (62, 211, 166, 15)),
    ] {
        paint.set_color_rgba8(color.0, color.1, color.2, color.3);
        if let Some(path) = PathBuilder::from_circle(x, y, r) {
            pixmap.fill_path(
                &path,
                &paint,
                FillRule::Winding,
                Transform::identity(),
                None,
            );
        }
    }
    let w = width as f32;
    let h = height as f32;
    let mid = (w - 16.0) / 2.0;
    round(
        &mut pixmap,
        Bounds {
            x: 28.0,
            y: 70.0,
            w: w - 56.0,
            h: 56.0,
        },
        17.0,
        (31, 35, 52, 255),
    );
    for b in [
        Bounds {
            x: 28.0,
            y: 142.0,
            w: mid - 28.0,
            h: 192.0,
        },
        Bounds {
            x: mid + 16.0,
            y: 142.0,
            w: w - 28.0 - mid - 16.0,
            h: 192.0,
        },
        Bounds {
            x: 28.0,
            y: 350.0,
            w: w - 56.0,
            h: 70.0,
        },
        Bounds {
            x: 28.0,
            y: 436.0,
            w: w - 56.0,
            h: h - 527.0,
        },
    ] {
        round(&mut pixmap, b, 18.0, (27, 31, 46, 255));
    }
    let status = match state {
        2 | 3 => (62, 211, 166),
        5 => (255, 99, 112),
        0 | 6 => (144, 153, 176),
        _ => (255, 205, 92),
    };
    paint.set_color_rgba8(status.0, status.1, status.2, 255);
    if let Some(path) = PathBuilder::from_circle(51.0, 98.0, 7.0) {
        pixmap.fill_path(
            &path,
            &paint,
            FillRule::Winding,
            Transform::identity(),
            None,
        );
    }
    for (i, base) in actions(width, height).into_iter().enumerate() {
        let amount = if control == Some(i) {
            hover.clamp(0.0, 1.0)
        } else {
            0.0
        };
        let b = Bounds {
            x: base.x - amount * 2.2,
            y: base.y - amount * 3.7,
            w: base.w + amount * 4.4,
            h: base.h + amount * 4.4,
        };
        round(
            &mut pixmap,
            Bounds {
                x: b.x + 1.0,
                y: b.y + 5.0,
                ..b
            },
            13.0,
            (0, 0, 0, 65),
        );
        let fill = match i {
            0 => (121, 101, 255),
            5 => (116, 51, 67),
            _ => (35, 40, 57),
        };
        let channel =
            |a: u8, b: u8| (f32::from(a) + (f32::from(b) - f32::from(a)) * amount * 0.45) as u8;
        round(
            &mut pixmap,
            b,
            13.0,
            (
                channel(fill.0, 73),
                channel(fill.1, 78),
                channel(fill.2, 105),
                255,
            ),
        );
    }
    Some(pixmap)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn original_toolbar_hit_boxes_follow_resizing() {
        for (w, h) in [(1120, 820), (1920, 1080), (900, 740)] {
            for (i, b) in actions(w, h).iter().enumerate() {
                assert_eq!(
                    hit(w, h, (b.x + b.w / 2.0) as i32, (b.y + b.h / 2.0) as i32),
                    Some(i)
                );
            }
            assert_eq!(hit(w, h, 40, 160), None);
        }
    }
}
