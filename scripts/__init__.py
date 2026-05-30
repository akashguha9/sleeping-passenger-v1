"""Project scripts package for sleeping-passenger-v1.

Marks ``scripts`` as a regular package so ``scripts.<module>`` imports resolve
deterministically under any ``sys.path`` ordering.  Importing this package has
no side effects: no DB, no filesystem, no network, no broker calls.
"""
