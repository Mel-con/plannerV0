# !/usr/bin/env python3
# building custom gym environment:
# # https://medium.com/analytics-vidhya/building-custom-gym-environments-for-reinforcement-learning-24fa7530cbb5

import gym
from gym import spaces
import numpy as np
import math
from math import pi as pi
from scipy.spatial.transform import Rotation as R
import sys, time
import rclpy
from rclpy.node import Node
from std_msgs.msg import String, Header
from diagnostic_msgs.msg import DiagnosticStatus, KeyValue
from actionlib_msgs.msg import GoalID, GoalStatus, GoalStatusArray
from sensor_msgs.msg import Imu
from geometry_msgs.msg import PointStamped, PolygonStamped, Twist, TwistStamped, PoseStamped, Point
from planner_msgs.msg import SDiagnosticStatus, SGlobalPose, SHealth, SImu, EnemyReport, OPath, SPath
from planner.sim_admin import check_state_simulation, act_on_simulation
from planner.sim_services import check_line_of_sight, get_all_possible_ways

STOP = 0
START = 1
PAUSE = 2


class PlannerEnv(gym.Env):
    MAX_STEPS = 200
    STEP_REWARD = 1 / MAX_STEPS
    FINAL_REWARD = 1.0

    class Enemy:
        def __init__(self, msg):
            self.cep = msg.cep
            self.gpoint = msg.gpose
            self.priority = msg.priority
            self.tclass = msg.tclass
            self.is_alive = msg.is_alive
            self.id = msg.id

        def update(self, n_enn):
            self.cep = n_enn.cep
            self.gpoint = n_enn.gpoint
            self.priority = n_enn.priority
            self.tclass = n_enn.tclass
            self.is_alive = n_enn.is_alive

    class Entity:
        def __init__(self, msg):
            self.id = msg.id
            self.diagstatus = msg.diagstatus
            self.gpoint = Point()
            self.imu = Imu()
            self.health = KeyValue()

        def update_desc(self, n_ent):
            self.diagstatus = n_ent.diagstatus

        def update_gpose(self, n_pose):
            self.gpoint = n_pose

        def update_imu(self, n_imu):
            self.imu = n_imu

        def update_health(self, n_health):
            self.health = n_health

    def get_entity(self, id):
        found = None
        for elem in self.entities:
            if elem.id == id:
                found = elem
                break
        return found

    def get_enemy(self, id):
        found = None
        for elem in self.enemies:
            if elem.id == id:
                found = elem
                break
        return found

    def global_pose_callback(self, msg):
        this_entity = self.get_entity(msg.id)
        if (this_entity == None):
            self.get_logger().info('This entity "%s" is not managed yet' % msg.id)
            return
        this_entity.update_gpose(msg.gpose.point)
        self.get_logger().debug('Received: "%s"' % msg)

    def entity_description_callback(self, msg):
        a = self.Entity(msg)
        res = False
        for elem in self.entities:
            if elem.id == a.id:
                elem.update_desc(a)
                res = True
                break
        if not res:
            self.entities.append(a)

        self.get_logger().debug('Received: "%s"' % msg)

    def enemy_description_callback(self, msg):
        a = self.Enemy(msg)
        res = False
        for elem in self.enemies:
            if elem.id == a.id:
                elem.update(a)
                res = True
                break
        if not res:
            self.enemies.append(a)
        self.get_logger().debug('Received: "%s"' % msg)

    def entity_imu_callback(self, msg):
        this_entity = self.get_entity(msg.id)
        if (this_entity == None):
            self.get_logger().info('This entity "%s" is not managed yet' % msg.id)
            return
        this_entity.update_imu(msg.imu)
        self.get_logger().debug('Received: "%s"' % msg)

    def entity_overall_health_callback(self, msg):
        this_entity = self.get_entity(msg.id)
        if (this_entity == None):
            self.get_logger().info('This entity "%s" is not managed yet' % msg.id)
            return
        this_entity.update_health(msg.values)
        self.get_logger().debug('Received: "%s"' % msg)

    def move_entity_to_goal(self, entity, goal):
        self.get_logger().info('Move entity:' + entity.id + " to position:" + goal.__str__())
        msg = SGlobalPose()
        msg.gpose = goal
        msg.id = entity.id
        self.moveToPub.publish(msg)

    def look_at_goal(self, entity, goal):
        self.get_logger().info('Entity:' + entity.id + " should look at:" + goal.__str__())
        msg = SGlobalPose()
        msg.gpose = goal
        msg.id = entity.id
        self.lookPub.publish(msg)

    def take_path(self, entity, path):
        self.get_logger().info('Entity:' + entity.id + " should take the path:" + path.name)
        msg = SPath()
        msg.path = path
        msg.id = entity.id
        self.takePathPub.publish(msg)

    def attack_goal(self, entity, goal):
        self.get_logger().info('Entity:' + entity.id + " should attack at:" + goal.__str__())
        msg = SGlobalPose()
        msg.gpose = goal
        msg.id = entity.id
        self.attackPub.publish(msg)

    def __init__(self):
        super(PlannerEnv, self).__init__()

        print('Planner environment created!')
        self.hist_size = 3
        self.simOn = False

        # For time step
        self.current_time = time.time()
        self.last_time = self.current_time
        self.time_step = []
        self.last_obs = np.array([])
        self.TIME_STEP = 0.05  # 10 mili-seconds
        self.steps = 0
        self.total_reward = 0
        self.boarders = []
        # Define action and observation space
        # They must be gym.spaces objects
        # Example when using discrete actions:
        self.action_space = spaces.Box(low=np.array([-1] * 4), high=np.array([1] * 4), dtype=np.float16)
        # spaces.Discrete(N_DISCRETE_ACTIONS)
        # Example for using image as input:
        self.observation_space = spaces.Box(low=0, high=512,
                                            shape=(43657,), dtype=np.uint8)
        # Observation: for now two lists: one of entities and one of enemies
        self._obs = []
        # As a first step, actions can be only of 3 types: move, look, attack
        # For each type of action, there should be a list of pairs of {entity, goal}
        self._actions = {'MOVE_TO': [{}], 'LOOK_AT': [{}], 'ATTACK': [{}]}

        # ROS2 Support
        rclpy.init()
        self.entities = []
        self.enemies = []
        self.act_req = 0
        self.stat_req = 0
        self.ch_los_req = 0
        self.node = rclpy.create_node("planner")

        # Subscribe to topics
        self.entityPoseSub = self.node.create_subscription(SGlobalPose, '/entity/global_pose',
                                                           self.global_pose_callback, 10)

        self.entityDescriptionSub = self.node.create_subscription(SDiagnosticStatus, '/entity/description',
                                                                  self.entity_description_callback, 10)
        self.enemyDescriptionSub = self.node.create_subscription(EnemyReport, '/enemy/description',
                                                                 self.enemy_description_callback, 10)
        self.entityImuSub = self.node.create_subscription(SImu, '/entity/imu', self.entity_imu_callback, 10)
        self.entityOverallHealthSub = self.node.create_subscription(SHealth, '/entity/overall_health',
                                                                    self.entity_overall_health_callback, 10)
        # Publish topics
        self.moveToPub = self.node.create_publisher(SGlobalPose, '/entity/move_to/goal', 10)
        self.attackPub = self.node.create_publisher(SGlobalPose, '/entity/attack/goal', 10)
        self.lookPub = self.node.create_publisher(SGlobalPose, '/entity/look/goal', 10)
        self.takePathPub = self.create_publisher(SPath, '/entity/takepath', 10)

        timer_period = 10  # seconds
        #        self.timer = self.node.create_timer(timer_period, self.timer_callback)
        self.num_of_dead_enemies = 0

    def get_obs(self):
        obs = self.update_state()
        return obs

    def update_state(self):
        entities = self.entities
        enemies = self.enemies
        # Line of sight?
        # Different path
        obs = {'entities': entities, 'enemies': enemies}
        # obs = {'h_map': h_map}
        return obs

    def init_env(self):
        if self.simOn:
            ret = check_state_simulation()
            if ret != START or ret != PAUSE:
                print("Inconsistent state of the simulation = " + str(ret))
            nret = act_on_simulation(ascii(STOP))
            if nret != STOP:
                print("Couldn't stop the simulation")
            else:
                self.simOn = False

        # Restart simulation
        ret = act_on_simulation(ascii(START))
        if ret != START:
            print("Couldn't start the simulation")

        self.simOn = True

    def reset(self):
        # what happens when episode is done

        # clear all
        self.steps = 0
        self.total_reward = 0
        self.boarders = []
        self._obs = []

        # initial state depends on environment (mission)
        self.init_env()

        # wait for simulation to set up
        while True:  # wait for all topics to arrive
            if bool(self.entities) and bool(self.ennemies):  # and len(self.stones) == self.numStones + 1:
                break

        # wait for simulation to stabilize, stones stop moving
        time.sleep(5)

        self._obs = self.update_state()
        return self._obs

    def time_stuff(self):
        self.current_time = time.time()
        time_step = self.current_time - self.last_time
        if time_step < self.TIME_STEP:
            time.sleep(self.TIME_STEP - time_step)
            self.current_time = time.time()
            time_step = self.current_time - self.last_time
        self.time_step.append(time_step)
        self.last_time = self.current_time

    def reward_func(self):
        previous = self.num_of_dead_enemies
        num_of_dead_enemies=0
        for enemy in self.enemies:
            if not enemy.is_alive:
                num_of_dead_enemies = num_of_dead_enemies + 1
        self.num_of_dead_enemies=num_of_dead_enemies

        if num_of_dead_enemies > previous:
            bonus = 0.1

        malus = (- bonus) * self.steps / (self.MAX_STEPS )

        # print(malus)

        return malus

    def step(self, action):
        # send action to simulation
        self.do_action(action)

        self.time_stuff()
        # get observation from simulation
        self._obs = self.update_state()

        # calc step reward and add to total
        r_t = self.reward_func()

        # check if done
        done, final_reward, reset = self.end_of_episode()

        step_reward = r_t + final_reward
        self.total_reward = self.total_reward + step_reward

        self.done = done
        if done:
            self.enemies = {}
            self.entities = {}
            print('Done ')

        info = {"state": self.obs, "action": action, "reward": self.total_reward, "step": self.steps,
                "reset reason": reset}

        return self._obs, step_reward, done, info

    def end_of_episode(self):
        done = False
        reset = 'No'
        final_reward = 0
        current_pos = self._obs
        # self._obs = {'Entities':self.entities, 'Enemies':self.ennemies
        #
        # threshold = 7.5
        threshold = 0.5
        num_of_enemies = self.enemies.count()
        num_of_dead_enemies = 0
        for enemy in self.enemies:
            if not enemy.is_alive:
                num_of_dead_enemies = num_of_dead_enemies + 1

        if num_of_dead_enemies/num_of_enemies > threshold:
            done = True
            reset = 'goal achieved'
            print('----------------', reset, '----------------')
            nret = act_on_simulation(ascii(STOP))
            if nret != STOP:
                print("Couldn't stop the simulation")
            else:
                self.simOn = False
            final_reward = PlannerEnv.FINAL_REWARD

        self.steps += 1

        return done, final_reward, reset

    #
    # ex1 = {'Entity:Suicide': (0.0, 0.0, 0.0)}
    # ex2 = {'Entity:Drone': (0.1, 0.1, 0.1)}
    # _actions['MOVE_TO'].append(ex1)
    # _actions['MOVE_TO'].append(ex2)
    #    self._actions = {'MOVE_TO': [{}], 'LOOK_AT': [{}], 'ATTACK': [{}], 'TAKE_PATH':[{}]}

    def do_action(self, agent_action):
        for act in self._actions['MOVE_TO']:
            if len(act) > 1:
                for elm in act:
                    entity = elm
                    goal = act[elm]
                    self.move_entity_to_goal(entity, goal)
        for act in self._actions['LOOK_AT']:
            if len(act) > 1:
                for elm in act:
                    entity = elm
                    goal = act[elm]
                    self.look_at_goal(entity, goal)
        for act in self._actions['ATTACK']:
            if len(act) > 1:
                for elm in act:
                    entity = elm
                    goal = act[elm]
                    self.attack_goal(entity, goal)
        for act in self._actions['TAKE_PATH']:
            if len(act) > 1:
                for elm in act:
                    entity = elm
                    path = act[elm]
                    self.take_path(entity, path)
