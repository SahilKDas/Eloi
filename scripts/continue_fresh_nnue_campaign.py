"""Apply the documented runtime-only continuation without altering frozen code.

The current worker is not hot-patched. Invoke this on its next natural stop:
    python scripts/continue_fresh_nnue_campaign.py run
The original runner's OS lock still prevents overlapping workers.
"""
import datetime as dt
from pathlib import Path
import run_fresh_nnue_campaign as campaign


def apply_runtime_extension():
    path = campaign.ROOT / 'data/nnue_fresh_data_continuation.json'
    extension = campaign.read(path)
    if campaign.data.sha(campaign.PROTOCOL) != extension['original_protocol_sha256']:
        raise RuntimeError('runtime extension is not bound to this frozen protocol')
    deadline = dt.datetime.fromisoformat(extension['runtime_deadline_utc'])
    if deadline.tzinfo is None or deadline <= dt.datetime.now(dt.timezone.utc):
        raise RuntimeError('runtime continuation window is invalid or expired')
    campaign.data.immutable_json(campaign.WORK / 'continuation-runtime.json', {
        'extension_sha256': campaign.data.sha(path),
        'wrapper_sha256': campaign.data.sha(Path(__file__)),
        'original_protocol_sha256': extension['original_protocol_sha256'],
        'effective_deadline_utc': deadline.isoformat(),
        'scope': extension['scope']})
    campaign.data.DEADLINE = deadline


if __name__ == '__main__':
    apply_runtime_extension()
    campaign.main()
