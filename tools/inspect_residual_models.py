"""Read-only checkpoint behavior audit on sampled training observations.

This detects degenerate/no-op models. It is not a gameplay evaluation or a
held-out estimate of improvement. Does not run MAME or change training.
"""
import argparse
import json
from pathlib import Path
import sys

import numpy as np


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('run', type=Path)
    args = ap.parse_args()
    sys.path.insert(0, str(args.run / 'source'))
    from residual_policy import ResidualPolicy
    probe = args.run / 'worker_0/probe_obs.npy'
    if not probe.exists():
        print('No observation probe yet')
        return
    obs = np.load(probe, allow_pickle=False)
    rows = []
    for path in sorted(args.run.glob('actor_*.npz')):
        actor = ResidualPolicy(path)
        logits = actor.logits(obs)
        probabilities = np.exp(logits - logits.max(axis=1, keepdims=True))
        probabilities /= probabilities.sum(axis=1, keepdims=True)
        # Every final hidden coordinate is tanh-bounded in [-1, 1]. Therefore
        # bias_difference + L1(weight_difference) is a global upper bound on
        # each alternative's logit minus keep, for ANY observation. A negative
        # bound proves the greedy policy cannot ever override the champion.
        scale = 1 if int(actor.weights['layers']) else 2
        bounds = (actor.weights['ba'][1:] - actor.weights['ba'][0]
                  + scale * np.abs(actor.weights['wa'][1:] - actor.weights['wa'][0]).sum(axis=1))
        row = dict(model=path.name, probe_frames=len(obs),
                   greedy_alternative_logit_upper_bounds=bounds.tolist(),
                   greedy_proven_noop=bool(np.all(bounds < 0)),
                   greedy_override_fraction=float(np.mean(np.argmax(logits, axis=1) != 0)),
                   mean_correction_probability=float(np.mean(1 - probabilities[:, 0])),
                   correction_probability_range=[float(np.min(1-probabilities[:, 0])),
                                                  float(np.max(1-probabilities[:, 0]))])
        rows.append(row)
    print(json.dumps(rows, indent=2))
    (args.run / 'behavior_audit.json').write_text(json.dumps(rows, indent=2))


if __name__ == '__main__':
    main()
