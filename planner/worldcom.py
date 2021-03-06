#!/usr/bin/env python3
import sys
import rclpy
from rclpy.node import Node
from rclpy.callback_groups import ReentrantCallbackGroup

from std_msgs.msg import String, Header
from diagnostic_msgs.msg import DiagnosticStatus, KeyValue
from actionlib_msgs.msg import GoalID, GoalStatus, GoalStatusArray
from sensor_msgs.msg import Imu
from geometry_msgs.msg import PointStamped, PolygonStamped, Twist, TwistStamped, PoseStamped, Point
from planner_msgs.msg import SDiagnosticStatus, SGlobalPose, SHealth, SImu, EnemyReport, OPath, SPath
from planner_msgs.srv import ActGeneralAdmin, StateGeneralAdmin, CheckLOS, AllPathEntityToTarget
import planner_msgs

class WorldCom(Node):

    class Enemy:
        def __init__(self, msg):
            self.cep = msg.cep
            self.gpoint = msg.gpose
            self.priority=msg.priority
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
            self.gpoint= Point()
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


    def __init__(self, args=None):
        rclpy.init(args=args)
        super().__init__('world_communication')
        self.world_state = {}
        self.entities = []
        self.enemies = []
        self.act_req = 0
        self.stat_req = 0
        self.ch_los_req = 0
        self.get_ways_req = 0
        self.entityPoseSub = self.create_subscription(SGlobalPose, '/entity/global_pose', self.global_pose_callback, 10)

        self.entityDescriptionSub = self.create_subscription(SDiagnosticStatus, '/entity/description', self.entity_description_callback, 10)
        self.enemyDescriptionSub = self.create_subscription(EnemyReport, '/enemy/description', self.enemy_description_callback, 10)
        self.entityImuSub = self.create_subscription(SImu, '/entity/imu', self.entity_imu_callback, 10)
        self.entityOverallHealthSub = self.create_subscription(SHealth, '/entity/overall_health', self.entity_overall_health_callback, 10)

        self.moveToPub = self.create_publisher(SGlobalPose, '/entity/moveto/goal', 10)
        self.attackPub = self.create_publisher(SGlobalPose, '/entity/attack/goal', 10)
        self.lookPub = self.create_publisher(SGlobalPose, '/entity/look/goal', 10)
        self.takePathPub = self.create_publisher(SPath, '/entity/takepath', 10)

        self.genAdminCli = self.create_client(ActGeneralAdmin, 'act_general_admin')
        self.stateAdminCli = self.create_client(StateGeneralAdmin, 'state_general_admin')
        self.lineOfSightCli = self.create_client(CheckLOS, 'check_line_of_sight')
        self.getAllPossibleWaysCli = self.create_client(AllPathEntityToTarget, 'get_all_possible_ways')

        timer_period = 10  # seconds
        self.timer = self.create_timer(timer_period, self.timer_callback)
        self.client_futures = []
        self.i = 2
        self.future = None
        self.our_spin()

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

    def act_gen_admin_request(self, command):
        if (command > 2) or (command < 0):
            self.get_logger().warn('wrong command:'+ascii(command))
            return
        self.act_req = ActGeneralAdmin.Request()
        while not self.genAdminCli.wait_for_service(timeout_sec=1.0):
            self.get_logger().info('service ActGeneralAdmin not available, waiting ...')
        self.act_req.admin = bytes([command])
        self.client_futures.append(self.genAdminCli.call_async(self.act_req))

    def state_gen_admin_request(self):
        self.stat_req = StateGeneralAdmin.Request()
        while not self.stateAdminCli.wait_for_service(timeout_sec=1.0):
            self.get_logger().info('service StateGeneralAdmin not available, waiting ...')

        self.client_futures.append(self.stateAdminCli.call_async(self.stat_req))


    def check_line_of_sight_request(self, entity, enemy):
        self.ch_los_req = CheckLOS.Request()
        while not self.lineOfSightCli.wait_for_service(timeout_sec=1.0):
            self.get_logger().info('service CheckLOS not available, waiting ...')
        self.ch_los_req.one = entity.gpoint
        self.ch_los_req.two = enemy.gpoint
        self.client_futures.append(self.lineOfSightCli.call_async(self.ch_los_req))

    def get_all_possible_ways_request(self, entity, target):
        self.get_ways_req = AllPathEntityToTarget.Request()
        while not self.getAllPossibleWaysCli.wait_for_service(timeout_sec=1.0):
            self.get_logger().info('service ALLPathEntityToTarget not available, waiting ...')
        self.get_ways_req.entityid = entity.id
        self.get_ways_req.target = target
        self.client_futures.append(self.getAllPossibleWaysCli.call_async(self.get_ways_req))

    def timer_callback(self):
        self.get_logger().info('Timer callback: "%d"' % self.i)
        self.act_gen_admin_request(self.i)
        if self.i==3:
            self.i=0
        else:
            self.i += 1
        self.state_gen_admin_request()
        goal=PointStamped()
        goal.header = Header()
        goal.point = Point()
        goal.point.x = 0.1
        goal.point.y = 0.1
        goal.point.z = 0.1
        entt = self.get_entity("Suicide")
        if (entt == None):
            print("No entity found")
            return
        else:
            self.move_entity_to_goal(entt, goal)
        enn = self.get_enemy("Sniper")
        if (enn == None):
            print("No ennemy found")
            return
        else:
            self.check_line_of_sight_request(entt, enn)
        self.get_all_possible_ways_request(entt,goal.point)

    def global_pose_callback(self, msg):
        this_entity = self.get_entity(msg.id)
        if (this_entity==None):
            self.get_logger().info('This entity "%s" is not managed yet' % msg.id)
            return
        this_entity.update_gpose(msg.gpose.point)
        self.world_state['GlobalPose'] = msg.gpose.point
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
        res=False
        for elem in self.enemies:
            if elem.id == a.id:
                elem.update(a)
                res=True
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
        self.world_state['IMU'] = msg.imu
        self.get_logger().debug('Received: "%s"' % msg)


    def entity_overall_health_callback(self, msg):
        this_entity = self.get_entity(msg.id)
        if (this_entity == None):
            self.get_logger().info('This entity "%s" is not managed yet' % msg.id)
            return
        this_entity.update_health(msg.values)
        self.world_state['Health'] = msg.values
        self.get_logger().debug('Received: "%s"' % msg)

    def move_entity_to_goal(self, entity, goal):
        self.get_logger().info('Move entity:'+entity.id+" to position:"+ goal.__str__())
        msg = SGlobalPose()
        msg.gpose = goal
        msg.id = entity.id
        self.moveToPub.publish(msg)

    def look_at_goal(self, entity, goal):
        self.get_logger().info('Entity:'+entity.id+" should look at:"+ goal.__str__())
        msg = SGlobalPose()
        msg.gpose = goal
        msg.id = entity.id
        self.lookPub.publish(msg)

    def take_path(self, entity, path):
        self.get_logger().info('Entity:'+entity.id+" should take the path:"+ path.name)
        msg = SPath()
        msg.path = path
        msg.id = entity.id
        self.takePathPub.publish(msg)

    def attack_goal(self, entity, goal):
        self.get_logger().info('Entity:'+entity.id+" should attack at:"+ goal.__str__())
        msg = SGlobalPose()
        msg.gpose = goal
        msg.id = entity.id
        self.attackPub.publish(msg)

    def our_spin(self):
        while rclpy.ok():
            rclpy.spin_once(self)
            incomplete_futures = []
            for f in self.client_futures:
                if f.done():
                    res = f.result()

                    if type(res).__name__=='ActGeneralAdmin_Response':
                        print("ActGeneralAdmin_Response: "+res.resulting_status.__str__())
                        res_int = int.from_bytes(res.resulting_status, "big")
                    if type(res).__name__=='StateGeneralAdmin_Response':
                        print("StateGeneralAdmin_Response: " + res.resulting_status.__str__())
                        res_int = int.from_bytes(res.resulting_status, "big")
                    if type(res).__name__=='CheckLOS_Response':
                        print("CheckLOS_Response: " + res.is_los.__str__())
                    if type(res).__name__=='AllPathEntityToTarget_Response':
                        print("AllPathEntityToTarget_Response: " + res.path.__str__())
                else:
                    incomplete_futures.append(f)
            self.client_futures = incomplete_futures

def main(args=None):
    #rclpy.init(args=args)

    world_communication = WorldCom()

    ## while rclpy.ok():
    #     rclpy.spin_once(world_communication)
    #     if world_communication.future.done():
    #         try:
    #             response = world_communication.future.result()
    #         except Exception as e:
    #             world_communication.get_logger().info('Service call failed %r' % (e,))
    #         else:
    ##             world_communication.get_logger().info('Result of ActGeneralAdmin: %d' % (int.from_bytes(response.resulting_status, "big")))

    #world_communication.our_spin()
    ##rclpy.spin(world_communication)
    ## Destroy the node explicitly
    ## (optional - otherwise it will be done automatically
    ## when the garbage collector destroys the node object)
    world_communication.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()