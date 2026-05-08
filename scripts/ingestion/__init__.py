"""Read-only ingestion loaders for the Global Signal Fabric.

Every loader in this package is read-only by construction. Forbidden methods
(place_order, modify_order, cancel_order, redeem_position, submit_order,
execute_trade, buy, sell, long, short) are NOT allowed in any loader.
"""
