"""C-02 acquisition pipeline: normalize, redact, label, map to the ontology, gate G1, publish entity candidates."""
from usep.pipeline.worker import AcquisitionWorker, Outcome

__all__ = ["AcquisitionWorker", "Outcome"]
