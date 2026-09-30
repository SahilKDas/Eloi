//! Complete headless native Lichess loop built on the injectable supervisor.

use std::io;
use std::path::Path;
use std::sync::atomic::AtomicBool;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use eloi_core::Player;
use eloi_engine::search::SearchLimits;
use eloi_protocol::bridge::State;
use eloi_protocol::config::RuntimeConfig;
use eloi_protocol::transport::{Action, Supervisor};
use eloi_protocol::windows_http::WindowsHttp;

#[derive(Clone, Copy)]
struct EngineSettings {
    depth: u8,
    hash_mb: u16,
    overhead_ms: u32,
}

pub fn run(
    config_path: &Path,
    worker_path: Option<&Path>,
    dashboard: Option<&Arc<eloi_ui::OperationsModel>>,
) -> io::Result<()> {
    let text = std::fs::read_to_string(config_path)?;
    let config = eloi_protocol::config::parse(&text).map_err(io::Error::other)?;
    let settings = settings(&config)?;
    let transport =
        Arc::new(WindowsHttp::new(config.token.expose_for_transport()).map_err(io::Error::other)?);
    if let Some(model) = dashboard {
        let model = Arc::clone(model);
        let cancellable = Arc::clone(&transport);
        std::thread::Builder::new()
            .name("eloi-dashboard-cancellation".into())
            .spawn(move || {
                while !model.stop_requested() {
                    std::thread::sleep(Duration::from_millis(20));
                }
                eloi_protocol::transport::Transport::cancel(cancellable.as_ref());
            })?;
    }
    let donor = worker_path
        .map(eloi_engine::worker::DonorWorker::start)
        .transpose()?
        .map(|worker| Arc::new(Mutex::new(worker)));
    let mut supervisor = Supervisor::new(transport, config);
    publish(&supervisor, dashboard.map(Arc::as_ref));
    connect_with_retry(&mut supervisor, dashboard.map(Arc::as_ref))?;
    loop {
        if let Some(model) = dashboard.map(Arc::as_ref) {
            supervisor
                .controller
                .set_accepting(model.snapshot().accepting);
        }
        match supervisor.next_control_action() {
            Ok(action @ (Action::Accept(_) | Action::Decline(_))) => {
                supervisor
                    .challenge_action(&action)
                    .map_err(io::Error::other)?;
            }
            Ok(Action::AttachGame(id)) => {
                let donor = donor.clone();
                supervisor
                    .play_game(&id, |session| {
                        choose_move(session, donor.as_ref(), settings)
                    })
                    .map_err(io::Error::other)?;
            }
            Ok(Action::Ignore) => {}
            Err(error) => match supervisor.controller.snapshot().state {
                State::BackingOff => {
                    connect_with_retry(&mut supervisor, dashboard.map(Arc::as_ref))?;
                }
                State::Fatal | State::Stopping | State::Stopped => {
                    return Err(io::Error::other(error));
                }
                _ => return Err(io::Error::other(error)),
            },
        }
        publish(&supervisor, dashboard.map(Arc::as_ref));
    }
}

fn settings(config: &RuntimeConfig) -> io::Result<EngineSettings> {
    Ok(EngineSettings {
        depth: u8::try_from(config.depth.min(64)).map_err(io::Error::other)?,
        hash_mb: u16::try_from(config.hash_mb.min(1024)).map_err(io::Error::other)?,
        overhead_ms: config.move_overhead_ms,
    })
}

fn connect_with_retry(
    supervisor: &mut Supervisor<WindowsHttp>,
    dashboard: Option<&eloi_ui::OperationsModel>,
) -> io::Result<()> {
    loop {
        match supervisor.connect() {
            Ok(()) => {
                publish(supervisor, dashboard);
                return Ok(());
            }
            Err(_error) if supervisor.controller.snapshot().state == State::BackingOff => {
                publish(supervisor, dashboard);
                let seconds = supervisor.controller.snapshot().retry_seconds;
                std::thread::sleep(Duration::from_secs(u64::from(seconds)));
            }
            Err(error) => return Err(io::Error::other(error)),
        }
    }
}

fn publish(supervisor: &Supervisor<WindowsHttp>, dashboard: Option<&eloi_ui::OperationsModel>) {
    let Some(dashboard) = dashboard else { return };
    let snapshot = supervisor.controller.snapshot();
    let state = match snapshot.state {
        State::Stopped => 0,
        State::Connecting => 1,
        State::Connected => 2,
        State::Playing => 3,
        State::BackingOff => 4,
        State::Fatal => 5,
        State::Stopping => 6,
    };
    dashboard.publish(eloi_ui::OperationsSnapshot {
        state,
        accepting: snapshot.accepting,
        wins: snapshot.counters.wins,
        draws: snapshot.counters.draws,
        losses: snapshot.counters.losses,
        incidents: snapshot.counters.incidents,
    });
}

fn choose_move(
    session: &eloi_protocol::lichess::Session,
    donor: Option<&Arc<Mutex<eloi_engine::worker::DonorWorker>>>,
    settings: EngineSettings,
) -> Result<eloi_core::rules::Move8, &'static str> {
    let position = session.game.position();
    let remaining = if position.turn == Player::White {
        session.state.white_ms
    } else {
        session.state.black_ms
    };
    let increment = if position.turn == Player::White {
        session.state.white_increment_ms
    } else {
        session.state.black_increment_ms
    };
    let remaining = u32::try_from(remaining.min(u64::from(u32::MAX))).unwrap_or(u32::MAX);
    let increment = u32::try_from(increment.min(u64::from(u32::MAX))).unwrap_or(u32::MAX);
    let budget = eloi_engine::time::plan(position, remaining, increment, 0, settings.overhead_ms);
    let hard = Duration::from_millis(budget.hard_ms.max(1));
    let stopped = AtomicBool::new(false);
    if position.variant == eloi_core::Variant::Standard
        && let Some(donor) = donor
    {
        let reserve = hard
            .div_f32(10.0)
            .clamp(Duration::from_millis(15), Duration::from_millis(100));
        let donor_budget = hard.saturating_sub(reserve).max(Duration::from_millis(1));
        if let Ok(report) = donor.lock().map_err(|_| "donor lock poisoned")?.search(
            &session.game,
            donor_budget.min(Duration::from_secs(60)),
            &stopped,
        ) {
            return Ok(report.best_move);
        }
        // The donor's contained failure cannot reuse its expired deadline. The
        // native fallback receives its own reserved, newly-created budget.
        return native_move(session, settings, reserve);
    }
    native_move(session, settings, hard)
}

fn native_move(
    session: &eloi_protocol::lichess::Session,
    settings: EngineSettings,
    hard: Duration,
) -> Result<eloi_core::rules::Move8, &'static str> {
    let stopped = AtomicBool::new(false);
    let soft = hard.mul_f32(0.8).max(Duration::from_millis(1));
    eloi_engine::search::search(
        &session.game,
        SearchLimits {
            movetime: hard,
            soft_time: Some(soft.min(hard)),
            depth: if settings.depth == 0 {
                64
            } else {
                settings.depth
            },
            nodes: None,
            hash_mb: settings.hash_mb,
            noise_millipawns: 0,
        },
        &stopped,
        |_| {},
    )
    .map_err(|_| "native search failed")?
    .best_move
    .ok_or("native search returned no move")
}
