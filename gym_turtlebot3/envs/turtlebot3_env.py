#! /usr/bin/env python3

import rospy
import gym
import numpy as np
import math
import time
import os
from cv_bridge import CvBridge
from geometry_msgs.msg import Twist, Point, Pose
from sensor_msgs.msg import CompressedImage
from sensor_msgs.msg import LaserScan
from nav_msgs.msg import Odometry
from std_srvs.srv import Empty
from gym import spaces
from gym.utils import seeding
from gym_turtlebot3.envs.mytf import euler_from_quaternion
from gym_turtlebot3.envs import Respawn

TURTLE = '003'


class TurtleBot3Env(gym.Env):
    def __init__(self, observation_mode=0, env_stage=1, max_env_size=None, continuous=False, observation_size=24,
                 action_size=5, min_range=0.1, max_range=2.5, min_ang_vel=-1.5, max_ang_vel=1.5, min_linear_vel=-0.5,
                 max_linear_vel=0.5, goalbox_distance=0.35, collision_distance=0.18, reward_goal=200.,
                 reward_collision=-20, angle_out=250, goal_list=None, test_real=False):

        self.bridge = CvBridge()
        self.goal_x = 0
        self.goal_y = 0
        self.heading = 0
        self.image = None
        self.initGoal = True
        self.get_goalbox = False
        self.position = Pose()
        self.env_stage = env_stage
        self.test_real = test_real

        if self.test_real:
            self.pub_cmd_vel = rospy.Publisher('cmd_vel', Twist, queue_size=1)
            self.sub_odom = rospy.Subscriber('odom', Odometry, self.getOdometry)
        else:
            self.pub_cmd_vel = rospy.Publisher('cmd_vel', Twist, queue_size=1)
            self.sub_odom = rospy.Subscriber('odom', Odometry, self.getOdometry)
        self.sub_image = rospy.Subscriber('/camera_2/image_raw/compressed', CompressedImage, self.getImage, queue_size=1)

        self.reset_proxy = rospy.ServiceProxy('gazebo/reset_simulation', Empty)
        self.unpause_proxy = rospy.ServiceProxy('gazebo/unpause_physics', Empty)
        self.pause_proxy = rospy.ServiceProxy('gazebo/pause_physics', Empty)
        self.respawn_goal = Respawn()

        if not goal_list:
            if self.env_stage == 1 or self.env_stage == 2:
                goal_list = np.asarray([np.random.uniform((-1.5, -1.5), (1.5, 1.5)) for _ in range(1)])
            else:
                goal_list = np.array([np.random.uniform((0, 0), (3, -3)) for _ in range(1)])
        else:
            goal_list = np.array(goal_list)
        self.respawn_goal.setGoalList(goal_list)

        self.observation_mode = observation_mode
        self.observation_size = observation_size
        self.min_range = min_range
        self.max_range = max_range
        self.min_ang_vel = min_ang_vel
        self.max_ang_vel = max_ang_vel
        self.min_linear_vel = min_linear_vel
        self.max_linear_vel = max_linear_vel
        self.goalbox_distance = goalbox_distance
        self.collision_distance = collision_distance
        self.reward_goal = reward_goal
        self.reward_collision = reward_collision
        self.angle_out = angle_out
        self.continuous = continuous
        self.max_env_size = max_env_size

        if self.continuous:
            low, high, shape_value = self.get_action_space_values()
            self.action_space = spaces.Box(low=low, high=high, shape=(shape_value,), dtype=float)
        else:
            self.action_space = spaces.Discrete(action_size)
            ang_step = max_ang_vel / ((action_size - 1) / 2)
            self.actions = [((action_size - 1) / 2 - action) * ang_step for action in range(action_size)]

        low, high = self.get_observation_space_values()
        self.observation_space = spaces.Box(low, high, dtype=float)

        self.num_timesteps = 0
        self.lidar_distances = None
        self.ang_vel = 0
        self.linear_vel = 0

        self.start_time = time.time()
        self.last_step_time = self.start_time

        self.seed()

    def seed(self, seed=None):
        self.np_random, seed = seeding.np_random(seed)
        return [seed]

    def get_action_space_values(self):
        low = np.array([self.min_ang_vel, self.min_linear_vel])
        high = np.array([self.max_ang_vel, self.max_linear_vel])
        shape_value = 2
        return low, high, shape_value

    def get_observation_space_values(self):
        low = np.append(np.full(self.observation_size, self.min_range), np.array([-math.pi, 0], dtype=np.float32))
        high = np.append(np.full(self.observation_size, self.max_range),
                         np.array([math.pi, self.max_env_size], dtype=np.float32))
        return low, high

    def _getGoalDistace(self):
        goal_distance = round(math.hypot(self.goal_x - self.position.x, self.goal_y - self.position.y), 2)
        return goal_distance

    def getOdometry(self, odom):
        self.position = odom.pose.pose.position
        orientation = odom.pose.pose.orientation
        orientation_list = [orientation.x, orientation.y, orientation.z, orientation.w]
        _, _, yaw = euler_from_quaternion(orientation_list)
        goal_angle = math.atan2(self.goal_y - self.position.y, self.goal_x - self.position.x)

        heading = goal_angle - yaw
        if heading > math.pi:
            heading -= 2 * math.pi

        elif heading < -math.pi:
            heading += 2 * math.pi

        self.heading = heading

    def get_time_info(self):
        time_info = time.strftime("%H:%M:%S", time.gmtime(time.time() - self.start_time))
        time_info += '-' + str(self.num_timesteps)
        return time_info

    def episode_finished(self):
        pass

    def get_env_state(self):
        return self.lidar_distances

    def getState(self, scan):
        scan_range = []
        heading = self.heading
        done = False

        for i in range(len(scan.ranges)):
            if scan.ranges[i] == float('Inf'):
                scan_range.append(self.max_range)
            elif np.isnan(scan.ranges[i]):
                scan_range.append(self.min_range)
            else:
                scan_range.append(scan.ranges[i])

        self.lidar_distances = scan_range

        if self.test_real:
            while self.image is None:
                time.sleep(0.1)
            return [self.get_env_state(), self.image]

        time_info = self.get_time_info()
        current_distance = self._getGoalDistace()
        if min(self.lidar_distances) < self.collision_distance:
            # print(f'{time_info}: Collision!!')
            done = True

        if current_distance < self.goalbox_distance:
            if not done:
                # print(f'{time_info}: Goal!!')
                self.get_goalbox = True
                if self.respawn_goal.last_index is (self.respawn_goal.len_goal_list - 1):
                    done = True
                    self.episode_finished()
        # current_distance = np.sqrt(32) / (current_distance + 1)
        return self.get_env_state() + [heading, current_distance], done

    def get_done_reward(self, lidar, distance):
        done = False
        self.lidar_distances = lidar
        if min(self.lidar_distances) < self.collision_distance:
            done = True

        if distance < self.goalbox_distance:
            if not done:
                self.get_goalbox = True
                if self.respawn_goal.last_index is (self.respawn_goal.len_goal_list - 1):
                    done = True

        reward = self.setReward(done)
        return reward, done

    def setReward(self, done):
        if self.get_goalbox:
            reward = self.reward_goal
            self.pub_cmd_vel.publish(Twist())
            self.goal_x, self.goal_y = self.respawn_goal.getPosition(True, delete=True)
            self.goal_distance = self._getGoalDistace()
            self.get_goalbox = False
        elif done:
            reward = self.reward_collision = - 20.
            self.pub_cmd_vel.publish(Twist())
            if self.respawn_goal.last_index != 0:
                self.respawn_goal.initIndex()
                self.goal_x, self.goal_y = self.respawn_goal.getPosition(True, delete=True)
                self.goal_distance = self._getGoalDistace()
        else:
            reward = 0
        return reward

    def set_ang_vel(self, action):
        if self.continuous:
            self.ang_vel = action
        else:
            self.ang_vel = self.actions[action]

    def set_linear_vel(self, action):
        if self.continuous:
            self.linear_vel = action
        else:
            self.linear_vel = self.actions[action]

    def step(self, action):
        self.set_ang_vel(np.clip(action[0], self.min_ang_vel, self.max_ang_vel))
        self.set_linear_vel(np.clip(action[1], self.min_linear_vel, self.max_linear_vel))

        vel_cmd = Twist()
        vel_cmd.linear.x = self.linear_vel
        vel_cmd.angular.z = self.ang_vel
        self.pub_cmd_vel.publish(vel_cmd)

        if self.test_real:
            return None, None, None, None

        data = None
        while data is None:
            try:
                if self.test_real:
                    data = None
                    # data = rospy.wait_for_message('/scan', LaserScan)
                else:
                    data = rospy.wait_for_message('/scan', LaserScan, timeout=15)
            except:
                pass

        self.num_timesteps += 1
        if self.test_real:
            # state = self.getState(data)
            return data, None, None, {}
        else:
            state, done = self.getState(data)
            reward = self.setReward(done)
            return np.asarray(state), reward, done, {}

    def get_position(self):
        return [self.position.x, self.position.y]

    def get_target_position(self):
        return [self.goal_x, self.goal_y]

    def get_scan(self):
        return self.lidar_distances

    def getImage(self, image):
        self.image = self.bridge.compressed_imgmsg_to_cv2(image)

    def reset(self, new_random_goals=True, goal=None):
        if not self.test_real:
            if new_random_goals:
                if self.env_stage == 1 or self.env_stage == 2:
                    self.respawn_goal.setGoalList(
                        np.asarray([np.random.uniform((-1.65, -1.65), (1.65, 1.65)) for _ in range(1)]))
                else:
                    val = np.random.uniform((0.25, -0.25), (3.75, -3.75))
                    # while 1.0 < val[0] < 2.5 and -1.0 > val[1] > -2.5:
                    #    val = np.random.uniform((0.25, -0.25), (3.75, -3.75))
                    self.respawn_goal.setGoalList(np.asarray([val]))
            else:
                self.respawn_goal.setGoalList(np.array(goal))

            rospy.wait_for_service('gazebo/reset_world')
            try:
                self.reset_proxy()
            except rospy.ServiceException:
                print("gazebo/reset_simulation service call failed")

            data = None
            while data is None:
                try:
                    data = rospy.wait_for_message('/scan', LaserScan, timeout=15)
                except:
                    pass

            if self.initGoal:
                self.goal_x, self.goal_y = self.respawn_goal.getPosition()
                self.initGoal = False
                time.sleep(1)
            else:
                self.goal_x, self.goal_y = self.respawn_goal.getPosition(True, delete=True)

            self.goal_distance = self.old_distance = self._getGoalDistace()
            state, _ = self.getState(data)
        else:
            data = None
            while data is None:
                try:
                    data = rospy.wait_for_message('/scan', LaserScan, timeout=10)
                except:
                    pass
            state = self.getState(data)

        return state

    def render(self, mode=True):
        pass

    def close(self):
        rospy.signal_shutdown("Gym closed.")
        os.system("kill $(ps aux | grep gzserver | grep -v grep | awk '{print $2}')")
