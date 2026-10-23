"""Bootstrap helpers that must run before ``lamtools_core`` is imported.

Nothing in this package may import ``lamtools_core``: module overrides have to
be installed before the first host module loads, so the bootstrap code is
standard-library only.
"""
