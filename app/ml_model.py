import pathlib
try:
    import joblib
except Exception:  # pragma: no cover - optional dependency
    joblib = None

class MLModel:
    def __init__(self, path="models/ml_model.pkl"):
        p = pathlib.Path(path)
        if joblib and p.exists():
            self.model = joblib.load(p)
        else:
            self.model = None

    def allow(self, feats):
        if self.model is None:
            return True
        return bool(self.model.predict([feats])[0])
