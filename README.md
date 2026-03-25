# bayesopt-lab

A minimal Gaussian-process Bayesian optimization loop with ARTIQ-oriented scaffolding for tuning lab hardware parameters from live measurements.

## What it does

This repo is split into two layers:

- **A tiny Bayesian optimization core (`src/main.py`)**:
  - Defines a parameter space (name + bounds)
  - Normalizes parameters into a unit hypercube
  - Uses **Latin Hypercube Sampling** for the first few trials
  - Fits a **Gaussian Process** (scikit-learn) and proposes new points using a simple **UCB (upper confidence bound)** acquisition rule

- **An ARTIQ-friendly experiment scaffold (`src/hardware_driver.py`)**:
  - Lets you declare devices, integer channel args, numeric args, and BO parameters in a single `CONFIG`
  - Generates ARTIQ `setattr_device(...)` and `setattr_argument(...)` bindings in `build()`
  - Runs the host-side BO loop and calls your experiment’s `evaluate(params)` method each trial

There’s also an **example experiment** (`src/run_adc_dac_experiment.py`) showing how you might optimize a Zotino DAC voltage using a Sampler ADC reading as feedback (objective = negative squared error to a target voltage).

## The hard part

The core challenge here is integrating a host-side optimization loop (numpy/scikit-learn) with ARTIQ’s experiment model, where:

- You typically declare devices and user arguments in `build()`
- You cast/prepare arguments in `prepare()`
- Timing-sensitive I/O happens in `@kernel` methods
- But Bayesian optimization logic (GP fitting, acquisition, random sampling) is naturally **host-side Python**

The approach in this repo is to keep that boundary explicit:

- The BO loop is completely host-side and only depends on an `experiment` object supporting:
  - `parameter_space() -> list[Parameter]`
  - `evaluate(params: dict[str, float]) -> float`
- ARTIQ integration happens in a base class (`ConfigurableBOExperiment`) that:
  - Builds devices/arguments from a declarative `CONFIG`
  - Runs the BO loop on the host and calls your `evaluate()` for measurements
- ARTIQ imports are optional: the scaffold can be imported on non-ARTIQ machines, and it will raise a clear error only when you try to run hardware code.

This keeps the optimization loop testable/iterable without dragging in ARTIQ everywhere, while still matching how ARTIQ experiments are structured.

## Stack

### Languages
- Python

### Libraries
- `numpy`
- `scikit-learn` (GaussianProcessRegressor, Matern kernel, WhiteKernel)

### Hardware / lab framework (external dependency)
- ARTIQ (`artiq.experiment`, plus coredevice drivers like Zotino/Sampler/etc.)

### Tooling
- Nix dev shell (`shell.nix`) providing:
  - Python 3.12
  - numpy
  - scikit-learn

## Local setup

### ARTIQ environment (required for hardware experiments)

To run `src/run_adc_dac_experiment.py` or `test_connection.py`, you need an ARTIQ installation and a working ARTIQ setup (master + device_db + connected hardware). This repo includes a `device_db.py`, but it is specific to one lab configuration and hard-codes a core device address.

Once ARTIQ is installed and your device DB is correct, you would run these as ARTIQ experiments using your normal ARTIQ workflow (e.g., via the dashboard/master tooling).

## Project structure

- `src/main.py`  
  Minimal Bayesian optimization implementation:
  - `Parameter` (name + bounds)
  - normalization helpers
  - Latin hypercube initialization
  - `SimpleBO` (GP + UCB acquisition)
  - `run(...)` loop that prints each trial and returns the best found params/objective

- `src/hardware_driver.py`  
  ARTIQ scaffolding:
  - Declarative config types: `DeviceSpec`, `ChannelSpec`, `NumericArgSpec`, `BOExperimentConfig`
  - `ConfigurableBOExperiment`: builds ARTIQ args/devices from `CONFIG`, then runs the host BO loop and calls `evaluate(...)`

- `src/run_adc_dac_experiment.py`  
  Example ARTIQ experiment using Zotino + Sampler:
  - Defines a single BO parameter (`dac_voltage`)
  - Measures Sampler ADC after setting a DAC voltage
  - Objective is `-(measured - target)^2`

- `device_db.py`  
  ARTIQ device database for a specific hardware stack (core + various peripherals). You will almost certainly need to edit this for your setup.

- `test_connection.py` and `repository/test_connection.py`  
  Small ARTIQ experiments used as bring-up / sanity checks for sampling.

- `shell.nix`  
  Minimal dev shell for Python/numpy/scikit-learn.

## Known limitations / what’s next

This is intentionally early-stage and not a polished “library” yet.

- **No packaging / dependency locking**: there is no `pyproject.toml` or `requirements.txt` yet.
- **No runnable demo script**: the synthetic objective exists in `src/main.py`, but there’s no CLI or `python -m ...` entry point.
- **ARTIQ workflow isn’t documented**: the repo doesn’t describe how to start `artiq_master`, point it at `device_db.py`, and run the experiments.
- **`device_db.py` is lab-specific**: it hard-codes a core device IP and a particular hardware inventory.
- **BO implementation is minimal**:
  - acquisition optimization is done by sampling random candidates
  - no constraints, no multi-objective support, no persistence, no resuming runs
- **No tests / CI**.

Next steps include:
1) a small CLI for the synthetic objective (so anyone can run a demo in seconds),  
2) proper packaging + pinned dependencies,  
3) logging/plotting and resumable runs,  
4) better acquisition optimization and parameter types (categorical/discrete),  
5) a clear ARTIQ “how to run” guide and safer hardware bounds.

## Why I built this

I wanted a BO loop that’s small enough to understand end-to-end, but still practical to wire into ARTIQ experiments. The goal wasn’t to compete with full-featured frameworks — it was to have a minimal, hackable baseline that makes the host/kernel boundary explicit and makes it easy to iterate on “measure → fit → propose” with real lab devices.
