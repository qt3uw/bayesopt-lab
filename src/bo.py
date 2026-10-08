"""
Minimal Bayesian optimization loop: Gaussian process + UCB acquisition.

Anything with `parameter_space()` and `evaluate(params)` can be optimized
(see `Experiment`). Synthetic demo, no hardware needed:

    python src/bo.py
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import List, Protocol, Tuple

import numpy as np
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import Matern, WhiteKernel


@dataclass
class Parameter:
    name: str
    bounds: Tuple[float, float]  # physical (low, high)


class Experiment(Protocol):
    def parameter_space(self) -> List[Parameter]:
        """Returns the physical parameter definitions for BO."""

    def evaluate(self, params: dict[str, float]) -> float:
        """Apply params, measure, return the objective. Higher is better."""


def normalize(params: List[Parameter], physical: dict) -> np.ndarray:
    return np.array(
        [(physical[p.name] - p.bounds[0]) / (p.bounds[1] - p.bounds[0]) for p in params],
        dtype=float,
    )


def denormalize(params: List[Parameter], unit: np.ndarray) -> dict:
    return {
        p.name: p.bounds[0] + float(unit[i]) * (p.bounds[1] - p.bounds[0])
        for i, p in enumerate(params)
    }


def latin_hypercube(params: List[Parameter], n: int) -> List[dict]:
    dim = len(params)
    unit = np.zeros((n, dim))
    for j in range(dim):
        strata = (np.arange(n) + np.random.rand(n)) / n
        np.random.shuffle(strata)
        unit[:, j] = strata
    return [denormalize(params, unit[i]) for i in range(n)]


class SimpleBO:
    def __init__(self, parameters: List[Parameter], beta: float = 2.0):
        self.parameters = parameters
        self.beta = beta
        # Without a length-scale floor the fit collapses to 1e-5 and BO degrades to random search.
        matern = Matern(length_scale=0.5, length_scale_bounds=(0.01, 10.0), nu=2.5)
        kernel = matern + WhiteKernel(noise_level=1e-4)
        self.gp = GaussianProcessRegressor(kernel=kernel, normalize_y=True, alpha=1e-6)
        self.X: List[np.ndarray] = []
        self.y: List[float] = []

    def suggest(self, candidates: int = 256) -> np.ndarray:
        dim = len(self.parameters)
        if len(self.y) < dim + 1:
            return np.random.rand(dim)

        self.gp.fit(np.vstack(self.X), np.array(self.y))
        unit_candidates = np.random.rand(candidates, dim)
        mean, std = self.gp.predict(unit_candidates, return_std=True)
        ucb = mean + self.beta * std
        return unit_candidates[int(np.argmax(ucb))]

    def observe(self, unit_x: np.ndarray, objective: float) -> None:
        self.X.append(unit_x.astype(float))
        self.y.append(float(objective))


def run(experiment: Experiment, init_trials: int = 5, max_trials: int = 100, seed: int = 123) -> dict:
    random.seed(seed)
    np.random.seed(seed)
    parameters = experiment.parameter_space()

    bo = SimpleBO(parameters)
    initial = latin_hypercube(parameters, init_trials)
    best = {"params": None, "objective": -float("inf")}

    for t in range(max_trials):
        proposal = initial[t] if t < init_trials else denormalize(parameters, bo.suggest())
        objective = float(experiment.evaluate(proposal))
        bo.observe(normalize(parameters, proposal), objective)
        if objective > best["objective"]:
            best = {"params": proposal, "objective": objective}
        print(f"trial {t:02d} | objective={objective:.4f} | params={proposal}")

    print(f"\nBest found: {best}")
    return best


class SyntheticExperiment:
    """Gaussian hill peaked at noise_amp=2.2, noise_freq=420, max ~1.0."""

    def parameter_space(self) -> List[Parameter]:
        return [Parameter("noise_amp", (0.0, 5.0)), Parameter("noise_freq", (10.0, 2000.0))]

    def evaluate(self, params: dict[str, float]) -> float:
        amp_peak = math.exp(-0.5 * ((params["noise_amp"] - 2.2) / 0.8) ** 2)
        freq_peak = math.exp(-0.5 * ((params["noise_freq"] - 420.0) / 180.0) ** 2)
        return amp_peak * freq_peak + random.gauss(0, 0.01)


if __name__ == "__main__":
    best = run(SyntheticExperiment(), max_trials=30)
    assert best["objective"] > 0.9, f"BO failed to find the synthetic peak: {best}"
