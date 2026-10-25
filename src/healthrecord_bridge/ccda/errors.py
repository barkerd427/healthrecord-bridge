"""Exceptions raised by the C-CDA converter."""


class CcdaError(ValueError):
    """Base class for input problems."""


class NotClinicalDocumentError(CcdaError):
    """The XML root is not ``{urn:hl7-org:v3}ClinicalDocument``."""


class UnsafeXmlError(CcdaError):
    """The XML declares a DTD or entities, which this converter refuses to process."""


class NoDocumentsFoundError(CcdaError):
    """An archive contained no C-CDA documents."""
