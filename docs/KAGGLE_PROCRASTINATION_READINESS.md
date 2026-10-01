# Kaggle Procrastination Readiness

This is the v4.0.0 side quest where Eloi politely observes that the four-player
training plan cannot fit inside vibes, excuses, or a browser tab that was never
opened.

## Goal

Prepare the local side of the Kaggle workflow for `E4PC-FFA` and `E4PC-Teams`
without committing credentials, private datasets, raw checkpoints, or training
outputs.

This does not train the models yet. It checks that the local scaffold is ready
and that Sahil has left at least one breadcrumb proving the Kaggle account exists.

## Make the Kaggle Bits

1. Create or open a Kaggle account.
2. Create a private notebook for Eloi v4 four-player training.
3. Create a private dataset for resumable shards, manifests, and checkpoints.
4. Keep the dataset private.
5. Do not bypass Kaggle quota. Getting rate-limited by free compute is normal;
   trying to outsmart it is how projects get cursed.

Optional local breadcrumb, ignored by Git:

```json
{
  "dataset": "your-kaggle-name/eloi-four-player-v4-private",
  "notebook": "your-kaggle-name/eloi-four-player-v4-training"
}
```

Save that as `.eloi-kaggle.json` in the repository root, or set one of:

```powershell
$env:ELOI_KAGGLE_DATASET = 'your-kaggle-name/eloi-four-player-v4-private'
$env:ELOI_KAGGLE_NOTEBOOK = 'your-kaggle-name/eloi-four-player-v4-training'
```

The readiness checker only needs the identifier. It does not need a token.

## Local Dry Runs

Run the original scaffold directly:

```powershell
python scripts\four_player_kaggle_pipeline.py --mode ffa --dry-run
python scripts\four_player_kaggle_pipeline.py --mode teams --dry-run
```

Run the side-quest checker:

```powershell
python scripts\kaggle_readiness_check.py --dry-run-only
```

Expected result: FFA and Teams manifests validate. If no Kaggle breadcrumb
exists, the checker should roast you but not fail the local dry-run-only check.

When the Kaggle breadcrumb exists:

```powershell
python scripts\kaggle_readiness_check.py
```

Expected result: all checks pass.

## Expected Manifest Shape

Each dry-run manifest should report:

- `schema: 1`
- `mode: ffa` or `mode: teams`
- `target_positions: 500000`
- `materialized_positions: 512`
- `dry_run: true`
- positive `train`, `validation`, and `sealed-test` split counts
- a 64-character `records_sha256`

## Sahil Procrastination Status

- [ ] Kaggle account exists.
- [ ] Private notebook exists.
- [ ] Private dataset exists.
- [ ] Local `.eloi-kaggle.json` or environment variable points at it.
- [ ] Readiness checker passes without needing `--dry-run-only`.
- [ ] Sahil has stopped treating account creation like a 12-game losing streak.

If the first four boxes are empty, the blocker is not compute, architecture, or
Caissa. It is account creation. Devastating, but curable.

## Boundaries

- Do not commit Kaggle credentials.
- Do not commit private dataset contents.
- Do not commit raw self-play shards or checkpoints.
- Do not run full campaigns locally.
- Do not use free Colab for this chess training.
- Do not treat this side quest as model progress. It is readiness work, not the
  actual `E4PC-FFA` or `E4PC-Teams` training campaign.
