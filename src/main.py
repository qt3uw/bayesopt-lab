"""
Extremely minimal Bayesian optimization loop.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Callable, List, Protocol, Tuple

import numpy as np
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import Matern, WhiteKernel


@dataclass
class Parameter:
    name: str
    bounds: Tuple[float, float]


class BOExperiment(Protocol):
    def parameter_space(self) -> List[Parameter]:
        """Returns the physical parameter definitions for BO."""

    def evaluate(self, params: dict[str, float]) -> float:
        """Returns objective value for the proposed physical params."""


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


def evaluate(params: dict) -> float:
    """
    Synthetic objective to exercise the loop without hardware.
    """
    amp = params["noise_amp"]
    freq = params["noise_freq"]
    amp_peak = math.exp(-0.5 * ((amp - 2.2) / 0.8) ** 2)
    freq_peak = math.exp(-0.5 * ((freq - 420.0) / 180.0) ** 2)
    noise = random.gauss(0, 0.01)
    return amp_peak * freq_peak + noise

class SimpleBO:
    def __init__(self, parameters: List[Parameter], beta: float = 2.0):
        self.parameters = parameters
        self.beta = beta
        kernel = Matern(length_scale=0.5, nu=2.5) + WhiteKernel(noise_level=1e-4)
        self.gp = GaussianProcessRegressor(kernel=kernel, normalize_y=True)
        self.X: List[np.ndarray] = []
        self.y: List[float] = []

    def suggest(self, candidates: int = 256) -> np.ndarray:
        dim = len(self.parameters)
        if len(self.y) < dim + 1:
            return np.random.rand(dim)

        X = np.vstack(self.X)
        y = np.array(self.y)
        self.gp.fit(X, y)

        unit_candidates = np.random.rand(candidates, dim)
        preds = self.gp.predict(unit_candidates, return_std=True)
        if isinstance(preds, tuple):
            mean, std = preds[0], preds[1]  # ignore any extra values
        else:
            mean, std = preds, np.zeros_like(preds)
        ucb = mean + self.beta * std
        return unit_candidates[int(np.argmax(ucb))]

    def observe(self, unit_x: np.ndarray, objective: float) -> None:
        self.X.append(unit_x.astype(float))
        self.y.append(float(objective))


def run(
    experiment: BOExperiment,
    init_trials: int = 5,
    max_trials: int = 100,
    seed: int = 123,
    stabilizer: Callable[[dict], None] | None = None,
) -> dict:
    random.seed(seed)
    np.random.seed(seed)
    stabilize = stabilizer or (lambda _: None)
    parameters = experiment.parameter_space()

    bo = SimpleBO(parameters)
    initial = latin_hypercube(parameters, init_trials)

    best = {"params": None, "objective": -float("inf")}

    for t in range(max_trials):
        proposal = initial[t] if t < init_trials else denormalize(parameters, bo.suggest())
        stabilize(proposal)
        objective_value = experiment.evaluate(proposal)
        bo.observe(normalize(parameters, proposal), objective_value)
        if objective_value > best["objective"]:
            best = {"params": proposal, "objective": objective_value}
        print(f"trial {t:02d} | objective={objective_value:.4f} | params={proposal}")

    print("\nBest found:")
    print(best)
    return best


# if __name__ == "__main__":
    
