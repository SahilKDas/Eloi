"""Report-only audit of quantized warm-start capacity; no candidate changes."""
import argparse
import json
import numpy as np
import run_fresh_nnue_campaign as campaign


def channel_stats(model):
    weights, bias, output = model
    nonzero_inputs = np.count_nonzero(weights, axis=0)
    dead = (nonzero_inputs == 0) & (output == 0)
    return {'hidden_channels': int(output.size),
            'nonzero_output_coefficients': int(np.count_nonzero(output)),
            'zero_input_and_output_channels': int(np.count_nonzero(dead)),
            'zero_input_and_output_indices': np.flatnonzero(dead).tolist(),
            'bias_min_max': [float(bias.min()), float(bias.max())]}


def audit():
    root, work, trainer, data = campaign.ROOT, campaign.WORK, campaign.trainer, campaign.data
    production_path = root / 'include/eloi/nnue_weights.hpp'
    production = trainer.load_quantized_header(production_path)
    dead = (np.count_nonzero(production[0], axis=0) == 0) & (production[2] == 0)
    reports = []
    for name in ('A', 'B', 'C', 'blend25', 'blend50'):
        header = work / 'candidates' / name / 'include/eloi/nnue_weights.hpp'
        model = trainer.load_quantized_header(header)
        floating = campaign.checkpoint_model(name)
        reports.append({'candidate': name, 'header_sha256': data.sha(header),
            'quantized': channel_stats(model),
            'float': channel_stats(floating),
            'production_dead_channels_still_zero_in_float': bool(
                np.all(floating[0][:, dead] == 0) and np.all(floating[2][dead] == 0)),
            'changed_quantized_input_weights': int(np.count_nonzero(model[0] != production[0])),
            'changed_float_input_weights': int(np.count_nonzero(floating[0] != production[0])),
            'changed_quantized_biases': int(np.count_nonzero(model[1] != production[1])),
            'changed_quantized_output_weights': int(np.count_nonzero(model[2] != production[2]))})
    return {'purpose': 'diagnostic only; no training, selection, or held-out target access',
            'production_header_sha256': data.sha(production_path),
            'trainer_sha256': data.sha(root / 'scripts/train_nnue.py'),
            'audit_script_sha256': data.sha(__file__),
            'production': channel_stats(production), 'candidates': reports,
            'invariant': 'With an all-zero input column and zero output coefficient, both perspectives have the same activation; output gradient is zero and input gradient is multiplied by the zero output. Both existing optimizers preserve this state exactly.',
            'interpretation': 'More data alone cannot activate these channels under this warm-start/update procedure. This does not establish the cause of any individual engine regression.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--freeze', action='store_true')
    args = parser.parse_args()
    result = audit()
    if args.freeze:
        campaign.data.immutable_json(campaign.WORK / 'channel-capacity-audit.json', result)
    print(json.dumps(result, indent=2))
