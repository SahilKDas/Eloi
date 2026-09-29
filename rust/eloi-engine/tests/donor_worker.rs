//! Explicit integration gate for the locally compiled, model-verified worker.

use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::Duration;

use eloi_core::Variant;
use eloi_core::game::Game;
use eloi_core::position::INITIAL_FEN;
use eloi_engine::worker::DonorWorker;

#[test]
#[ignore = "requires ELOI_TEST_VIRIDITHAS_WORKER pointing to the compiled donor"]
fn contained_donor_search_reset_stop_and_variant_refusal() {
    let path = PathBuf::from(
        std::env::var_os("ELOI_TEST_VIRIDITHAS_WORKER").expect("explicit compiled worker path"),
    );
    let mut worker = DonorWorker::start(&path).expect("worker startup");
    let mut game = Game::from_fen(INITIAL_FEN, Variant::Standard).unwrap();
    assert!(game.push_uci("e2e4"));
    assert!(game.push_uci("e7e5"));
    let result = worker
        .search(&game, Duration::from_millis(250), &AtomicBool::new(false))
        .expect("bounded legal search");
    assert!(result.depth > 0);
    assert!(game.position().legal_moves().contains(&result.best_move));
    assert!(result.elapsed < Duration::from_millis(400));
    worker.new_game().expect("new-game readiness");
    let variant = Game::from_fen(INITIAL_FEN, Variant::Atomic).unwrap();
    assert!(
        worker
            .search(
                &variant,
                Duration::from_millis(250),
                &AtomicBool::new(false)
            )
            .is_err()
    );
    let stop = Arc::new(AtomicBool::new(false));
    let trigger = Arc::clone(&stop);
    let timer = std::thread::spawn(move || {
        std::thread::sleep(Duration::from_millis(60));
        trigger.store(true, Ordering::Relaxed);
    });
    let result = worker
        .search(&game, Duration::from_secs(1), &stop)
        .expect("external stop");
    timer.join().unwrap();
    assert!(result.externally_stopped);
    assert!(result.elapsed < Duration::from_millis(500));
}
