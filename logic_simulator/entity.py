from logic_simulator.pos import Pos
import numpy as np
import copy


class Entity:
    STEP_TIME = 0.2

    def __init__(self, id, pos: Pos):
        self._id = id
        self._pos = pos
        self._startpos = copy.copy(pos)
        self._velocity_dir = np.array([0.0, 0.0, 0.0], dtype=float)
        self._speed = 0.0
        self._t = 0.0
        self._target_pos = copy.copy(pos)
        self._looking_at = copy.copy(pos)
        self._health = 1.0

    def reset(self):
        self._pos = copy.copy(self._startpos)
        self._velocity_dir = np.array([0.0, 0.0, 0.0], dtype=float)
        self._speed = 0.0
        self._t = 0.0
        self._target_pos = copy.copy(self._pos)
        self._looking_at = copy.copy(self._pos)
        self._health = 1.0

    def predict(self, t):
        raise NotImplementedError

    def clone(self):
        raise NotImplementedError

    # def step(self, *args):
    #     raise NotImplementedError

    def update(self):
        raise NotImplementedError

    def _is_same_args(self, *args):
        raise NotImplementedError

    def is_line_of_sight_to(self, pos):
        range_to_target = self.pos.distance_to(pos)

        is_los = range_to_target < self._max_range_of_view

        if is_los:
            range_to_look_at = self.pos.distance_to(self.looking_at)
            direction_to_target = self.pos.direction_vector(pos)
            direction_to_look_at = self.pos.direction_vector(self.looking_at)

            # cos alpha = A dot B / (norm A * norm B)
            cos_angle = np.dot(direction_to_target, direction_to_look_at) / (range_to_target * range_to_look_at)

            # first quarter  - cos function decreasing
            is_los = cos_angle > np.cos(self._fov)

        return is_los



    @property
    def id(self):
        return self._id

    @property
    def state(self):
        return np.array([[self.pos.x, self.pos.y, self.pos.z], self.velocity,
                         [self.looking_at.x, self.looking_at.y, self.looking_at.z], self.health])

    @property
    def pos(self) -> Pos:
        return self._pos

    @property
    def velocity(self):
        return self._speed * self._velocity_dir

    @property
    def health(self):
        return self._health

    @health.setter
    def health(self, h):
        self._health = h

    @property
    def looking_at(self) -> Pos:
        return self._looking_at

    def __str__(self):
        return "Pos: ({X}, {Y}, {Z}) Velocity: ({Vx}, {Vy}, {Vz})".format(X=self.pos.X, Y=self.pos.Y, Z=self.pos.Z,
                                                                          Vx=self.velocity[0], Vy=self.velocity[1],
                                                                          Vz=self.velocity[2])
