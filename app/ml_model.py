import pathlib

try:
    import joblib
except Exception:  # pragma: no cover - optional dependency
    joblib = None


class MLModel:
    """Load optional ML model for signal filtering."""

    def __init__(self, path: str = "models/ml_model.pkl") -> None:
        p = pathlib.Path(path)
        if joblib and p.exists():
            self.model = joblib.load(p)
        else:
            self.model = None

    def allow(self, feats: list[float] | tuple[float, ...]) -> bool:
        """Return True if the features pass the ML filter."""
        if self.model is None:
            return True
        return bool(self.model.predict([feats])[0])
