//! Conservative Eloi-native reference search for migration validation.
//!
//! This establishes legal, cancellable three-lane alpha-beta with exact Eloi
//! model arithmetic. Selective search and endgame knowledge require subsequent
//! parity gates before this profile is eligible to replace the legacy search.

use std::sync::Mutex;
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
    /// Total transposition-table budget shared by all three lanes.
    pub hash_mb: u16,
    /// Root-score noise range in millipawns; zero is deterministic.
    pub noise_millipawns: u16,
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
    table: &'a mut Table,
    quiet_history: [[i32; 64]; 64],
    killers: [[Option<Move8>; 2]; MAX_PLY as usize],
}

#[derive(Clone, Copy, Default)]
struct Entry {
    key: u64,
    score: i32,
    depth: u8,
    bound: i8,
    best: Option<Move8>,
}

struct Table(Vec<Entry>);

impl Table {
    fn new(bytes: usize) -> Self {
        let entries = bytes / std::mem::size_of::<Entry>();
        Self(vec![Entry::default(); entries])
    }

    fn probe(&self, key: u64) -> Option<Entry> {
        self.index(key)
            .map(|index| self.0[index])
            .filter(|entry| entry.key == key)
    }

    fn index(&self, key: u64) -> Option<usize> {
        let length = u64::try_from(self.0.len()).ok()?;
        (length != 0)
            .then(|| usize::try_from(key % length).ok())
            .flatten()
    }

    fn store(&mut self, entry: Entry) {
        if entry.score.abs() >= MATE - 1024 {
            return;
        }
        let Some(index) = self.index(entry.key) else {
            return;
        };
        if self.0[index].key != entry.key || self.0[index].depth <= entry.depth {
            self.0[index] = entry;
        }
    }
}

fn tt_bound(score: i32, alpha: i32, beta: i32) -> i8 {
    if score <= alpha {
        -1
    } else {
        i8::from(score >= beta)
    }
}

fn valid_limits(limits: SearchLimits) -> bool {
    !limits.movetime.is_zero()
        && limits.movetime <= Duration::from_hours(24)
        && (1..=64).contains(&limits.depth)
        && limits.hash_mb <= 1024
        && limits.noise_millipawns <= 10_000
        && !limits
            .soft_time
            .is_some_and(|soft| soft.is_zero() || soft > limits.movetime)
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
    if position.variant == Variant::Horde {
        return Some(horde_evaluate(position));
    }
    if position.variant == Variant::Crazyhouse {
        return Some(crazyhouse_evaluate(position));
    }
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

fn crazyhouse_evaluate(position: &Position) -> i32 {
    let board_value = |piece: PieceKind| match piece {
        PieceKind::Pawn => 100,
        PieceKind::Knight => 320,
        PieceKind::Bishop => 330,
        PieceKind::Rook => 500,
        PieceKind::Queen => 900,
        PieceKind::King => 0,
    };
    // Pocket material is deliberately worth more than material already on the
    // board: a drop has no travel time and can create an immediate check.
    let pocket_values = [115, 365, 355, 545, 980];
    let mut white = 0;
    let mut black = 0;
    for piece in position.cells.iter().flatten() {
        let value = board_value(piece.kind);
        if piece.owner == eloi_core::Player::White {
            white += value;
        } else {
            black += value;
        }
    }
    for (count, value) in position.pockets[0].iter().zip(pocket_values) {
        white += i32::from(*count) * value;
    }
    for (count, value) in position.pockets[1].iter().zip(pocket_values) {
        black += i32::from(*count) * value;
    }

    // Reward legal checking drops without recursively invoking search. This is
    // intentionally small: alpha-beta remains authoritative over tactics.
    let checking_drops = i32::try_from(
        position
            .legal_children()
            .into_iter()
            .filter(|(mv, child)| {
                matches!(mv.kind, MoveKind::Drop(_)) && child.in_check(child.turn)
            })
            .count(),
    )
    .unwrap_or(0);
    let signed = white - black;
    if position.turn == eloi_core::Player::White {
        signed + checking_drops * 28
    } else {
        -signed + checking_drops * 28
    }
}

fn horde_evaluate(position: &Position) -> i32 {
    let mut score = 0;
    for (square, piece) in position.cells.iter().enumerate() {
        let Some(piece) = piece else {
            continue;
        };
        let value = match piece.kind {
            PieceKind::Pawn => {
                100 + if piece.owner == eloi_core::Player::White {
                    i32::try_from(square / 8).unwrap_or(0) * 6
                } else {
                    0
                }
            }
            PieceKind::Bishop | PieceKind::Knight => 300,
            PieceKind::Rook => 500,
            PieceKind::Queen => 900,
            PieceKind::King => 0,
        };
        score += if piece.owner == eloi_core::Player::White {
            value
        } else {
            -value
        };
    }
    if let Some(king) = position.king(eloi_core::Player::Black) {
        score += i32::from(position.attackers(king, eloi_core::Player::White)) * 45;
    }
    if position.turn == eloi_core::Player::White {
        score
    } else {
        -score
    }
}

impl Lane<'_> {
    fn move_priority(
        &self,
        position: &Position,
        mv: Move8,
        tt_move: Option<Move8>,
        ply: u16,
    ) -> i32 {
        let history = mv.from.map_or(0, |from| {
            self.quiet_history[usize::from(from.index())][usize::from(mv.to.index())]
        });
        let killer = self.killers.get(usize::from(ply)).map_or(0, |moves| {
            if moves.contains(&Some(mv)) { 80_000 } else { 0 }
        });
        priority(position, mv) + history + killer + if Some(mv) == tt_move { 1_000_000 } else { 0 }
    }

    fn reward_cutoff(&mut self, position: &Position, mv: Move8, depth: u8, ply: u16) {
        if position.is_capture(mv) || mv.promotion.is_some() {
            return;
        }
        if let Some(from) = mv.from {
            let score =
                &mut self.quiet_history[usize::from(from.index())][usize::from(mv.to.index())];
            *score = score.saturating_add(i32::from(depth).pow(2).min(4096));
        }
        if let Some(killers) = self.killers.get_mut(usize::from(ply))
            && killers[0] != Some(mv)
        {
            killers[1] = killers[0];
            killers[0] = Some(mv);
        }
    }

    fn tt_lookup(
        &self,
        key: u64,
        depth: u8,
        alpha: i32,
        beta: i32,
    ) -> (Option<Entry>, Option<(i32, Vec<Move8>)>) {
        let entry = (depth > 0).then(|| self.table.probe(key)).flatten();
        let cutoff = entry.filter(|hit| {
            hit.depth >= depth
                && (hit.bound == 0
                    || (hit.bound < 0 && hit.score <= alpha)
                    || (hit.bound > 0 && hit.score >= beta))
        });
        let result = cutoff.map(|hit| {
            let pv = if hit.bound == 0 {
                hit.best.into_iter().collect()
            } else {
                Vec::new()
            };
            (hit.score, pv)
        });
        (entry, result)
    }

    // Keeping the complete alpha/beta window transition in one routine makes
    // fail-high re-search and cancellation cleanup auditable together.
    #[allow(clippy::too_many_lines)]
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
        let position_key = key(position, &children);
        if self
            .history
            .iter()
            .filter(|&&previous| previous == position_key)
            .count()
            >= 2
            || (!matches!(position.variant, Variant::Antichess | Variant::Crazyhouse)
                && position.halfmove >= 100)
            || position.insufficient_material()
        {
            return Some((0, Vec::new()));
        }
        let in_check = position.in_check(position.turn);
        if ply >= MAX_PLY {
            return Some((evaluate(position, nnue)?, Vec::new()));
        }
        let original_alpha = alpha;
        let (entry, cutoff) = self.tt_lookup(position_key, depth, alpha, beta);
        if cutoff.is_some() {
            return cutoff;
        }
        let tt_move = entry.and_then(|entry| entry.best);
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
        children.sort_by_key(|(mv, _)| {
            std::cmp::Reverse(self.move_priority(position, *mv, tt_move, ply))
        });
        self.history.push(position_key);
        let mut best = if depth == 0 && !in_check && !compulsory_capture {
            alpha
        } else {
            -MATE
        };
        let mut best_pv = Vec::new();
        for (index, (mv, child)) in children.into_iter().enumerate() {
            let mut child_nnue = nnue.clone();
            child_nnue.update(position, &child).ok()?;
            let child_depth = depth.saturating_sub(1);
            let reducible = index >= 4
                && depth >= 3
                && !in_check
                && matches!(position.variant, Variant::Standard | Variant::Chess960)
                && !position.is_capture(mv)
                && mv.promotion.is_none()
                && !child.in_check(child.turn);
            let probe_depth = child_depth.saturating_sub(u8::from(reducible));
            let mut result = if index == 0 {
                self.negamax(&child, &child_nnue, child_depth, ply + 1, -beta, -alpha)
            } else {
                self.negamax(
                    &child,
                    &child_nnue,
                    probe_depth,
                    ply + 1,
                    -alpha - 1,
                    -alpha,
                )
            };
            if index != 0
                && result.as_ref().is_some_and(|(score, _)| -score > alpha)
                && probe_depth != child_depth
            {
                result = self.negamax(
                    &child,
                    &child_nnue,
                    child_depth,
                    ply + 1,
                    -alpha - 1,
                    -alpha,
                );
            }
            if index != 0
                && result
                    .as_ref()
                    .is_some_and(|(score, _)| (-score > alpha) && (-score < beta))
            {
                result = self.negamax(&child, &child_nnue, child_depth, ply + 1, -beta, -alpha);
            }
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
                self.reward_cutoff(position, mv, depth, ply);
                break;
            }
        }
        self.history.pop();
        if depth > 0 {
            self.table.store(Entry {
                key: position_key,
                score: best,
                depth,
                bound: tt_bound(best, original_alpha, beta),
                best: best_pv.first().copied(),
            });
        }
        Some((best, best_pv))
    }
}

fn root_iteration(
    position: &Position,
    children: &[(Move8, Position)],
    state: &NnueState,
    history: &[u64],
    shared: &Shared<'_>,
    tables: &[Mutex<Table>],
    iteration: (u8, u16),
) -> Option<Vec<(usize, i32, Vec<Move8>)>> {
    let (depth, noise_millipawns) = iteration;
    std::thread::scope(|scope| {
        let jobs: Vec<_> = (0..SEARCH_THREADS)
            .map(|lane| {
                let history = history.to_vec();
                scope.spawn(move || {
                    let mut table = tables[lane].lock().ok()?;
                    let mut context = Lane {
                        shared,
                        history,
                        table: &mut table,
                        quiet_history: [[0; 64]; 64],
                        killers: [[None; 2]; MAX_PLY as usize],
                    };
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
                        scores.push((
                            index,
                            -score + root_noise(position, *mv, noise_millipawns),
                            line,
                        ));
                    }
                    Some(scores)
                })
            })
            .collect();
        jobs.into_iter()
            .map(|job| job.join().ok().flatten())
            .collect::<Option<Vec<_>>>()
            .map(|iterations| iterations.into_iter().flatten().collect())
    })
}

fn root_noise(position: &Position, mv: Move8, millipawns: u16) -> i32 {
    if millipawns == 0 {
        return 0;
    }
    let mut mixed = key(position, &position.legal_children());
    for byte in mv.uci(position.variant == Variant::Chess960).bytes() {
        mixed ^= u64::from(byte);
        mixed = mixed.wrapping_mul(0x100_0000_01b3);
    }
    mixed ^= mixed >> 33;
    mixed = mixed.wrapping_mul(0xff51_afd7_ed55_8ccd);
    let range = u64::from(millipawns) * 2 + 1;
    let milli = i32::try_from(mixed % range).unwrap_or(0) - i32::from(millipawns);
    milli / 10
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
    if !valid_limits(limits) {
        return Err("invalid bounded native search limits");
    }
    let start = Instant::now();
    let position = game.position();
    let mut children = position.legal_children();
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
    let table_bytes = usize::from(limits.hash_mb) * 1024 * 1024 / SEARCH_THREADS;
    let tables: Vec<_> = (0..SEARCH_THREADS)
        .map(|_| Mutex::new(Table::new(table_bytes)))
        .collect();
    let mut history: Vec<_> = game
        .position_history()
        .map(|p| key(p, &p.legal_children()))
        .collect();
    history.push(key(position, &children));
    for depth in 1..=limits.depth {
        let Some(mut scores) = root_iteration(
            position,
            &children,
            &state,
            &history,
            &shared,
            &tables,
            (depth, limits.noise_millipawns),
        ) else {
            break;
        };
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
            let preferred = result.best_move;
            children.sort_by_key(|(mv, _)| {
                std::cmp::Reverse(
                    priority(position, *mv) + if Some(*mv) == preferred { 1_000_000 } else { 0 },
                )
            });
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
    fn transposition_table_honors_zero_budget_and_depth_replacement() {
        let mut empty = Table::new(0);
        empty.store(Entry {
            key: 7,
            score: 12,
            depth: 3,
            bound: 0,
            best: None,
        });
        assert!(empty.probe(7).is_none());

        let mut table = Table::new(std::mem::size_of::<Entry>());
        table.store(Entry {
            key: 7,
            score: 12,
            depth: 3,
            bound: 0,
            best: None,
        });
        table.store(Entry {
            key: 7,
            score: 99,
            depth: 2,
            bound: 0,
            best: None,
        });
        assert_eq!(table.probe(7).unwrap().score, 12);
    }

    #[test]
    fn zero_hash_search_remains_legal_and_complete() {
        let game = Game::from_fen(eloi_core::position::INITIAL_FEN, Variant::Standard).unwrap();
        let result = search(
            &game,
            SearchLimits {
                movetime: Duration::from_secs(1),
                soft_time: None,
                depth: 2,
                nodes: Some(20_000),
                hash_mb: 0,
                noise_millipawns: 0,
            },
            &AtomicBool::new(false),
            |_| {},
        )
        .unwrap();
        assert_eq!(result.depth, 2);
        assert!(
            game.position()
                .legal_moves()
                .contains(&result.best_move.unwrap())
        );
    }

    #[test]
    fn horde_keeps_handcrafted_material_without_nnue_tempo() {
        let mut position =
            Position::from_fen(eloi_core::position::HORDE_INITIAL_FEN, Variant::Horde).unwrap();
        assert_eq!(horde_evaluate(&position), 84);
        position.turn = eloi_core::Player::Black;
        assert_eq!(horde_evaluate(&position), -84);
        let position =
            Position::from_fen("4k3/3P1P2/8/8/8/8/8/8 w - - 0 1", Variant::Horde).unwrap();
        assert_eq!(horde_evaluate(&position), 362);
    }

    #[test]
    fn crazyhouse_values_pockets_and_immediate_checking_drops() {
        let white_pocket =
            Position::from_fen("4k3/8/8/8/8/8/8/4K3[Q] w - - 0 1", Variant::Crazyhouse).unwrap();
        let black_pocket =
            Position::from_fen("4k3/8/8/8/8/8/8/4K3[q] w - - 0 1", Variant::Crazyhouse).unwrap();
        assert!(crazyhouse_evaluate(&white_pocket) > 980);
        assert!(crazyhouse_evaluate(&black_pocket) < -900);

        let checking_drop =
            Position::from_fen("7k/8/8/8/8/8/8/K7[R] w - - 0 1", Variant::Crazyhouse).unwrap();
        assert!(crazyhouse_evaluate(&checking_drop) > 545);
    }

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
                hash_mb: 1,
                noise_millipawns: 0,
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
                hash_mb: 1,
                noise_millipawns: 0,
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
                hash_mb: 1,
                noise_millipawns: 0,
            },
            &AtomicBool::new(false),
            |_| {},
        )
        .unwrap();
        assert!(result.best_move.is_none());
        assert_eq!(result.stop_reason, StopReason::Terminal);
    }
}
