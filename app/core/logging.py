"""Root logging: one formatter, INFO, on stdout.

Imported for its side effect by app.main before anything logs, so the
reasons this API writes - a refused request, a deleted resource - reach
`docker logs` instead of being dropped by Python's default WARNING
level. A no-op when handlers are already installed (pytest, or a host
process that configures logging itself).
"""
import logging


if not logging.getLogger().handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    )