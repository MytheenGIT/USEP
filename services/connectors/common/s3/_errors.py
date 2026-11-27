def error_code(exc: Exception) -> str:
    return getattr(exc, "response", {}).get("Error", {}).get("Code", "")


def is_missing(exc: Exception) -> bool:
    return error_code(exc) in {"NoSuchKey", "404", "NotFound"}


def is_precondition_failed(exc: Exception) -> bool:
    return error_code(exc) in {"PreconditionFailed", "412", "ConditionalRequestConflict"}
