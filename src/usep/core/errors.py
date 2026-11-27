class ConfigError(Exception):
    """Raised when configuration or a pinned definition is invalid (fail closed)."""


class UsepError(Exception):
    """Base class for run-time errors."""


class OntologyLoadError(UsepError):
    """The ontology or a pinned pack cannot be trusted. Callers fail closed: no partial ontology is returned."""

    def __init__(self, problems: list[str]):
        self.problems = list(problems)
        super().__init__("; ".join(self.problems))


class EventBusError(UsepError):
    pass


class SchemaViolation(EventBusError):
    """An event does not match the registered schema for its topic. It is never written to the bus."""


class PipelineError(UsepError):
    """A record cannot be processed for a reason that is not the record's fault (store down, bad config). Retry."""
