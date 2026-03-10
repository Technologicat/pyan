"""Kepler orbit mechanics — propagation and anomaly solving."""

import math


class Orbit:
    """Two-body Keplerian orbit defined by classical orbital elements."""

    def __init__(self, sma, ecc, inc, mu=1.0):
        self.sma = sma        # semi-major axis [m]
        self.ecc = ecc        # eccentricity [-]
        self.inc = inc        # inclination [rad]
        self.mu = mu          # gravitational parameter [m^3/s^2]

    def period(self):
        """Orbital period from Kepler's third law: T = 2*pi*sqrt(a^3/mu)."""
        return 2.0 * math.pi * math.sqrt(self.sma**3 / self.mu)

    def position(self, true_anomaly):
        """Position on the ellipse at a given true anomaly.

        Returns (r, x, y) in the orbital plane.
        """
        r = self.sma * (1 - self.ecc**2) / (1 + self.ecc * math.cos(true_anomaly))
        x = r * math.cos(true_anomaly)
        y = r * math.sin(true_anomaly)
        return r, x, y

    def propagate(self, dt):
        """Advance the orbit by dt seconds using the mean anomaly.

        Solves Kepler's equation M = E - e*sin(E) to find the true anomaly
        at the new epoch.
        """
        T = self.period()
        # Mean motion and mean anomaly advance
        n = 2.0 * math.pi / T
        M = n * dt
        # Solve Kepler's equation for eccentric anomaly
        E = converge_anomaly(M, self.ecc)
        # Eccentric anomaly -> true anomaly
        nu = 2.0 * math.atan2(
            math.sqrt(1 + self.ecc) * math.sin(E / 2),
            math.sqrt(1 - self.ecc) * math.cos(E / 2),
        )
        return self.position(nu)


def converge_anomaly(M, ecc, tol=1e-12):
    """Solve Kepler's equation: find E such that M = E - e*sin(E).

    Starts from the initial guess E = M, then delegates to refine_anomaly
    for Newton-Raphson iteration.
    """
    E0 = M  # initial guess
    return refine_anomaly(E0, M, ecc, tol)


def refine_anomaly(E, M, ecc, tol):
    """One Newton-Raphson step for Kepler's equation.

    If the residual is within tolerance, return E.
    Otherwise, apply the correction and check convergence again.
    """
    residual = E - ecc * math.sin(E) - M
    if abs(residual) < tol:
        return E
    # Newton-Raphson correction: dE = residual / (1 - e*cos(E))
    E_new = E - residual / (1 - ecc * math.cos(E))
    return converge_anomaly(M, ecc, tol)
