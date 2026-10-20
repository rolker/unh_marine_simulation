from asv_sim import model
import pytest
import rclpy
import rclpy.node
import synthetic_grid

# Skip launch_testing files when run via plain pytest (colcon test).
# These require the launch_test runner instead.
collect_ignore = ['test_tide_integration.py']


@pytest.fixture
def mdl():
    rclpy.init()
    node = rclpy.node.Node('collision_test')
    try:
        yield model.Model('demo', node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


@pytest.fixture(scope='module')
def origin_and_grid(tmp_path_factory):
    path = str(tmp_path_factory.mktemp('grid') / 'truth.tif')
    lat, lon = synthetic_grid.write_grid(path)
    return lat, lon, path


@pytest.fixture
def world(origin_and_grid):
    from mbes_sim.bathy_grid import BathyGrid
    lat, lon, path = origin_and_grid
    return lat, lon, BathyGrid(path)
