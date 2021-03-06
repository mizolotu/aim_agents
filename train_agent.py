import sys, json, os
os.environ["CUDA_VISIBLE_DEVICES"] = "-1"

from environments.aim_sensors import AimSensors
from algorithms.bs_common.vec_env import SubprocVecEnv
from algorithms.flow_ppo.ppo import learn as learn_ppo
from algorithms.flow_dqn.deepq import learn as learn_dqn

def create_env(env, attack_vectors, cfg_dir, stack_size):
    return lambda : AimSensors(env, attack_vectors, cfg_dir, stack_size=stack_size)

if __name__ == '__main__':

    # parse arguments, substitute to parsearg later

    alg_cfg_file = sys.argv[1]
    env_inds = [int(idx) for idx in sys.argv[2].split(',')]
    av_inds = [int(idx) for idx in sys.argv[3].split(',')]

    # environment backend ips

    env_urls = [
        '192.168.176.10:5000',
        '192.168.176.11:5000',
        '192.168.176.12:5000',
        '192.168.176.13:5000',
        '192.168.176.14:5000',
        '192.168.176.15:5000'
    ]

    # attack vectors

    attack_vectors = [
        'botnet_attack',
        'exfiltration_attack',
        'scan_attack',
        'exploit_attack',
        'slowloris_attack'
    ]

    # experiment parameters

    env_cfg_dir = 'environment_coefficients'
    alg_cfg_dir = 'algorithm_configurations'
    envs = [env_urls[idx] for idx in env_inds]
    avs = [attack_vectors[idx] for idx in av_inds]
    log_prefix = '_'.join(avs)
    with open('{0}/{1}.json'.format(alg_cfg_dir, alg_cfg_file), 'r') as f:
        alg_kwargs = json.load(f)
    alg_kwargs['load_path'] = 'logs/{0}/{1}'.format(log_prefix,alg_kwargs['load_path'])
    if alg_kwargs['network'] == 'cnn':
        stack_size = 4
    else:
        stack_size = 1

    # create environments

    env_fns = [create_env(env, avs, env_cfg_dir, stack_size=stack_size) for env in envs]
    env = SubprocVecEnv(env_fns)

    # start training

    algorithm = alg_cfg_file.split('_')[0]
    if algorithm == 'ppo':
        learn = learn_ppo
    elif algorithm == 'dqn':
        learn = learn_dqn
    learn(env=env, log_prefix=log_prefix, **alg_kwargs)