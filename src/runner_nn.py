import argparse
import time

import numpy as np
import pandas as pd
import carla

#Local imports
import visdom as vis

from environment import Agent, Environment
from spawn import df_to_spawn_points, numpy_to_transform, set_spectator_above_actor, configure_simulation
from control.mpc_control import MPCController
from control.abstract_control import Controller
from tensorboardX import SummaryWriter

#Configs
#TODO Add dynamically generated foldername based on config settings and date.
from config import DATA_PATH, FRAMERATE, TENSORBOARD_DATA, GAMMA, \
    DATE_TIME, SENSORS, VEHICLES, CARLA_IP, MAP, NEGATIVE_REWARD

from utils import tensorboard_log, visdom_log, init_reporting, save_info, update_Qvals


def main():
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
        default=MAP,
        help='Avialable maps: "circut_spa", "RaceTrack", "Racetrack2". Default: "circut_spa"')

    argparser.add_argument(
        '--vehicle',
        metavar='V',
        default=0,
        type=int,
        dest='vehicle',
        help='Carla Vehicle blueprint, choose with integer. Avialable: ["vehicle.dodge_charger.police", "vehicle.mustang.mustang", "vehicle.tesla.model3", "vehicle.audi.etron"] Default: "vehicle.dodge_charger.police"')

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
        help='Avialable controllers: "MPC", "NN", Default: "MPC"')

    argparser.add_argument(
        '--speed',
        default=90,
        type=int,
        dest='speed',
        help='Target speed for mpc')

    argparser.add_argument(
        '--steps_ahead',
        default=10,
        type=int,
        dest='steps_ahead',
        help='steps 2calculate ahead for mpc')

    # Logging configs
    argparser.add_argument(
        '--tensorboard',
        metavar='TB',
        default=True,
        help='Decides if to log information to tensorboard (default: False)')

    args = argparser.parse_known_args()
    if len(args) > 1:
        args = args[0]

    run_client(args)


def run_client(args):

    args.host = 'localhost'
    args.port = 2000

    args.tensorboard = False
    writer = None
    if args.controller == 'MPC':
        TARGET_SPEED = args.speed
        STEPS_AHEAD = args.steps_ahead
        if args.tensorboard:
            writer = SummaryWriter(f'{TENSORBOARD_DATA}/{args.controller}/{args.map}_TS{TARGET_SPEED}_H{STEPS_AHEAD}_FRAMES{args.frames}_{DATE_TIME}',
                                   flush_secs=5, max_queue=5)
    elif args.tensorboard:
        writer = SummaryWriter(f'{TENSORBOARD_DATA}/{args.controller}/{args.map}_FRAMES{args.frames}', flush_secs=5)

    # Connecting to client -> later package it in function which checks if the world is already loaded and if the settings are the same.
    # In order to host more scripts concurrently
    client = configure_simulation(args)

    # load spawnpoints from csv -> generate spawn points from notebooks/20200414_setting_points.ipynb
    spawn_points_df = pd.read_csv(f'{DATA_PATH}/spawn_points/{args.map}.csv')
    spawn_points = df_to_spawn_points(spawn_points_df, n=10000, inverse=False) #We keep it here in order to have one way simulation within one script

    # Controller initialization
    if args.controller is 'NN':
        controller = NNController()

    status, actor_dict, env_dict, sensor_data = run_episode(client=client,
                                                            controller=controller,
                                                            spawn_points=spawn_points,
                                                            writer=writer,
                                                            args=args)



def run_episode(client:carla.Client, controller:Controller, spawn_points:np.array,
                writer:SummaryWriter, args) -> (str, dict, dict, list):
    '''
    Runs single episode. Configures world and agent, spawns it on map and controlls it from start point to termination
    state.

    :param client: carla.Client, client object connected to the Carla Server
    :param actor: carla.Vehicle
    :param controller: inherits abstract Controller class
    :param spawn_points: orginal or inverted list of spawnpoints
    :param writer: SummaryWriter, logger for tensorboard
    :param viz: visdom.Vis, other logger #refactor to one dictionary
    :param args: argparse.args, config #refactor to dict
    :return: status:str, succes
             actor_dict -> speed, wheels turn, throttle, reward -> can be taken from actor?
             env_dict -> consecutive locations of actor, distances to closest spawn point, starting spawn point
             array[np.array] -> photos
    '''
    NUM_STEPS = args.num_steps

    environment = Environment(client=client)
    world = environment.reset_env(args)
    agent_config = {'world':world, 'controller':controller, 'vehicle':VEHICLES[args.vehicle],
                    'sensors':SENSORS, 'spawn_points':spawn_points}
    agent = Agent(**agent_config)
    agent.initialize_vehicle()
    spectator = world.get_spectator()
    spectator.set_transform(numpy_to_transform(
        spawn_points[agent.spawn_point_idx-30]))

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
    time.sleep(1)
    init_reporting(path=agent.save_path, sensors=SENSORS)

    for step in range(NUM_STEPS):  #TODO change to while with conditions
        #Retrieve state and actions

        state = agent.get_state(step, retrieve_data=True)

        #Check if state is terminal


        #Apply action
        action = agent.play_step(state) #TODO split to two functions
        # actions.append(action)

        #Transit to next state
        world.tick()
        next_state = {
            'velocity': agent.velocity,
            'location': agent.location
        }

        #Receive reward
        reward = environment.calc_reward(points_3D=agent.waypoints, state=state, next_state=next_state,
                                         gamma=GAMMA, step=step)

        if state['distance_2finish'] < 5:
            print(f'agent {str(agent)} finished the race in {step} steps')
            save_info(path=agent.save_path, state=state, action=action, reward=0)
            update_Qvals(agent.save_path)
            break

        if state['collisions'] > 0:
            print(f'failed, collision {str(agent)}')
            save_info(path=agent.save_path, state=state, action=action,
                      reward=NEGATIVE_REWARD * (GAMMA ** step))
            agent.destroy()
            break

        save_info(path=agent.save_path, state=state, action=action, reward=reward)

        # print(f'step:{step} data:{len(agent.sensors["depth"]["data"])}')
        #Log
        if ((agent.velocity < 20) & (step % 10 == 0)) or (step % 50 == 0):
            set_spectator_above_actor(spectator, agent.transform)
        # time.sleep(0.1)

    #Calc Qvalues and add to reporting file
    update_Qvals(path=agent.save_path)

    world.tick()

    status, actor_dict, env_dict, sensor_data = str, dict, dict, list

    return status, actor_dict, env_dict, sensor_data


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nCancelled by user. Bye!')