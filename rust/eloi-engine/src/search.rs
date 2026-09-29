//! Conservative Eloi-native reference search for migration validation.
//!
//! This establishes legal, cancellable three-lane alpha-beta with exact Eloi
//! model arithmetic. Selective search and endgame knowledge require subsequent
//! parity gates before this profile is eligible to replace the legacy search.

use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::time::{Duration, Instant};

use eloi_core::game::Game;
use eloi_core::position::Position;
use eloi_core::rules::{Move8, MoveKind, opponent};
use eloi_core::{PieceKind, SEARCH_THREADS, Variant};

use crate::nnue::NnueState;

const MATE: i32 = 30_000;
const MAX_PLY: u16 = 64;

/// Explicit bounded search limits.
#[derive(Clone, Copy, Debug)]
pub struct SearchLimits {
    /// Real wall-clock budget.
    pub movetime: Duration,
    /// Optional completed-iteration boundary for clock-managed searches.
    pub soft_time: Option<Duration>,
    /// Maximum completed depth.
    pub depth: u8,
    /// Optional global node limit shared by all three lanes.
    pub nodes: Option<u64>,
}

/// Actual reason the search returned.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum StopReason {
    /// Completed an iteration after the soft clock allocation.
    SoftLimit,
    /// Reached the depth limit.
    Depth,
    /// Reached the real clock deadline.
    HardLimit,
    /// Reached the shared node limit.
    NodeLimit,
    /// User or protocol requested cancellation.
    ExternalStop,
    /// No legal move exists, or a variant terminal position was reached.
    Terminal,
}

/// A completed iteration or explicitly identified emergency legal answer.
#[derive(Clone, Debug)]
pub struct SearchResult {
    /// Best legal root move, absent for a terminal root.
    pub best_move: Option<Move8>,
    /// Last fully completed root depth.
    pub depth: u8,
    /// Centipawn or internal distance-to-mate score.
    pub score: i32,
    /// Legally constructed principal variation.
    pub pv: Vec<Move8>,
    /// Total nodes across all lanes.
    pub nodes: u64,
    /// Actual elapsed time.
    pub elapsed: Duration,
    /// Why the search stopped.
    pub stop_reason: StopReason,
    /// No complete iteration exists; move is only an emergency legal answer.
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

struct Lane<'a> {
    shared: &'a Shared<'a>,
    history: Vec<u64>,
}

fn key(position: &Position, children: &[(Move8, Position)]) -> u64 {
    position.identity_key(
        children
            .iter()
            .any(|(mv, _)| mv.kind == MoveKind::EnPassant),
    )
}

fn terminal(position: &Position, children: &[(Move8, Position)], ply: u16) -> Option<i32> {
    if let Some(winner) = position.terminal_winner() {
        return Some(if winner == position.turn {
            MATE - i32::from(ply)
        } else {
            -MATE + i32::from(ply)
        });
    }
    if children.is_empty() {
        return Some(if position.variant == Variant::Antichess {
            MATE - i32::from(ply)
        } else if position.in_check(position.turn) {
            -MATE + i32::from(ply)
        } else {
            0
        });
    }
    None
}

fn priority(position: &Position, mv: Move8) -> i32 {
    let value = |piece| match piece {
        PieceKind::Pawn => 100,
        PieceKind::Knight => 320,
        PieceKind::Bishop => 330,
        PieceKind::Rook => 500,
        PieceKind::Queen => 900,
        PieceKind::King => 20_000,
    };
    mv.promotion.map_or(0, value)
        + if position.is_capture(mv) {
            10_000 + position.at(mv.to).map_or(100, |p| value(p.kind)) * 10
                - mv.from
                    .and_then(|s| position.at(s))
                    .map_or(0, |p| value(p.kind))
        } else {
            0
        }
}

fn evaluate(position: &Position, nnue: &NnueState) -> Option<i32> {
    if position.variant == Variant::Antichess {
        let ours = position
            .cells
            .iter()
            .flatten()
            .filter(|p| p.owner == position.turn)
            .count();
        let theirs = position
            .cells
            .iter()
            .flatten()
            .filter(|p| p.owner != position.turn)
            .count();
        return Some(
            100 * (i32::try_from(theirs).ok()? - i32::try_from(ours).ok()?)
                + if position
                    .legal_moves()
                    .first()
                    .is_some_and(|&m| position.is_capture(m))
                {
                    35
                } else {
                    0
                },
        );
    }
    let mut score = nnue.evaluate(position.turn).ok()?;
    if position.variant == Variant::KingOfTheHill {
        let distance = |owner| {
            position.king(owner).map_or(8, |s| {
                [27_u8, 28, 35, 36]
                    .iter()
                    .map(|&hill| {
                        i32::from((s.index() % 8).abs_diff(hill % 8))
                            + i32::from((s.index() / 8).abs_diff(hill / 8))
                    })
                    .min()
                    .unwrap_or(8)
            })
        };
        score += 120 * (distance(opponent(position.turn)) - distance(position.turn));
    }
    if position.variant == Variant::Atomic {
        let pressure = |attacker, defender| {
            position.king(defender).map_or(20, |king| {
                i32::try_from(
                    position
                        .pseudo_moves(attacker)
                        .into_iter()
                        .filter(|&m| {
                            position.is_capture(m)
                                && (m.to.index() % 8).abs_diff(king.index() % 8) <= 1
                                && (m.to.index() / 8).abs_diff(king.index() / 8) <= 1
                        })
                        .count(),
                )
                .unwrap_or(0)
            })
        };
        score += 140
            * (pressure(position.turn, opponent(position.turn))
                - pressure(opponent(position.turn), position.turn));
    }
    Some(score)
}

impl Lane<'_> {
    fn negamax(
        &mut self,
        position: &Position,
        nnue: &NnueState,
        depth: u8,
        ply: u16,
        mut alpha: i32,
        beta: i32,
    ) -> Option<(i32, Vec<Move8>)> {
        self.shared.visit()?;
        let mut children = position.legal_children();
        if let Some(score) = terminal(position, &children, ply) {
            return Some((score, Vec::new()));
        }
        let key = key(position, &children);
        if self
            .history
            .iter()
            .filter(|&&previous| previous == key)
            .count()
            >= 2
            || (!matches!(position.variant, Variant::Antichess | Variant::Crazyhouse)
                && position.halfmove >= 100)
        {
            return Some((0, Vec::new()));
        }
        let in_check = position.in_check(position.turn);
        if ply >= MAX_PLY {
            return Some((evaluate(position, nnue)?, Vec::new()));
        }
        let compulsory_capture = position.variant == Variant::Antichess
            && children.iter().any(|(mv, _)| position.is_capture(*mv));
        if depth == 0 && !in_check && !compulsory_capture {
            let stand = evaluate(position, nnue)?;
            if stand >= beta {
                return Some((stand, Vec::new()));
            }
            alpha = alpha.max(stand);
            if position.variant != Variant::Antichess
                || !children.iter().any(|(m, _)| position.is_capture(*m))
            {
                children.retain(|(mv, _)| position.is_capture(*mv) || mv.promotion.is_some());
            }
        }
        children.sort_by_key(|(mv, _)| std::cmp::Reverse(priority(position, *mv)));
        self.history.push(key);
        let mut best = if depth == 0 && !in_check && !compulsory_capture {
            alpha
        } else {
            -MATE
        };
        let mut best_pv = Vec::new();
        for (mv, child) in children {
            let mut child_nnue = nnue.clone();
            child_nnue.update(position, &child).ok()?;
            let result = self.negamax(
                &child,
                &child_nnue,
                depth.saturating_sub(1),
                ply + 1,
                -beta,
                -alpha,
            );
            let Some((score, pv)) = result else {
                self.history.pop();
                return None;
            };
            let score = -score;
            if score > best {
                best = score;
                best_pv.clear();
                best_pv.push(mv);
                best_pv.extend(pv);
            }
            alpha = alpha.max(score);
            if alpha >= beta {
                break;
            }
        }
        self.history.pop();
        Some((best, best_pv))
    }
}

/// Execute iterative deepening with exactly three search lanes.
///
/// # Errors
/// Rejects unbounded limits, unsupported topology and malformed model artifacts.
pub fn search(
    game: &Game,
    limits: SearchLimits,
    stopped: &AtomicBool,
    mut report: impl FnMut(&SearchResult),
) -> Result<SearchResult, &'static str> {
    if limits.movetime.is_zero()
        || limits.movetime > Duration::from_secs(60)
        || limits.depth == 0
        || limits.depth > 64
        || limits
            .soft_time
            .is_some_and(|soft| soft.is_zero() || soft > limits.movetime)
    {
        return Err("invalid bounded native search limits");
    }
    let start = Instant::now();
    let position = game.position();
    let children = position.legal_children();
    let shared = Shared {
        deadline: start + limits.movetime,
        stopped,
        nodes: AtomicU64::new(0),
        node_limit: limits.nodes,
    };
    let mut result = SearchResult {
        best_move: children.first().map(|(mv, _)| *mv),
        depth: 0,
        score: 0,
        pv: Vec::new(),
        nodes: 0,
        elapsed: Duration::ZERO,
        stop_reason: StopReason::Terminal,
        emergency: !children.is_empty(),
    };
    if children.is_empty() {
        result.score = terminal(position, &children, 0).unwrap_or(0);
        return Ok(result);
    }
    let state = NnueState::refresh(position)?;
    let mut history: Vec<_> = game
        .position_history()
        .map(|p| key(p, &p.legal_children()))
        .collect();
    history.push(key(position, &children));
    for depth in 1..=limits.depth {
        let iterations = std::thread::scope(|scope| {
            let jobs: Vec<_> = (0..SEARCH_THREADS)
                .map(|lane| {
                    let history = history.clone();
                    let shared = &shared;
                    let state = &state;
                    let children = &children;
                    scope.spawn(move || {
                        let mut context = Lane { shared, history };
                        let mut scores = Vec::new();
                        for (index, (mv, child)) in children
                            .iter()
                            .enumerate()
                            .filter(|(i, _)| i % SEARCH_THREADS == lane)
                        {
                            let mut nnue = state.clone();
                            nnue.update(position, child).ok()?;
                            let (score, pv) =
                                context.negamax(child, &nnue, depth - 1, 1, -MATE, MATE)?;
                            let mut line = vec![*mv];
                            line.extend(pv);
                            scores.push((index, -score, line));
                        }
                        Some(scores)
                    })
                })
                .collect();
            jobs.into_iter()
                .map(|job| job.join().ok().flatten())
                .collect::<Option<Vec<_>>>()
        });
        let Some(iterations) = iterations else {
            break;
        };
        let mut scores: Vec<_> = iterations.into_iter().flatten().collect();
        scores.sort_by_key(|(index, score, _)| (std::cmp::Reverse(*score), *index));
        if let Some((index, score, pv)) = scores.first() {
            result.best_move = Some(children[*index].0);
            result.score = *score;
            result.pv.clone_from(pv);
            result.depth = depth;
            result.nodes = shared.nodes.load(Ordering::Relaxed);
            result.elapsed = start.elapsed();
            result.emergency = false;
            report(&result);
        }
        if stopped.load(Ordering::Relaxed)
            || Instant::now() >= shared.deadline
            || limits.soft_time.is_some_and(|soft| start.elapsed() >= soft)
        {
            break;
        }
    }
    result.nodes = shared.nodes.load(Ordering::Relaxed);
    result.elapsed = start.elapsed();
    result.stop_reason = stop_reason(&result, limits, &shared);
    Ok(result)
}

fn stop_reason(result: &SearchResult, limits: SearchLimits, shared: &Shared<'_>) -> StopReason {
    if shared.stopped.load(Ordering::Relaxed) {
        StopReason::ExternalStop
    } else if limits.nodes.is_some_and(|limit| result.nodes >= limit) {
        StopReason::NodeLimit
    } else if result.depth == limits.depth {
        StopReason::Depth
    } else if result.depth > 0
        && limits.soft_time.is_some_and(|soft| result.elapsed >= soft)
        && Instant::now() < shared.deadline
    {
        StopReason::SoftLimit
    } else {
        StopReason::HardLimit
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn mate_defense_and_bounded_cancellation() {
        let game =
            Game::from_fen("6k1/5ppp/8/8/8/8/5PPP/3Q2K1 w - - 0 1", Variant::Standard).unwrap();
        let result = search(
            &game,
            SearchLimits {
                movetime: Duration::from_secs(1),
                soft_time: None,
                depth: 2,
                nodes: Some(10_000),
            },
            &AtomicBool::new(false),
            |_| {},
        )
        .unwrap();
        assert!(result.depth >= 1);
        assert!(
            game.position()
                .legal_moves()
                .contains(&result.best_move.unwrap())
        );
        assert!(result.nodes <= 10_000);
        let result = search(
            &game,
            SearchLimits {
                movetime: Duration::from_secs(1),
                depth: 8,
                soft_time: None,
                nodes: None,
            },
            &AtomicBool::new(true),
            |_| {},
        )
        .unwrap();
        assert!(result.emergency);
        assert_eq!(result.stop_reason, StopReason::ExternalStop);
        assert!(result.elapsed < Duration::from_millis(100));
    }

    #[test]
    fn variant_terminal_positions_have_no_submitted_move() {
        let game = Game::from_fen("7k/8/8/8/4K3/8/8/8 w - - 0 1", Variant::KingOfTheHill).unwrap();
        let result = search(
            &game,
            SearchLimits {
                movetime: Duration::from_millis(250),
                depth: 3,
                soft_time: None,
                nodes: None,
            },
            &AtomicBool::new(false),
            |_| {},
        )
        .unwrap();
        assert!(result.best_move.is_none());
        assert_eq!(result.stop_reason, StopReason::Terminal);
    }
}
