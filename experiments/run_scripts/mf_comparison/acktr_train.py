from rllab.misc.instrument import stub, run_experiment_lite
from rllab.policies.gaussian_mlp_policy import GaussianMLPPolicy
import lasagne.nonlinearities as NL
import sys
from sandbox.ours.envs.mujoco import HalfCheetahEnvRandParams, HopperEnvRandParams, AntEnvRandParams

from rllab.misc.instrument import VariantGenerator, variant
from rllab import config
import argparse
import random
import os

from sandbox.ours.envs.mujoco import AntEnvRandParams, HalfCheetahEnvRandParams, HopperEnvRandParams, \
    WalkerEnvRandomParams, SwimmerEnvRandParams, PR2EnvRandParams

import tensorflow as tf
from baselines import logger
from baselines.common.cmd_util import make_mujoco_env, mujoco_arg_parser
from baselines.acktr.acktr_cont import learn
from baselines.acktr.policies import GaussianMlpPolicy
from baselines.acktr.value_functions import NeuralNetValueFunction

EXP_PREFIX = 'acktr-baselines'

ec2_instance = 'c4.xlarge'

# configure instance

subnets = [
    'us-east-2a',
    'us-east-2b',
    'us-east-2c',
]

info = config.INSTANCE_TYPE_INFO[ec2_instance]
config.AWS_INSTANCE_TYPE = ec2_instance
config.AWS_SPOT_PRICE = str(info["price"])


def run_train_task(vv):

    # Create envs.
    env = vv['env'](log_scale_limit=0.0, max_path_length=vv['path_length'])

    with tf.Session(config=tf.ConfigProto()):
        ob_dim = env.observation_space.shape[0]
        ac_dim = env.action_space.shape[0]
        with tf.variable_scope("vf"):
            vf = NeuralNetValueFunction(ob_dim, ac_dim)
        with tf.variable_scope("pi"):
            policy = GaussianMlpPolicy(ob_dim, ac_dim)

        learn(env, policy=policy, vf=vf,
              gamma=vv['discount'], lam=0.97, timesteps_per_batch=vv['batch_size'],
              desired_kl=0.002, num_timesteps=vv['num_timesteps'], max_path_length=vv['path_length'], animate=False)

        env.close()




def run_experiment(argv):

    # -------------------- Parse Arguments -----------------------------------
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', type=str, default='local',
                        help='Mode for running the experiments - local: runs on local machine, '
                             'ec2: runs on AWS ec2 cluster (requires a proper configuration file)')

    args = parser.parse_args(argv[1:])

    # -------------------- Define Variants -----------------------------------

    vg = VariantGenerator()
    vg.add('env', ['HalfCheetahEnvRandParams', 'AntEnvRandParams', 'WalkerEnvRandomParams',
                   'SwimmerEnvRandParams', 'HopperEnvRandParams', 'PR2EnvRandParams'])
    vg.add('total_timesteps', [int(10**8)])
    vg.add('seed', [31, 41, 32])
    vg.add('discount', [0.99])
    vg.add('path_length', [200])
    vg.add('batch_size', [5000])
    vg.add('num_timesteps', [10**7])
    vg.add('hidden_nonlinearity', ['tanh'])
    vg.add('hidden_sizes', [(32, 32)])

    variants = vg.variants()
    from pprint import pprint
    pprint(variants)

    # ----------------------- AWS conficuration ---------------------------------
    if args.mode == 'ec2':
        n_parallel = int(info["vCPU"] / 2)  # make the default 4 if not using ec2
    else:
        n_parallel = 6

    if args.mode == 'ecs':
        print("\n" + "**********" * 10 + "\nexp_prefix: {}\nvariants: {}".format('TRPO', len(variants)))
        print('Running on type {}, with price {}, parallel {} on the subnets: '.format(config.AWS_INSTANCE_TYPE,
                                                                                       config.AWS_SPOT_PRICE,
                                                                                       n_parallel), *subnets)

    # ----------------------- TRAINING ---------------------------------------
    exp_ids = random.sample(range(1, 1000), len(variants))
    for v, exp_id in zip(variants, exp_ids):
        exp_name = "acktr_%s_%i_%i_id_%i" % (v['env'], v['batch_size'], v['seed'], exp_id)

        v['exp_name'] = exp_name
        v['exp_prefix'] = EXP_PREFIX

        v = instantiate_class_stings(v)

        subnet = random.choice(subnets)
        config.AWS_REGION_NAME = subnet[:-1]
        config.AWS_KEY_NAME = config.ALL_REGION_AWS_KEY_NAMES[
            config.AWS_REGION_NAME]
        config.AWS_IMAGE_ID = config.ALL_REGION_AWS_IMAGE_IDS[
            config.AWS_REGION_NAME]
        config.AWS_SECURITY_GROUP_IDS = \
            config.ALL_REGION_AWS_SECURITY_GROUP_IDS[
                config.AWS_REGION_NAME]

        run_experiment_lite(
            run_train_task,
            exp_prefix=EXP_PREFIX,
            exp_name=exp_name,
            # Number of parallel workers for sampling
            n_parallel=n_parallel,
            # Only keep the snapshot parameters for the last iteration
            snapshot_mode="last",
            sync_s3_pkl=True,
            periodic_sync=True,
            # Specifies the seed for the experiment. If this is not provided, a random seed
            # will be used
            seed=v["seed"],
            #sync_all_data_node_to_s3=True,
            python_command="python3", #sys.executable,
            pre_commands=["yes | pip install tensorflow=='1.6.0'",
                          "yes | pip install --upgrade cloudpickle",
                          "yes | pip install gym==0.10.5"],
            mode=args.mode,
            use_cloudpickle=True,
            variant=v,
        )



def instantiate_class_stings(v):
    v['env'] = globals()[v['env']]

    if v['hidden_nonlinearity'] == 'relu':
        v['hidden_nonlinearity'] = NL.rectify
    elif v['hidden_nonlinearity'] == 'tanh':
        v['hidden_nonlinearity'] = NL.tanh
    elif v['hidden_nonlinearity'] == 'elu':
        v['hidden_nonlinearity'] = NL.elu
    else:
        raise NotImplementedError('Not able to recognize spicified hidden_nonlinearity: %s' % v['hidden_nonlinearity'])
    return v

if __name__ == "__main__":
    run_experiment(sys.argv)