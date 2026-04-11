import json
import os

_WEIGHTS_FILE = os.path.join(os.path.dirname(__file__), "donor_weights.json")

DEFAULT_WEIGHTS = {
    "surplus": 0.8,
    "health":  0.4,
    "dist":    0.5,
    "eff":     0.2,
    "loss":    0.3,
}


def load_weights(path=_WEIGHTS_FILE):
    """
    Load MCDA weights from JSON.
    Returns DEFAULT_WEIGHTS if the file is absent or corrupt.
    """
    try:
        with open(path, "r") as f:
            data = json.load(f)
        return {k: float(data.get(k, v)) for k, v in DEFAULT_WEIGHTS.items()}
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        return dict(DEFAULT_WEIGHTS)


def save_weights(weights, path=_WEIGHTS_FILE):
    """
    Persist the 5 MCDA weights to JSON.

    Args:
        weights: dict with keys matching DEFAULT_WEIGHTS
        path:    file path to write

    Raises:
        OSError: if the file cannot be written
    """
    clean = {k: weights[k] for k in DEFAULT_WEIGHTS}
    with open(path, "w") as f:
        json.dump(clean, f, indent=2)
