"""Celestial body properties — gravity, escape velocity, sphere of influence."""

import math


class CelestialBody:
    """A spherical body with known mass and radius."""

    def __init__(self, name, mass, radius):
        self.name = name
        self.mass = mass        # [kg]
        self.radius = radius    # [m]

    def gravity(self):
        """Surface gravitational acceleration: g = G*M/R^2."""
        G = 6.674e-11
        return G * self.mass / self.radius**2

    def escape_velocity(self):
        """Escape velocity from the surface: v_esc = sqrt(2*g*R)."""
        g = self.gravity()
        return math.sqrt(2 * g * self.radius)

    def hill_radius(self, parent_mass, distance):
        """Hill sphere radius: r_H = d * (m / 3M)^(1/3).

        Approximates the region where this body's gravity dominates
        over the parent body's tidal forces.
        """
        return distance * (self.mass / (3 * parent_mass)) ** (1 / 3)
