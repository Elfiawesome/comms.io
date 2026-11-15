"""Built-in source plugin package.

Modules are imported lazily by ``comms.registry`` to avoid circular imports.
Third-party plugins can register themselves with the same decorator or via
the ``comms.sources`` Python entry-point group.
"""
