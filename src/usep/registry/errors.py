from usep.core.errors import OntologyLoadError


class RegistryError(OntologyLoadError):
    """A release, signature, pin or store problem. It is an OntologyLoadError, so every consumer that already fails closed on
    a bad ontology (the pipeline's config cache keeps what it has) does the same here."""

    def __init__(self, message: str) -> None:
        super().__init__([message])
