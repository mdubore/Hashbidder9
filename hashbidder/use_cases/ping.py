"""Ping and current-bids use cases."""

from hashbidder.client import HashpowerClient, OrderBook, UserBid


async def run_ping(client: HashpowerClient) -> OrderBook:
    """Fetch the current order book.

    Args:
        client: The hashpower market client to use.

    Returns:
        The current spot order book snapshot.
    """
    return await client.get_orderbook()


async def get_current_bids(client: HashpowerClient) -> tuple[UserBid, ...]:
    """Fetch the authenticated user's active bids.

    Args:
        client: The hashpower market client to use.

    Returns:
        The user's currently active spot bids.
    """
    return await client.get_current_bids()
