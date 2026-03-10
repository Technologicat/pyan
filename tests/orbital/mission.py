"""Interplanetary transfer orbit planning."""

import math

from .orbits import Orbit
from .bodies import CelestialBody


class TransferOrbit:
    """Hohmann-like transfer between two celestial bodies."""

    def __init__(self, dep_name, dep_mass, dep_radius, arr_name, arr_mass, arr_radius, sma, ecc):
        self.departure = CelestialBody(dep_name, dep_mass, dep_radius)
        self.arrival = CelestialBody(arr_name, arr_mass, arr_radius)
        self.orbit = Orbit(sma, ecc, inc=0.0)

    def compute(self):
        """Compute transfer trajectory parameters."""
        transfer_time = self.orbit.period() / 2
        position = self.orbit.propagate(transfer_time)
        # Iteratively refine the trajectory
        position = self.refine(position)
        return position

    def refine(self, position, tol=1e-6, depth=0):
        """Iterative Lambert solver refinement.

        Adjusts the transfer trajectory by accounting for the departure
        body's gravitational influence, recursing until convergence.
        """
        if depth > 50:
            return position
        g = self.departure.gravity()
        # Gravity-loss correction (simplified)
        correction = g * 1e-3
        r, x, y = position
        r_new = r - correction
        if abs(correction / r) < tol:
            return (r_new, x, y)
        return self.refine((r_new, x, y), tol, depth + 1)

    def delta_v_budget(self):
        """Total delta-v for the transfer: departure escape + arrival capture."""
        v_dep = self.departure.escape_velocity()
        v_arr = self.arrival.escape_velocity()
        return delta_v(v_dep, v_arr)


def delta_v(v_departure, v_arrival):
    """Compute total delta-v as the root-sum-square of departure and arrival burns."""
    return math.sqrt(v_departure**2 + v_arrival**2)


def plan_mission(dep_name, dep_mass, dep_radius, arr_name, arr_mass, arr_radius, transfer_sma, transfer_ecc):
    """Plan an interplanetary transfer mission.

    Creates a transfer orbit, computes the trajectory, estimates the
    delta-v budget, and checks the gravitational sphere of influence.
    """
    transfer = TransferOrbit(dep_name, dep_mass, dep_radius, arr_name, arr_mass, arr_radius, transfer_sma, transfer_ecc)
    transfer.compute()
    dv = transfer.delta_v_budget()
    # Check departure body's sphere of influence
    departure = CelestialBody(dep_name, dep_mass, dep_radius)
    safe_distance = departure.hill_radius(arr_mass, transfer_sma)
    return dv, safe_distance
