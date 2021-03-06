import gym, requests, json
import numpy as np
import os.path as osp

from gym import spaces
from time import sleep, time
from collections import deque

class AimSensors(gym.Env):

    metadata = {'render.modes': ['human']}

    def __init__(self, env_ip, attack_vectors, cfg_dir, delay=0.1, cfg_episodes=0, cfg_steps=100, stack_size=1):
        super(AimSensors, self).__init__()
        self.env_ip = env_ip
        self.attack_vectors = attack_vectors
        self.delay = delay
        self.stack_size = stack_size
        self.flows = []
        self.flow_stack = deque(maxlen=stack_size)
        self.obs_stack = deque(maxlen=stack_size)
        self.score_stack = deque(maxlen=stack_size)

        # reconfigure backend if needed

        env_cfg_file = osp.join(cfg_dir, '{0}.json'.format(env_ip.split(':')[0]))
        try:
            with open(env_cfg_file, 'r') as f:
                cfg = json.load(f)
        except Exception as e:
            print(e)
            cfg = {}
        if cfg == {}:
            cfg_episodes = np.maximum(cfg_episodes, 2)
        if cfg_episodes > 0:
            cfg = {}
            coeff = {}
            gamma = 0
            for attack in attack_vectors:
                coeff_attack = - np.ones(2)
                while np.any(coeff_attack < 0):
                    print('Configuring backend {0} for {1}'.format(self.env_ip, attack))
                    n_arr = None
                    for e in range(cfg_episodes):
                        if n_arr is None:
                            n_arr = self._calculate_coefficients(attack, cfg_steps)
                        else:
                            n_arr = np.vstack([n_arr, self._calculate_coefficients(attack, cfg_steps)])
                        print(n_arr)
                    g = n_arr[:, 3] / n_arr[:, 2]  # number of resolved packets / number of dns replies
                    a_normal = np.mean(n_arr[:, 3] + n_arr[:, 4])
                    b_normal = np.mean(n_arr[:, 2] * g)
                    a_attack = np.mean(n_arr[:, 0])
                    b_attack = np.mean(n_arr[:, 1])
                    coeff_attack = np.array([a_normal / a_attack, b_normal / b_attack])

                print('Coefficients for {0}: alpha = {1}, beta = {2}'.format(attack, coeff_attack[0], coeff_attack[1]))
                coeff[attack] = {'a': coeff_attack[0], 'b': coeff_attack[1]}
                gamma = np.mean(g)
            cfg['coeff'] = coeff
            cfg['gamma'] = gamma
            with open(env_cfg_file, 'w') as f:
                json.dump(cfg, f)

        # retrieve state and action information

        ready = False
        while not ready:
            try:
                flows, f_state, p_state, stats = self._get_state()
                actions, action_categories = self._get_actions()
                frame_size = len(f_state[0])
                action_size = len(actions)
                self._set_gamma(cfg['gamma'])
                for key in cfg['coeff'].keys():
                    self._set_coeff(key, cfg['coeff'][key]['a'], cfg['coeff'][key]['b'])
                ready = True
                print('Environment {0} has been initialized.'.format(env_ip))
            except Exception as e:
                print(e)
                print('Trying to connect to {0}...'.format(env_ip))
                sleep(1)
        if self.stack_size > 1:
            self.observation_space = spaces.Box(low=0, high=np.inf, shape=(stack_size, frame_size), dtype=np.float32)
        else:
            self.observation_space = spaces.Box(low=0, high=np.inf, shape=(frame_size,), dtype=np.float32)
        self.action_space = spaces.Discrete(action_size)

    def step(self, action_list):
        action_list = np.asarray(action_list, dtype=int)
        t_start = time()
        self._take_action(action_list)
        t_action = time()
        if t_action < t_start + self.delay:
            sleep(t_start + self.delay - t_action)
        f_scores, f_counts = self._get_score()
        scores = f_scores
        self.flows, f_state, p_state, stats = self._get_state()
        if self.stack_size > 1:
            obs, flows = self._stack_obs(f_state, self.flows)
        else:
            obs = f_state
            flows = self.flows
        info = {
            'flows': flows,
            'stats': {
                'n_normal': stats['normal_flow_counts'],
                'n_attack': stats['attack_flow_counts'],
                'n_infected': len(stats['infected_devices'])
            }
        }

        return obs, scores, False, info

    def reset(self):
        self._reset_env()
        self._start_episode()
        self.flow_stack = deque(maxlen=self.stack_size)
        self.obs_stack = deque(maxlen=self.stack_size)
        self.score_stack = deque(maxlen=self.stack_size)
        self.flows, f_state, p_state, stats = self._get_state()
        if self.stack_size > 1:
            obs, flows = self._stack_obs(f_state, self.flows)
        else:
            obs = f_state
            flows = self.flows
        return obs, flows

    def _stack_obs(self, obs, flows):
        self.flow_stack.append(flows)
        self.obs_stack.append(obs)
        obs_s = np.zeros((len(flows), self.observation_space.shape[0], self.observation_space.shape[1]))
        for i,flow in enumerate(flows):
            for j,frame in enumerate(self.flow_stack):
                if flow in frame:
                    k = frame.index(flow)
                    obs_s[i, j, :] = self.obs_stack[j][k]
        return obs_s, flows

    def _stack_score(self, score):
        self.score_stack.append(score)
        all_flows = []
        for frame in self.flow_stack:
            all_flows.extend(frame)
        flows_s = list(set(all_flows))
        score_s = np.zeros(len(flows_s))
        for i,flow in enumerate(flows_s):
            for j,frame in enumerate(self.flow_stack):
                if flow in frame:
                    k = frame.index(flow)
                    score_s[i] += self.score_stack[j][k]
        return score_s / len(self.score_stack)

    def render(self, mode='human', close=False):
        pass

    def _calculate_coefficients(self, attack, cfg_steps):
        self._reset_env()
        self._start_episode(attack)
        sum_deltas = np.zeros(5)
        count_deltas = 0
        self.flows, f_state, p_state, stats = self._get_state()
        t_state = time()
        for step in range(cfg_steps):
            action_list = [0 for _ in self.flows]
            self._take_action(action_list)
            t_action = time()
            if t_action < t_state + self.delay:
                sleep(t_state + self.delay - t_action)
            _, counts = self._get_score()
            self.flows, f_state, p_state, stats = self._get_state()
            count_deltas += 1
            sum_deltas += np.array(counts)
        n_cf = sum_deltas / count_deltas
        return n_cf

    def _get_state(self):
        flows, f_state, p_state, stats = requests.get('http://{0}/state'.format(self.env_ip)).json()
        return flows, f_state, p_state, stats

    def _get_actions(self):
        return requests.get('http://{0}/actions'.format(self.env_ip)).json()

    def _set_gamma(self, g):
        return requests.post('http://{0}/dns_gamma'.format(self.env_ip), json={'gamma': g}).json()

    def _set_coeff(self, attack, a, b):
        return requests.post('http://{0}/score_coeff/{1}'.format(self.env_ip, attack), json={'a': a, 'b': b}).json()

    def _reset_env(self):
        return requests.get('http://{0}/reset'.format(self.env_ip)).json()

    def _start_episode(self, attack=None):
        if attack is None:
            attack = self.attack_vectors[np.random.randint(0, len(self.attack_vectors))]
        else:
            assert attack in self.attack_vectors
        r = requests.post('http://{0}/start_episode'.format(self.env_ip), json={'attack': attack, 'start': self.delay})
        return r.json()

    def _take_action(self, ai):
        if type(ai).__name__ != 'list':
            ai = ai.tolist()
        requests.post('http://{0}/action'.format(self.env_ip), json={'patterns': self.flows, 'action_inds': ai})

    def _get_score(self):
        ready = False
        while not ready:
            try:
                data = requests.get('http://{0}/score'.format(self.env_ip), json={'flows': self.flows}).json()
                ready = True
            except Exception as e:
                print(e)
        return data