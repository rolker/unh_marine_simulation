#!/usr/bin/env python3

# Roland Arsenault
# Center for Coastal and Ocean Mapping
# University of New Hampshire
# Copyright 2017, All rights reserved.

import asv_sim.collision
import asv_sim.dynamics
import asv_sim.environment
import asv_sim.model
import asv_sim.platform
from asv_sim_msgs.msg import Collision
from rcl_interfaces.msg import ParameterDescriptor
import rclpy
import rclpy.node
from rclpy.qos import QoSProfile
from rclpy.qos import ReliabilityPolicy
from std_msgs.msg import Bool
from std_msgs.msg import Float64


class AsvSim(rclpy.node.Node):

    def __init__(self):
        super().__init__('asv_sim')

        self.models = {}

        self.platforms_param = self.declare_parameter(
            'platforms', ['default'],
            ParameterDescriptor(description='List of platforms to enable'))

        self.environment = asv_sim.environment.Environment(self)

        self.collisions = self._createCollisions()

        self.platforms = []
        for platform_name in self.platforms_param.value:
            self.platforms.append(
                asv_sim.platform.Platform(platform_name, self))

        self.reset_subscriber = self.create_subscription(
            Bool, '~/sim_reset', self.reset_callback, 1)

        self.tide_publisher = self.create_publisher(
            Float64, '~/environment/tide_level', 5)

        self.update_timer = self.create_timer(0.05, self.update)
        self.nav_time = self.create_timer(0.2, self.updateNav)

    def _createCollisions(self) -> asv_sim.collision.Collisions:
        """Read the ``collision.*`` parameters and build the resolver.

        An unreadable ``collision.grid_file`` raises: a simulation that
        silently ran without its terrain would be the worse failure.
        """
        boats = self.declare_parameter(
            'collision.boats', True,
            ParameterDescriptor(
                description='Boats block each other (no interpenetration, '
                'sliding allowed). False lets them pass through.')).value
        grid_file = self.declare_parameter(
            'collision.grid_file', '',
            ParameterDescriptor(
                description='Bathymetry GeoTIFF (band 1, positive depth, '
                'as read by mbes_sim.bathy_grid). Empty: no terrain '
                'collision. Read once at start.')).value
        enc_dir = self.declare_parameter(
            'collision.enc_dir', '',
            ParameterDescriptor(
                description='S-57 ENC cell (.000) or a directory of cells; '
                'charted piers, pontoons, piles, buoys, beacons, rocks and '
                'wrecks block boats. Empty: no charted objects. Read once '
                'at start; an unreadable path stops the node. Point it at '
                'the cells of the area only.')).value
        enc_footprints = self.declare_parameter(
            'collision.enc_footprints', [''],
            ParameterDescriptor(
                description='Overrides of the footprint of a charted class '
                'as CLASS=metres (radius of a point, half width of a line); '
                '0 leaves the class out. Example: BOYLAT=1.5, SLCONS=0.')).value
        objects = None
        if enc_dir:
            from asv_sim import charts
            primitives, project, counts = charts.load(
                enc_dir, [e for e in enc_footprints if e])
            objects = asv_sim.collision.ChartedObjectSource(
                primitives, project)
            self.get_logger().info(
                'charted objects on: {} primitives from {} ({})'.format(
                    len(primitives), enc_dir, ', '.join(
                        '{} {}'.format(k, v)
                        for k, v in sorted(counts.items())) or 'none'))
            if not primitives:
                self.get_logger().warning(
                    'collision.enc_dir {} gave no charted objects: wrong '
                    'cells, or every class set to 0 in collision.enc_footprints'
                    .format(enc_dir))
        else:
            self.get_logger().info(
                'charted objects off: collision.enc_dir is not set')
        grid = None
        if grid_file:
            from mbes_sim.bathy_grid import BathyGrid
            grid = BathyGrid(grid_file)
            self.get_logger().info(
                'terrain collision on: {}'.format(grid_file))
        else:
            self.get_logger().info(
                'terrain collision off: collision.grid_file is not set')
        self.collision_publisher = self.create_publisher(
            Collision, '~/collisions',
            QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE))
        return asv_sim.collision.Collisions(
            grid=grid, boats=boats, emit=self._publishCollision,
            logger=self.get_logger(), objects=objects)

    def _publishCollision(self, event: dict) -> None:
        msg = Collision()
        msg.header.stamp = event['stamp'].to_msg()
        msg.platform = event['platform']
        msg.kind = event['kind']
        msg.other = event['other']
        msg.latitude = event['latitude']
        msg.longitude = event['longitude']
        msg.closing_speed = float(event['closing_speed'])
        msg.water_depth = float(event['water_depth'])
        self.collision_publisher.publish(msg)

    def getModel(self, model_name: str) -> asv_sim.model.Model:
        if model_name not in self.models:
            self.models[model_name] = asv_sim.model.Model(model_name, self)
        return self.models[model_name]

    def reset_callback(self, data):
        for p in self.platforms:
            p.reset_callback(data)

    def update(self):
        for p in self.platforms:
            p.update()

    def updateNav(self):
        now = self.get_clock().now()
        tide = self.environment.getTide(now)
        self.tide_publisher.publish(Float64(data=tide))

        for p in self.platforms:
            p.updateNav()


def main(args=None):
    rclpy.init(args=args)
    sim = AsvSim()
    rclpy.spin(sim)
    rclpy.shutdown()


if __name__ == '__main__':
    main()
