import time
import argparse
import numpy as np
import pandas as pd
import carla
import random

#Local imports
import visdom as vis

from environment import Agent, Environment
from spawn import df_to_spawn_points, numpy_to_transform, set_spectator_above_actor
from control.nn_control import NnA2CController
from control.abstract_control import Controller
from tensorboardX import SummaryWriter

import torch

#Configs
#TODO Add dynamically generated foldername based on config settings and date.
from config import DATA_PATH, STORE_DATA, FRAMERATE, TENSORBOARD_DATA, ALPHA, \
    DATE, SENSORS, VEHICLE, CARLA_IP, LEARNING_RATE, NUMBER_OF_EPOCHS, BATCH_SIZE, RANDOM_SEED, EXP_BUFFER

from utils import save_episode_info, tensorboard_log, visdom_log, visdom_initialize_windows, configure_simulation


def main():
    #set a seed for batch shuffling
    random.seed(RANDOM_SEED)
    #parse args
    #   - GPUS
    #   - CONTROLLER
    #   - LOGGING
    argparser = argparse.ArgumentParser()
    # Simulator configs
    argparser.add_argument(
        '--host',
        metavar='H',
        default=CARLA_IP,
        help='IP of the host server (default: localhost)')
    argparser.add_argument(
        '--port',
        metavar='P',
        default=2000,
        type=int,
        help='Port on the host server (default: 2000)')
    argparser.add_argument(
        '--synchronous',
        metavar='S',
        default=True,
        help='If to run in synchronous mode (currently only this option is avialable)')
    argparser.add_argument(
        '--frames',
        metavar='F',
        default=FRAMERATE,
        type=float,
        help='Number of frames per second, dont set below 10, use with --synchronous flag only')

    #World configs
    argparser.add_argument(
        '--map',
        metavar='M',
        default='circut_spa',
        help='Avialable maps: "circut_spa", "RaceTrack", "Racetrack2". Default: "circut_spa"')
    argparser.add_argument(
        '--vehicle',
        metavar='V',
        default=VEHICLE,
        help='Carla Vehicle blueprint Default: "vehicle.audi.tt"')

    # Simulation
    argparser.add_argument(
        '-s', '--num_steps',
        default=10000,
        type=int,
        dest='num_steps',
        help='Max number of steps per episode, if set to "None" episode will run as long as termiination conditions aren\'t satisfied')

    #Controller configs
    argparser.add_argument(
        '--controller',
        metavar='C',
        default='MPC',
        help='Avialable controllers: "MPC", "NN", Default: "NN"')

    # Logging configs
    argparser.add_argument(
        '--tensorboard',
        metavar='TB',
        default=False,
        help='Decides if to log information to tensorboard (default: False)')

    argparser.add_argument(
        '--visdom',
        metavar='V',
        default=True,
        help='Decides if to log information to visdom, (default: True)')
    parser.add_argument(
        "--cuda",
        default=False,
        action="store_true",
        help="Enable cuda")
    args = argparser.parse_known_args()
    if len(args) > 1:
        args = args[0]
#     return args
    run_learning_session(args)


def run_learning_session(args):
    args = main()
    args.host = 'localhost'
    args.port = 2000
    # Initialize tensorboard -> initialize writer inside run episode so that every
    if args.tensorboard:
        writer = SummaryWriter(f'{TENSORBOARD_DATA}/{args.controller}/{args.map}_TS{TARGET_SPEED}_H{STEPS_AHEAD}_FRAMES{args.frames}_{DATE}',
                               flush_secs=5, max_queue=5)
    elif args.tensorboard:
        writer = SummaryWriter(f'{TENSORBOARD_DATA}/{args.controller}/{args.map}_FRAMES{args.frames}', flush_secs=5)
    else:
        writer = None
    device = torch.device("cuda" if args.cuda else "cpu")

    # args.visdom = False
    viz = vis.Visdom(port=6006) if args.visdom else None

    # Connecting to client -> later package it in function which checks if the world is already loaded and if the settings are the same.
    # In order to host more scripts concurrently
    client = configure_simulation(args)

    # create config dict for raport
    #
    # Here let's create data structure which will let us save summary results from each run_episode iteration
    # for ex. status, distance travelled, reward obtained -> may be dataframe, we'll append each row after iteration

    # load spawnpoints from csv -> generate spawn points from notebooks/20200414_setting_points.ipynb
    spawn_points_df = pd.read_csv(f'{DATA_PATH}/spawn_points/{args.map}.csv')
    spawn_points = df_to_spawn_points(spawn_points_df, n=10000, inverse=False) #We keep it here in order to have one way simulation within one script

    # Controller initialization
    if args.controller is 'NN':
        controller = NnA2CController([8,75,100]).to(device)
        optimizer = torch.optim.Adam(controller.parameters(), lr=LEARNING_RATE, eps=1e-3)

    for epoch_idx in range(NUMBER_OF_EPOCHS):
        print("starting epoch number "+epoch_idx)
        #open MPC batch data source
        batched_data = split_data_into_batches(MPC_data_source)
        for batch in batched_data:
            #batch consists of many episodes
            for episode in batch:
                #4 previous environment states generated by MPC make up an episode
                #we take those 4 into account when feeding into the net 
                status, actor_dict, env_dict, sensor_data = run_episode(client=client,
                                                            controller=controller,
                                                            spawn_points=spawn_points,
                                                            writer=writer,
                                                            viz=viz,
                                                            args=args)
  
                
                steering_angle = float(output[0]['steer'])
                gas_brake_value = float(output[0]['gas_brake'])
                state_value = float(output[1])
                
        if epoch_idx%5==0:
            torch.save(controller.state_dict(), "../models")

    
    """
    TODO
    
    póki co discreet action space, potem do przerobienia na continuous
    
    for epoch in epochs:
        tworzymy zbachowane dane i tasujemy epizody wewnątrz nich
        for batch in batches:
            na początek zerujemy gradient, wyciągamy [stany, akcje, q wartości] z batchu w tensorach
        
            wrzucamy stany do sieci, uzyskujemy prwadopodobienstwa akcji i wartości stanów
            
            z wczesniejszych q wartości i wartości stanów liczymy mse_loss
            
            log_softmax na prawdopodobienstwach akcji
            
            liczymy advantage przez roznice q wartosci i wartosci stanow
            
            liczym policy_loss, entropy_loss i robimy dwa backwardy, jeden na policy_loss drugi na entropy_loss i wczesniejsze mse_loss
            (entropy_loss liczymy żeby zbyt nie karać sieci jak nie jest pewna akcji i daje niskie prawdopodobieństwa)
            
            step na optimizerze i lecimy dalej
            
            model zapisujemy co X kroków albo w momencie jak mamy największy reward
    
    """

def extract_batch_data(filenames_batch):
        
    states = []
    actions = []
    rewards = []
    not_done_idx = []
    last_states = []
    for idx, exp in enumerate(batch):
        # unpack states, actions, and rewards into separate lists
        states.append(np.array(exp.state, copy=False))
        actions.append(int(exp.action))
        rewards.append(exp.reward)
        if exp.last_state is not None:
            # if the episode has not yet ended, save the index and state prime of the transition
            not_done_idx.append(idx)
            last_states.append(np.array(exp.last_state, copy=False))
    states_v = torch.FloatTensor(states).to(device)
    actions_t = torch.LongTensor(actions).to(device)

    # handle rewards
    rewards_np = np.array(rewards, dtype=np.float32)
    # if at least one transition was non-terminal
    if not_done_idx:
        last_states_v = torch.FloatTensor(last_states).to(device)
        # calculate the values of all the state primes from the net
        last_vals_v = net(last_states_v)[1]
        last_vals_np = last_vals_v.data.cpu().numpy()[:, 0]
        # apply the Bellman equation adding GAMMA * V(s') to the reward for all non-terminal states
        # terminal states will contain just the reward received
        rewards_np[not_done_idx] += last_val_gamma * last_vals_np

    # these are the Q(s,a) values we will use to calculate the advantage and value loss
    q_vals_v = torch.FloatTensor(rewards_np).to(device)
    return states_v, actions_t, q_vals_v

    states = []
    steering = []
    rewards = []
    non_terminal_idxs = []
    terminal_idxs = []
    for episode in filenames_batch:
        pd.read_csv(episode)
        #iterate over pd_df rows
        
       
    
def split_data_into_batches(mpc_data_dir='../data/experiments/'):
    #prepare list for data filenames
    episode_csvs = []
    #recursively explore the directory containing mpc data
    for filename in glob.iglob(mpc_data_dir+'**/*.csv', recursive=True):
        episode_csvs.append(filename)
    #shuffle the data before batching
    random.shuffle(episode_csvs)
    
    # this batching discards some data if len(episode_csvs)%BATCH_SIZE != 0
    # im proud of my single line batching with this list comprehension B)
    batched_data = [episode_csvs[i*BATCH_SIZE:(i+1)*BATCH_SIZE] for i in range(len(episode_csvs)//BATCH_SIZE)]
#     batched_data = []
#     for data_iterator in range(len(episode_csvs)):
#         batch = []
#         batch_size_controller = 0
#         while batch_size_controller < BATCH_SIZE:
#             batch.append(episode_csvs[data_iterator])
#             batch_size_controller+=1
#         batched_data.append(batch)
#     if len(batched_data[-1])<BATCH_SIZE:
#         batched_data = batched_data[:-1] #removing the last batch if the number of datapoints isn't divisible by BATCH_SIZE
        
    return batched_data


def run_episode(client:carla.Client, controller:Controller, spawn_points:np.array,
                writer:SummaryWriter, viz:vis.Visdom, args) -> (str, dict, dict, list):
    '''

    :param actor: vehicle
    :param controller: inherits abstract Controller class
    :param sensors:
    :param way_points:
    :return: status:str ->
             actor_dict -> speed, wheels turn, throttle, reward -> can be taken from actor?
             env_dict -> consecutive locations of actor, distances to closest spawn point, starting spawn point
             array[np.array] -> photos
    '''
    # Create agent object -> delegate everything below to init and configure
    # play_step method returns values from the loop
    NUM_STEPS = args.num_steps
    # states = []
    # actions = []
    # rewards = []

    environment = Environment(client=client)
    world = environment.reset_env(args)
    agent = Agent(world=world, controller=controller, vehicle=args.vehicle,
                  sensors=SENSORS, spawn_points=spawn_points)

    agent.initialize_vehicle()
    spectator = world.get_spectator()
    spectator.set_transform(numpy_to_transform(
        spawn_points[agent.spawn_point_idx-30]))

    # Spawn actor -> how synchronously
    agent_transform = None
    world.tick()
    world.tick()
    # Calculate norm of all cordinates
    while (agent_transform != agent.transform).any():
        agent_transform = agent.transform
        world.tick()

    #INITIALIZE SENSORS
    agent.initialize_sensors()

    # Initialize visdom windows

    # Release handbrake
    world.tick()
    time.sleep(1)# x4? allow controll each 4 frames

    windows = visdom_initialize_windows(viz=viz, title=DATE, sensors=SENSORS, location=agent.location) if args.visdom else None

    for step in range(NUM_STEPS):  #TODO change to while with conditions
        #Retrieve state and actions

        state = agent.get_state(step, retrieve_data=True)
        # states.append(state)

        #Check if state is terminal
        if state['distance_2finish'] < 30:
            status = 'Succes'
            print('lap finished')
            break

        #Apply action
        action = agent.play_step(state) #TODO split to two functions
        state_value = action['state_value']
        # actions.append(action)

        #Transit to next state
        world.tick()
        next_state = {
            'velocity': agent.velocity,
            'location': agent.location
        }

        #Receive reward
        reward = environment.calc_reward(points_3D=agent.waypoints, state=state, next_state=next_state,
                                         alpha=ALPHA, step=step)
        # rewards.append(rewards)
        # print(f'step:{step} data:{len(agent.sensors["depth"]["data"])}')
        #Log
        if args.tensorboard:
            tensorboard_log(title=DATE, writer=writer, state=state,
                            action=action, reward=reward, step=step)
        if args.visdom:
            visdom_log(viz=viz, windows=windows, state=state, action=action, reward=reward, step=step)

        if ((agent.velocity < 20) & (step % 10 == 0)) or (step % 50 == 0):
            set_spectator_above_actor(spectator, agent.transform)
        # time.sleep(0.1)

    agent.destroy(data=True)
    del environment

        # Visdom render from depth_data
        # Explore MPC configurations
        # unpack_batch(batch, net, last_val_gamma):
        # calculate for ex. distance and add to separate informative logging structure
        # Uruchomienie 4 instancji środowiska?

    if STORE_DATA:
        pass
    else:
        sensors_data = None

    status, actor_dict, env_dict, sensor_data = str, dict, dict, list

    return status, actor_dict, env_dict, sensor_data


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nCancelled by user. Bye!')