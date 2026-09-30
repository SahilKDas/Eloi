//! Handcrafted four-player baseline search.
//!
//! This is the required pre-training opponent and fallback. It is intentionally
//! compact and deterministic: trained evaluators may replace ordering and leaf
//! evaluation later, but not legality.

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
}

struct Shared<'a> {
    deadline: Instant,
    stopped: &'a AtomicBool,
    nodes: AtomicU64,
    node_limit: Option<u64>,
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
    if limits.movetime.is_zero() || limits.depth == 0 || limits.depth > 12 {
        return Err("invalid four-player search limits");
    }
    let start = Instant::now();
    let root_moves = position.legal_moves();
    let mut result = FourSearchResult {
        best_move: root_moves.first().copied(),
        depth: 0,
        score: 0,
        nodes: 0,
        elapsed: Duration::ZERO,
        emergency: !root_moves.is_empty(),
    };
    if root_moves.is_empty() || position.outcome().is_some() {
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
        if let Some((index, score)) = scores
            .into_iter()
            .max_by_key(|(index, score)| (*score, std::cmp::Reverse(*index)))
        {
            result.best_move = Some(root_moves[index]);
            result.score = score;
            result.depth = depth;
            result.nodes = shared.nodes.load(Ordering::Relaxed);
            result.elapsed = start.elapsed();
            result.emergency = false;
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
    root_moves: &[FourMove],
    depth: u8,
    shared: &Shared<'_>,
) -> Option<Vec<(usize, i32)>> {
    std::thread::scope(|scope| {
        let jobs: Vec<_> = (0..SEARCH_THREADS)
            .map(|lane| {
                scope.spawn(move || {
                    let mut scores = Vec::new();
                    for (index, &mv) in root_moves
                        .iter()
                        .enumerate()
                        .filter(|(index, _)| index % SEARCH_THREADS == lane)
                    {
                        let child = position.play(mv)?;
                        let score = match position.mode {
                            FourMode::Ffa => {
                                let vector = maxn(&child, depth.saturating_sub(1), shared)?;
                                vector[position.turn.index()]
                            }
                            FourMode::Teams => {
                                let utility = teams_search(
                                    &child,
                                    depth.saturating_sub(1),
                                    -1_000_000,
                                    1_000_000,
                                    shared,
                                )?;
                                if red_yellow(position.turn) {
                                    utility
                                } else {
                                    -utility
                                }
                            }
                        };
                        scores.push((index, score));
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
) -> Option<i32> {
    shared.visit()?;
    if depth == 0 || position.outcome().is_some() {
        return Some(evaluate_teams(position));
    }
    let moves = position.legal_moves();
    if moves.is_empty() {
        return Some(evaluate_teams(position));
    }
    if red_yellow(position.turn) {
        let mut best = -1_000_000;
        for mv in moves {
            let child = position.play(mv)?;
            best = best.max(teams_search(&child, depth - 1, alpha, beta, shared)?);
            alpha = alpha.max(best);
            if alpha >= beta {
                break;
            }
        }
        Some(best)
    } else {
        let mut best = 1_000_000;
        for mv in moves {
            let child = position.play(mv)?;
            best = best.min(teams_search(&child, depth - 1, alpha, beta, shared)?);
            beta = beta.min(best);
            if alpha >= beta {
                break;
            }
        }
        Some(best)
    }
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
    match position.outcome() {
        Some(FourOutcome::TeamWin { red_yellow: true }) => return 30_000,
        Some(FourOutcome::TeamWin { red_yellow: false }) => return -30_000,
        Some(FourOutcome::Draw | FourOutcome::Placements(_)) => return 0,
        None => {}
    }
    let mut red_yellow_score = 0;
    let mut blue_green_score = 0;
    for cell in position.cells.iter().flatten() {
        if red_yellow(cell.owner) {
            red_yellow_score += material(cell.kind);
        } else {
            blue_green_score += material(cell.kind);
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
