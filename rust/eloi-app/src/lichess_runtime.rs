//! Complete headless native Lichess loop built on the injectable supervisor.

use std::io;
use std::path::Path;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use eloi_core::Player;
use eloi_engine::search::SearchLimits;
use eloi_protocol::bridge::State;
use eloi_protocol::config::RuntimeConfig;
use eloi_protocol::operations_store::OperationsStore;
use eloi_protocol::transport::{Action, Supervisor, Transport};
use eloi_protocol::windows_http::WindowsHttp;

#[derive(Clone, Copy)]
struct EngineSettings {
    depth: u8,
    hash_mb: u16,
    overhead_ms: u32,
}

/// Authenticate and prove cancellation of a real blocked control stream
/// without accepting challenges or issuing any mutating API request.
///
/// # Errors
/// Returns a token-free configuration, authentication, transport, or deadline
/// diagnostic. The token and raw account response are never printed.
pub fn live_smoke(config_path: &Path, legacy_config: bool) -> io::Result<()> {
    let text = std::fs::read_to_string(config_path)?;
    let token = if legacy_config {
        legacy_top_level_token(&text)?
    } else {
        eloi_protocol::config::parse(&text)
            .map_err(io::Error::other)?
            .token
            .expose_for_transport()
            .to_owned()
    };
    let transport = Arc::new(WindowsHttp::new(&token).map_err(io::Error::other)?);
    let reply = transport
        .account(&AtomicBool::new(false))
        .map_err(io::Error::other)?;
    if reply.status != 200 {
        return Err(io::Error::other(format!(
            "Lichess account request returned HTTP {}",
            reply.status
        )));
    }
    let value: serde_json::Value = serde_json::from_slice(&reply.body)
        .map_err(|_| io::Error::other("malformed account response"))?;
    let account = value
        .get("id")
        .and_then(serde_json::Value::as_str)
        .filter(|id| {
            !id.is_empty()
                && id.len() <= 32
                && id
                    .bytes()
                    .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'_' | b'-'))
        })
        .ok_or_else(|| io::Error::other("authenticated account identity malformed"))?
        .to_owned();
    let cancelled = Arc::new(AtomicBool::new(false));
    let stream_cancelled = Arc::clone(&cancelled);
    let stream_transport = Arc::clone(&transport);
    let (send, receive) = std::sync::mpsc::sync_channel(1);
    std::thread::Builder::new()
        .name("eloi-live-cancellation-smoke".into())
        .spawn(move || {
            let result =
                stream_transport.stream("/api/stream/event", &stream_cancelled, &mut |_| true);
            let _ = send.send(result.map(|reply| reply.status));
        })?;
    std::thread::sleep(Duration::from_millis(300));
    let started = std::time::Instant::now();
    cancelled.store(true, Ordering::Relaxed);
    transport.cancel();
    let result = receive.recv_timeout(Duration::from_secs(2)).map_err(|_| {
        io::Error::other("blocked control stream did not cancel within two seconds")
    })?;
    if result.is_ok() {
        return Err(io::Error::other(
            "control stream ended without exercising cancellation",
        ));
    }
    println!(
        "Lichess live smoke PASS: authenticated {account}; blocked stream cancelled in {} ms; no mutating request sent",
        started.elapsed().as_millis()
    );
    Ok(())
}

fn legacy_top_level_token(text: &str) -> io::Result<String> {
    if text.len() > 65_536 {
        return Err(io::Error::other("legacy configuration exceeds 64 KiB"));
    }
    let mut token = None;
    for line in text.trim_start_matches('\u{feff}').lines() {
        if line.starts_with(char::is_whitespace) || !line.starts_with("token:") {
            continue;
        }
        if token.is_some() {
            return Err(io::Error::other("duplicate top-level token setting"));
        }
        let raw = &line["token:".len()..];
        let mut quote = None;
        let mut end = raw.len();
        for (index, character) in raw.char_indices() {
            match character {
                '\'' | '"' if quote == Some(character) => quote = None,
                '\'' | '"' if quote.is_none() => quote = Some(character),
                '#' if quote.is_none() => {
                    end = index;
                    break;
                }
                '\\' if quote == Some('"') => {
                    return Err(io::Error::other(
                        "legacy token escape syntax is unsupported",
                    ));
                }
                _ => {}
            }
        }
        if quote.is_some() {
            return Err(io::Error::other("unterminated legacy token quote"));
        }
        let value = raw[..end].trim();
        let value = if value.len() >= 2
            && ((value.starts_with('"') && value.ends_with('"'))
                || (value.starts_with('\'') && value.ends_with('\'')))
        {
            &value[1..value.len() - 1]
        } else {
            value
        };
        token = Some(value.to_owned());
    }
    token
        .filter(|value| !value.is_empty())
        .ok_or_else(|| io::Error::other("top-level legacy token is missing"))
}

pub fn run(
    config_path: &Path,
    worker_path: Option<&Path>,
    dashboard: Option<&Arc<eloi_ui::OperationsModel>>,
) -> io::Result<()> {
    let text = std::fs::read_to_string(config_path)?;
    let config = eloi_protocol::config::parse(&text).map_err(io::Error::other)?;
    let settings = settings(&config)?;
    let mut store = OperationsStore::local().ok();
    let transport =
        Arc::new(WindowsHttp::new(config.token.expose_for_transport()).map_err(io::Error::other)?);
    if let Some(model) = dashboard {
        let model = Arc::clone(model);
        let cancellable = Arc::clone(&transport);
        std::thread::Builder::new()
            .name("eloi-dashboard-cancellation".into())
            .spawn(move || {
                loop {
                    if model.stop_requested() {
                        eloi_protocol::transport::Transport::cancel(cancellable.as_ref());
                        break;
                    }
                    if model.reconnect_requested() {
                        eloi_protocol::transport::Transport::cancel(cancellable.as_ref());
                        while model.reconnect_requested() && !model.stop_requested() {
                            std::thread::sleep(Duration::from_millis(10));
                        }
                    }
                    std::thread::sleep(Duration::from_millis(20));
                }
            })?;
    }
    let donor = worker_path
        .map(eloi_engine::worker::DonorWorker::start)
        .transpose()?
        .map(|worker| Arc::new(Mutex::new(worker)));
    let mut supervisor = Supervisor::new(transport, config);
    publish(&supervisor, dashboard.map(Arc::as_ref), &mut store);
    connect_with_retry(&mut supervisor, dashboard.map(Arc::as_ref), &mut store)?;
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
            Err(_error)
                if dashboard
                    .map(Arc::as_ref)
                    .is_some_and(eloi_ui::OperationsModel::take_reconnect) =>
            {
                if supervisor.controller.reconnect_now() {
                    connect_with_retry(&mut supervisor, dashboard.map(Arc::as_ref), &mut store)?;
                }
            }
            Err(error) => match supervisor.controller.snapshot().state {
                State::BackingOff => {
                    connect_with_retry(&mut supervisor, dashboard.map(Arc::as_ref), &mut store)?;
                }
                State::Fatal | State::Stopping | State::Stopped => {
                    return Err(io::Error::other(error));
                }
                _ => return Err(io::Error::other(error)),
            },
        }
        publish(&supervisor, dashboard.map(Arc::as_ref), &mut store);
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
    store: &mut Option<OperationsStore>,
) -> io::Result<()> {
    loop {
        match supervisor.connect() {
            Ok(()) => {
                publish(supervisor, dashboard, store);
                return Ok(());
            }
            Err(_error) if supervisor.controller.snapshot().state == State::BackingOff => {
                publish(supervisor, dashboard, store);
                let seconds = supervisor.controller.snapshot().retry_seconds;
                for _ in 0..seconds.saturating_mul(20) {
                    if dashboard.is_some_and(eloi_ui::OperationsModel::reconnect_requested) {
                        let _ = dashboard.map(eloi_ui::OperationsModel::take_reconnect);
                        let _ = supervisor.controller.reconnect_now();
                        break;
                    }
                    std::thread::sleep(Duration::from_millis(50));
                }
            }
            Err(error) => return Err(io::Error::other(error)),
        }
    }
}

fn publish(
    supervisor: &Supervisor<WindowsHttp>,
    dashboard: Option<&eloi_ui::OperationsModel>,
    store: &mut Option<OperationsStore>,
) {
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
    if let Some(dashboard) = dashboard {
        dashboard.publish(eloi_ui::OperationsSnapshot {
            state,
            accepting: snapshot.accepting,
            wins: snapshot.counters.wins,
            draws: snapshot.counters.draws,
            losses: snapshot.counters.losses,
            incidents: snapshot.counters.incidents,
        });
    }
    if let Some(store) = store
        && let Err(error) = store.publish(snapshot)
    {
        eprintln!("Operations evidence unavailable: {error}");
    }
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

#[cfg(test)]
mod tests {
    use super::legacy_top_level_token;

    #[test]
    fn legacy_smoke_reader_accepts_only_one_top_level_token() {
        let token = legacy_top_level_token(
            "token: 'lip_example' # private credential\nengine:\n  token: ignored\n",
        )
        .unwrap();
        assert_eq!(token, "lip_example");
        assert!(legacy_top_level_token("engine:\n  token: nested\n").is_err());
        assert!(legacy_top_level_token("token: first\ntoken: second\n").is_err());
    }
}
