//! Handcrafted Eloi four-player Teams release search and legacy FFA baseline.
//!
//! Teams uses Eloi's own material/positional evaluator and team alpha-beta.
//! No training campaign or donor evaluator is required for its release route.

use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::time::{Duration, Instant};

use eloi_core::four_player::{FourMode, FourMove, FourOutcome, FourPosition, FourSeat};
use eloi_core::{PieceKind, SEARCH_THREADS};

/// Bounded four-player search limits.
#[derive(Clone, Copy, Debug)]
pub struct FourSearchLimits {
    /// Real wall-clock budget.
    pub movetime: Duration,
    /// Maximum completed depth.
    pub depth: u8,
    /// Optional global node limit shared by all root lanes.
    pub nodes: Option<u64>,
}

/// Four-player search result.
#[derive(Clone, Debug)]
pub struct FourSearchResult {
    /// Selected legal move.
    pub best_move: Option<FourMove>,
    /// Completed depth.
    pub depth: u8,
    /// Root utility from the mover's perspective.
    pub score: i32,
    /// Total searched nodes.
    pub nodes: u64,
    /// Elapsed wall time.
    pub elapsed: Duration,
    /// True if only an emergency legal move was available before an iteration completed.
    pub emergency: bool,
    /// Legal principal variation from the last completed iteration.
    pub pv: Vec<FourMove>,
}

struct Shared<'a> {
    deadline: Instant,
    stopped: &'a AtomicBool,
    nodes: AtomicU64,
    node_limit: Option<u64>,
}

// Stack-only PV storage: no allocation or extra searches in recursive nodes.
#[derive(Clone, Default)]
struct PvLine {
    moves: [Option<FourMove>; 16],
}

impl PvLine {
    fn prepend(mv: FourMove, child: &Self) -> Self {
        let mut line = Self::default();
        line.moves[0] = Some(mv);
        line.moves[1..].copy_from_slice(&child.moves[..15]);
        line
    }
    fn to_vec(&self) -> Vec<FourMove> {
        self.moves.iter().copied().map_while(|mv| mv).collect()
    }
}

impl Shared<'_> {
    fn visit(&self) -> Option<()> {
        if self.stopped.load(Ordering::Relaxed) || Instant::now() >= self.deadline {
            return None;
        }
        self.nodes
            .fetch_update(Ordering::Relaxed, Ordering::Relaxed, |nodes| {
                if self.node_limit.is_some_and(|limit| nodes >= limit) {
                    None
                } else {
                    nodes.checked_add(1)
                }
            })
            .ok()
            .map(|_| ())
    }
}

/// Search a four-player root using exactly Eloi's three-thread contract.
///
/// # Errors
/// Rejects unbounded or impossible limits.
pub fn search_four_player(
    position: &FourPosition,
    limits: FourSearchLimits,
    stopped: &AtomicBool,
) -> Result<FourSearchResult, &'static str> {
    search_four_player_observed(position, limits, stopped, &mut |_| {})
}

/// Search with an observer invoked only after a complete iteration.
/// The observer must not block; it runs on the coordinating search thread.
///
/// # Errors
/// Rejects the same invalid limits as [`search_four_player`].
pub fn search_four_player_observed(
    position: &FourPosition,
    limits: FourSearchLimits,
    stopped: &AtomicBool,
    observer: &mut dyn FnMut(&FourSearchResult),
) -> Result<FourSearchResult, &'static str> {
    if limits.movetime.is_zero() || limits.depth == 0 || limits.depth > 12 {
        return Err("invalid four-player search limits");
    }
    let start = Instant::now();
    let mut root_moves = position.legal_successors();
    root_moves.sort_by_key(|(mv, _)| std::cmp::Reverse(move_priority(position, *mv)));
    let mut result = FourSearchResult {
        best_move: root_moves.first().map(|(mv, _)| *mv),
        depth: 0,
        score: 0,
        nodes: 0,
        elapsed: Duration::ZERO,
        emergency: !root_moves.is_empty(),
        pv: Vec::new(),
    };
    if root_moves.is_empty() || position.outcome().is_some() {
        result.best_move = None;
        result.emergency = false;
        return Ok(result);
    }
    let shared = Shared {
        deadline: start + limits.movetime,
        stopped,
        nodes: AtomicU64::new(0),
        node_limit: limits.nodes,
    };
    for depth in 1..=limits.depth {
        let Some(scores) = root_iteration(position, &root_moves, depth, &shared) else {
            break;
        };
        if let Some((index, score, pv)) = scores
            .into_iter()
            .max_by_key(|(index, score, _)| (*score, std::cmp::Reverse(*index)))
        {
            result.best_move = Some(root_moves[index].0);
            result.score = score;
            result.depth = depth;
            result.nodes = shared.nodes.load(Ordering::Relaxed);
            result.elapsed = start.elapsed();
            result.emergency = false;
            result.pv = PvLine::prepend(root_moves[index].0, &pv).to_vec();
            root_moves.swap(0, index);
            observer(&result);
        }
        if stopped.load(Ordering::Relaxed) || Instant::now() >= shared.deadline {
            break;
        }
    }
    result.nodes = shared.nodes.load(Ordering::Relaxed);
    result.elapsed = start.elapsed();
    Ok(result)
}

fn root_iteration(
    position: &FourPosition,
    root_moves: &[(FourMove, FourPosition)],
    depth: u8,
    shared: &Shared<'_>,
) -> Option<Vec<(usize, i32, PvLine)>> {
    std::thread::scope(|scope| {
        let jobs: Vec<_> = (0..SEARCH_THREADS)
            .map(|lane| {
                scope.spawn(move || {
                    let mut scores = Vec::new();
                    for (index, (_, child)) in root_moves
                        .iter()
                        .enumerate()
                        .filter(|(index, _)| index % SEARCH_THREADS == lane)
                    {
                        let (score, pv) = match position.mode {
                            FourMode::Ffa => {
                                let vector = maxn(&child, depth.saturating_sub(1), shared)?;
                                (vector[position.turn.index()], PvLine::default())
                            }
                            FourMode::Teams => {
                                let (utility, pv) = teams_search(
                                    &child,
                                    depth.saturating_sub(1),
                                    -1_000_000,
                                    1_000_000,
                                    shared,
                                )?;
                                (
                                    if red_yellow(position.turn) {
                                        utility
                                    } else {
                                        -utility
                                    },
                                    pv,
                                )
                            }
                        };
                        scores.push((index, score, pv));
                    }
                    Some(scores)
                })
            })
            .collect();
        jobs.into_iter()
            .map(|job| job.join().ok().flatten())
            .collect::<Option<Vec<_>>>()
            .map(|scores| scores.into_iter().flatten().collect())
    })
}

fn maxn(position: &FourPosition, depth: u8, shared: &Shared<'_>) -> Option<[i32; 4]> {
    shared.visit()?;
    if depth == 0 || position.outcome().is_some() {
        return Some(evaluate_ffa(position));
    }
    let moves = position.legal_moves();
    if moves.is_empty() {
        return Some(evaluate_ffa(position));
    }
    let mover = position.turn.index();
    let mut best = [-1_000_000; 4];
    for mv in moves {
        let child = position.play(mv)?;
        let score = maxn(&child, depth - 1, shared)?;
        if score[mover] > best[mover] {
            best = score;
        }
    }
    Some(best)
}

fn teams_search(
    position: &FourPosition,
    depth: u8,
    mut alpha: i32,
    mut beta: i32,
    shared: &Shared<'_>,
) -> Option<(i32, PvLine)> {
    shared.visit()?;
    if depth == 0 {
        return teams_quiescence(position, alpha, beta, 4, shared);
    }
    if let Some(outcome) = position.outcome() {
        return Some((team_terminal(outcome), PvLine::default()));
    }
    let mut moves = position.legal_successors();
    moves.sort_by_key(|(mv, _)| std::cmp::Reverse(move_priority(position, *mv)));
    if moves.is_empty() {
        return Some((evaluate_teams(position), PvLine::default()));
    }
    if red_yellow(position.turn) {
        let mut best = -1_000_000;
        let mut pv = PvLine::default();
        for (mv, child) in moves {
            let (score, child_pv) = teams_search(&child, depth - 1, alpha, beta, shared)?;
            if score > best {
                best = score;
                pv = PvLine::prepend(mv, &child_pv);
            }
            alpha = alpha.max(best);
            if alpha >= beta {
                break;
            }
        }
        Some((best, pv))
    } else {
        let mut best = 1_000_000;
        let mut pv = PvLine::default();
        for (mv, child) in moves {
            let (score, child_pv) = teams_search(&child, depth - 1, alpha, beta, shared)?;
            if score < best {
                best = score;
                pv = PvLine::prepend(mv, &child_pv);
            }
            beta = beta.min(best);
            if alpha >= beta {
                break;
            }
        }
        Some((best, pv))
    }
}

// Team turns alternate, so all utilities use Red/Yellow's perspective.
// Check evasions cannot use stand-pat; bounded capture search avoids horizon hangs.
fn teams_quiescence(
    position: &FourPosition,
    mut alpha: i32,
    mut beta: i32,
    remaining: u8,
    shared: &Shared<'_>,
) -> Option<(i32, PvLine)> {
    shared.visit()?;
    if let Some(outcome) = position.outcome() {
        return Some((team_terminal(outcome), PvLine::default()));
    }
    let stand = evaluate_teams(position);
    if remaining == 0 {
        return Some((stand, PvLine::default()));
    }
    let maximize = red_yellow(position.turn);
    let checked = position.king_attacked(position.turn);
    let mut best = if checked {
        if maximize { -1_000_000 } else { 1_000_000 }
    } else {
        stand
    };
    let mut pv = PvLine::default();
    if !checked {
        if maximize {
            if best >= beta {
                return Some((best, pv));
            }
            alpha = alpha.max(best);
        } else {
            if best <= alpha {
                return Some((best, pv));
            }
            beta = beta.min(best);
        }
    }
    let mut moves = position.legal_successors();
    if !checked {
        moves.retain(|(mv, _)| {
            position.at(mv.to).is_some()
                || mv.promotion.is_some()
                || position.at(mv.from).is_some_and(|p| {
                    p.kind == PieceKind::Pawn
                        && mv.from.file() != mv.to.file()
                        && mv.from.rank() != mv.to.rank()
                })
        });
    }
    moves.sort_by_key(|(mv, _)| std::cmp::Reverse(move_priority(position, *mv)));
    for (mv, child) in moves {
        let (score, child_pv) = teams_quiescence(&child, alpha, beta, remaining - 1, shared)?;
        if maximize {
            if score > best {
                best = score;
                pv = PvLine::prepend(mv, &child_pv);
            }
            alpha = alpha.max(best);
        } else {
            if score < best {
                best = score;
                pv = PvLine::prepend(mv, &child_pv);
            }
            beta = beta.min(best);
        }
        if alpha >= beta {
            break;
        }
    }
    Some((best, pv))
}

fn move_priority(position: &FourPosition, mv: FourMove) -> i32 {
    position.at(mv.to).map_or(0, |p| material(p.kind) * 16)
        - position.at(mv.from).map_or(0, |p| material(p.kind))
        + mv.promotion.map_or(0, material) * 8
}

fn evaluate_ffa(position: &FourPosition) -> [i32; 4] {
    if let Some(FourOutcome::Placements(placements)) = position.outcome() {
        let mut values = [-10_000; 4];
        for (rank, (seat, score)) in placements.into_iter().enumerate() {
            values[seat.index()] =
                30_000 - i32::try_from(rank).unwrap_or(0) * 4_000 + i32::from(score) * 100;
        }
        return values;
    }
    let mut values = [
        i32::from(position.scores[0]) * 100,
        i32::from(position.scores[1]) * 100,
        i32::from(position.scores[2]) * 100,
        i32::from(position.scores[3]) * 100,
    ];
    for cell in position.cells.iter().flatten() {
        values[cell.owner.index()] += material(cell.kind);
    }
    for seat in FourSeat::ORDER {
        if position.king_attacked(seat) {
            values[seat.index()] -= 120;
        }
        if !position.active[seat.index()] {
            values[seat.index()] -= 5_000;
        }
    }
    values
}

fn evaluate_teams(position: &FourPosition) -> i32 {
    let mut red_yellow_score = 0;
    let mut blue_green_score = 0;
    for (index, cell) in position
        .cells
        .iter()
        .enumerate()
        .filter_map(|(i, p)| p.map(|p| (i, p)))
    {
        let file = (index % 14) as i32;
        let rank = (index / 14) as i32;
        let progress = match cell.owner {
            FourSeat::Red => rank,
            FourSeat::Blue => file,
            FourSeat::Yellow => 13 - rank,
            FourSeat::Green => 13 - file,
        };
        let centrality = 13 - (file * 2 - 13).abs().max((rank * 2 - 13).abs());
        let positional = match cell.kind {
            PieceKind::Pawn => progress * 8 + centrality * 2,
            PieceKind::Knight => centrality * 6,
            PieceKind::Bishop => centrality * 3,
            PieceKind::Rook => progress * 2,
            PieceKind::Queen => centrality,
            PieceKind::King => -centrality * 5,
        };
        if red_yellow(cell.owner) {
            red_yellow_score += material(cell.kind) + positional;
        } else {
            blue_green_score += material(cell.kind) + positional;
        }
    }
    // The weaker king determines team survival; shelter is valuable for both partners.
    for seat in FourSeat::ORDER {
        if let Some(king) = position.king(seat) {
            let mut danger = 0;
            for df in -1i16..=1 {
                for dr in -1i16..=1 {
                    let f = i16::from(king.file()) + df;
                    let r = i16::from(king.rank()) + dr;
                    if let (Ok(f), Ok(r)) = (u8::try_from(f), u8::try_from(r)) {
                        if let Some(sq) = eloi_core::Square14::new(f, r) {
                            if position.at(sq).is_some_and(|p| {
                                position.allied(seat, p.owner) && p.kind == PieceKind::Pawn
                            }) {
                                danger -= 12;
                            }
                        }
                    }
                }
            }
            if position.king_attacked(seat) {
                danger += 100;
            }
            if red_yellow(seat) {
                red_yellow_score -= danger;
            } else {
                blue_green_score -= danger;
            }
        }
    }
    for seat in [FourSeat::Red, FourSeat::Yellow] {
        if position.king_attacked(seat) {
            red_yellow_score -= 120;
        }
    }
    for seat in [FourSeat::Blue, FourSeat::Green] {
        if position.king_attacked(seat) {
            blue_green_score -= 120;
        }
    }
    red_yellow_score - blue_green_score
}

fn team_terminal(outcome: FourOutcome) -> i32 {
    match outcome {
        FourOutcome::TeamWin { red_yellow: true } => 30_000,
        FourOutcome::TeamWin { red_yellow: false } => -30_000,
        _ => 0,
    }
}

fn red_yellow(seat: FourSeat) -> bool {
    matches!(seat, FourSeat::Red | FourSeat::Yellow)
}

fn material(piece: PieceKind) -> i32 {
    match piece {
        PieceKind::Pawn => 100,
        PieceKind::Knight => 320,
        PieceKind::Bishop => 330,
        PieceKind::Rook => 500,
        PieceKind::Queen => 900,
        PieceKind::King => 4_000,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn observer_reports_completed_legal_pvs_without_changing_search() {
        let mut p = fixture();
        add(&mut p, 6, 3, FourSeat::Red, PieceKind::Rook);
        add(&mut p, 9, 10, FourSeat::Yellow, PieceKind::Pawn);
        for seat in FourSeat::ORDER {
            p.turn = seat;
            for nodes in [None, Some(100_000)] {
                let limits = FourSearchLimits {
                    movetime: Duration::from_secs(5),
                    depth: 2,
                    nodes,
                };
                let plain = search_four_player(&p, limits, &AtomicBool::new(false)).unwrap();
                let mut updates = Vec::new();
                let watched =
                    search_four_player_observed(&p, limits, &AtomicBool::new(false), &mut |r| {
                        updates.push(r.clone())
                    })
                    .unwrap();
                assert_eq!(plain.best_move, watched.best_move);
                assert_eq!(plain.score, watched.score);
                assert_eq!(plain.depth, watched.depth);
                assert_eq!(plain.nodes, watched.nodes);
                assert_eq!(plain.pv, watched.pv);
                assert_eq!(updates.len(), usize::from(watched.depth));
                for (index, update) in updates.iter().enumerate() {
                    assert_eq!(usize::from(update.depth), index + 1);
                    assert!(!update.emergency);
                    assert_eq!(update.pv.first().copied(), update.best_move);
                    assert!(update.pv.len() <= 16);
                    let mut replay = p.clone();
                    for mv in &update.pv {
                        replay = replay.play(*mv).expect("PV move must be legal");
                    }
                }
            }
        }
    }
    #[test]
    fn no_depth_zero_or_cancelled_iteration_is_published() {
        let p = FourPosition::initial(FourMode::Teams);
        for stopped in [false, true] {
            let mut calls = 0;
            let result = search_four_player_observed(
                &p,
                FourSearchLimits {
                    movetime: Duration::from_secs(1),
                    depth: 12,
                    nodes: Some(1),
                },
                &AtomicBool::new(stopped),
                &mut |_| calls += 1,
            )
            .unwrap();
            assert_eq!(calls, 0);
            assert_eq!(result.depth, 0);
            assert!(result.pv.is_empty());
            assert!(result.emergency);
        }
    }
    fn fixture() -> FourPosition {
        use eloi_core::{Square14, four_player::FourPiece};
        let mut p = FourPosition::initial(FourMode::Teams);
        p.cells = [None; 196];
        p.castling = [0; 4];
        for (seat, (f, r)) in FourSeat::ORDER
            .into_iter()
            .zip([(7, 0), (0, 7), (6, 13), (13, 6)])
        {
            let sq = Square14::new(f, r).unwrap();
            p.cells[r as usize * 14 + f as usize] = Some(FourPiece {
                owner: seat,
                kind: PieceKind::King,
            });
            assert!(p.at(sq).is_some());
        }
        p
    }
    fn add(p: &mut FourPosition, f: usize, r: usize, owner: FourSeat, kind: PieceKind) {
        p.cells[r * 14 + f] = Some(eloi_core::four_player::FourPiece { owner, kind });
    }
    fn tactical_search(p: &FourPosition) -> FourSearchResult {
        search_four_player(
            p,
            FourSearchLimits {
                movetime: Duration::from_millis(1000),
                depth: 2,
                nodes: Some(20_000),
            },
            &AtomicBool::new(false),
        )
        .unwrap()
    }
    #[test]
    fn teams_takes_free_enemy_queen_without_harming_partner() {
        let mut p = fixture();
        add(&mut p, 6, 3, FourSeat::Red, PieceKind::Rook);
        add(&mut p, 6, 6, FourSeat::Blue, PieceKind::Queen);
        let result = tactical_search(&p);
        assert!(result.depth >= 1);
        assert_eq!(
            result.best_move.unwrap().to,
            eloi_core::Square14::new(6, 6).unwrap()
        );
    }
    #[test]
    fn teams_finishes_mate_and_terminal_search_submits_nothing() {
        let mut p = fixture();
        add(&mut p, 2, 6, FourSeat::Red, PieceKind::Rook);
        add(&mut p, 2, 8, FourSeat::Red, PieceKind::Rook);
        add(&mut p, 4, 7, FourSeat::Red, PieceKind::Rook);
        let result = tactical_search(&p);
        let child = p.play(result.best_move.unwrap()).unwrap();
        assert_eq!(
            child.outcome(),
            Some(FourOutcome::TeamWin { red_yellow: true })
        );
        assert_eq!(tactical_search(&child).best_move, None);
    }
    #[test]
    fn teams_cancellation_is_bounded_and_legal() {
        let p = FourPosition::initial(FourMode::Teams);
        let stopped = AtomicBool::new(true);
        let r = search_four_player(
            &p,
            FourSearchLimits {
                movetime: Duration::from_secs(1),
                depth: 12,
                nodes: Some(100),
            },
            &stopped,
        )
        .unwrap();
        assert!(r.elapsed < Duration::from_millis(250));
        assert!(p.legal_moves().contains(&r.best_move.unwrap()));
        assert!(r.emergency);
        assert_eq!(r.nodes, 0);
    }

    #[test]
    fn four_player_search_uses_three_lanes_and_returns_legal_move() {
        let position = FourPosition::initial(FourMode::Ffa);
        let result = search_four_player(
            &position,
            FourSearchLimits {
                movetime: Duration::from_millis(250),
                depth: 1,
                nodes: Some(10_000),
            },
            &AtomicBool::new(false),
        )
        .unwrap();
        assert_eq!(result.depth, 1);
        assert!(position.legal_moves().contains(&result.best_move.unwrap()));
        assert!(!result.emergency);
    }

    #[test]
    fn teams_utility_is_team_based() {
        let position = FourPosition::initial(FourMode::Teams);
        assert!(evaluate_teams(&position).abs() < 400);
    }
}
