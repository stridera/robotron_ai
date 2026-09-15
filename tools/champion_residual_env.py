"""Fresh-episode Gym wrapper around the *current calibrated* champion lab.

No save-state branching and no legacy shaped reward. Emulator recovery or
persistent score corruption truncates at the last valid observation; evaluation
always rejects the entire episode. Invalid data never supplies reward labels.
"""
import json
import importlib
import os
from pathlib import Path
import random
import sys
from collections import deque

import gymnasium as gym
import numpy as np


class ChampionResidualEnv(gym.Env):
    def __init__(self, source, output, rank=0, seed_base=91026000, port=29000):
        super().__init__()
        sys.path.insert(0, str(source))
        import mame_lab as lab
        import residual_policy as rp
        self.lab, self.rp = lab, rp
        self.output = Path(output) / f'worker_{rank}'
        self.output.mkdir(parents=True, exist_ok=True)
        self.rank, self.seed_base, self.port = rank, seed_base, port + rank
        self.episode = 0
        self.env = None
        self.probe_obs = deque(maxlen=512)
        self.action_space = gym.spaces.Discrete(3)
        self.observation_space = gym.spaces.Box(-2, 2, (rp.FEATURE_DIM,), np.float32)
        lab.setup_fsm(str(Path(source) / 'fsm_evolved_planner_v2_hunt.json'))

    def reset(self, *, seed=None, options=None):
        super().reset(seed=seed)
        self.close()
        importlib.reload(self.lab.fsm)
        importlib.reload(self.lab.cp)
        self.lab.setup_fsm(str(Path(self.lab.__file__).parent / 'fsm_evolved_planner_v2_hunt.json'))
        self.episode += 1
        episode_seed = (self.seed_base + self.rank * 1000003 + self.episode * 7919) % 2147483648
        if options and 'rom_seed' in options:
            episode_seed = int(options['rom_seed'])
        defect_seed = ((episode_seed * 2654435761) % 4294967296
                       if not options or 'defect_seed' not in options else int(options['defect_seed']))
        stem = self.output / f'episode_{self.episode:06d}'
        state = self.output / f'states_{self.episode:06d}'
        state.mkdir()
        os.environ.update(MAME_RL_SEED_BASE=str(episode_seed), MAME_STATE_DIR=str(state),
                          MAME_LOG=str(stem) + '.mame.log')
        # The bridge reads this constant at import, so update it before launching
        # each fresh emulator. There is one wrapper per worker process.
        import mame_bridge
        mame_bridge.STATE_DIR = str(state)
        self.env = self.lab.MameRobotronEnv(base_port=self.port, frameskip=4,
                                           reset_pool=[0], obs_mode='slot')
        self.game = self.lab.decision_game(self.env, 'train', f'{self.rank}-{self.episode}',
                      str(stem) + '.jsonl', 20000,
                      random.Random(defect_seed), 26)
        self.context = next(self.game)
        self.score0 = self.context['score']
        self.overrides = self.decisions = 0
        return self.rp.features(self.context), {}

    def step(self, action):
        before = self.context
        override = self.rp.corrected_action(before, int(action))
        self.overrides += int(override is not None)
        self.decisions += 1
        terminal = False
        try:
            after = self.game.send(override)
        except RuntimeError as error:
            if not str(error).startswith(('RECOVERED_EPISODE', 'INVALID_SCORE_PERSISTENT')):
                raise
            # Keep preceding valid training transitions, discard this invalid
            # transition, and bootstrap at its last known valid observation.
            # Do not fabricate a death, income, or an observation after restart.
            info = dict(score=before['score'], wave=before['wave'], deaths=before['deaths'],
                        net=(before['score'] - self.score0) / 25000 - before['deaths'],
                        override_fraction=self.overrides / self.decisions, valid=0,
                        invalid_reason=str(error))
            with (self.output / 'invalid.log').open('a') as f:
                f.write(json.dumps(dict(episode=self.episode, **info)) + '\n')
            self.close()
            return self.rp.features(before), 0.0, False, True, info
        except StopIteration as result:
            wave, score, deaths, steps = result.value
            after = dict(score=score, deaths=deaths, wave=wave, steps=steps)
            terminal = True
        reward = (after['score'] - before['score']) / 1000.0 - 25 * (after['deaths'] - before['deaths'])
        info = {}
        if terminal:
            info = dict(score=after['score'], wave=after['wave'], deaths=after['deaths'],
                        net=(after['score'] - self.score0) / 25000 - after['deaths'],
                        override_fraction=self.overrides / self.decisions, valid=1)
            with (self.output / 'episodes.log').open('a') as f:
                f.write(json.dumps(dict(episode=self.episode, **info)) + '\n')
            obs = np.zeros(self.rp.FEATURE_DIM, np.float32)
            self.close()
        else:
            self.context = after
            obs = self.rp.features(after)
            if self.rank == 0 and self.decisions % 64 == 0:
                self.probe_obs.append(obs.copy())
                if self.decisions % 1024 == 0:
                    np.save(self.output / 'probe_obs.npy', np.asarray(self.probe_obs))
        return obs, reward, terminal, False, info

    def close(self):
        if self.env is not None:
            self.env.close()
            self.env = None
