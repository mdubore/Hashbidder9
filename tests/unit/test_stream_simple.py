import asyncio
import json
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from hashbidder.dashboard import app
from hashbidder.metrics import MetricRow, MetricsRepo
from hashbidder.broadcast_hub import BroadcastHub

@pytest.mark.asyncio
async def test_stream_simple():
    mock_repo = AsyncMock(spec=MetricsRepo)
    mock_repo.get_history.return_value = []
    
    mock_hub = MagicMock(spec=BroadcastHub)
    live_queue = asyncio.Queue()
    mock_hub.subscribe.return_value = live_queue
    
    app.state.metrics_repo = mock_repo
    app.state.broadcast_hub = mock_hub
    
    with patch("hashbidder.dashboard.lifespan") as mock_lifespan:
        mock_lifespan.return_value.__aenter__.return_value = None
        
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            async with client.stream("GET", "/stream") as response:
                assert response.status_code == 200
                
                # Publish live event in background
                async def publish_later():
                    await asyncio.sleep(0.1)
                    row = MetricRow(
                        timestamp=100,
                        braiins_hashrate_phs=Decimal("1.0"),
                        ocean_hashrate_phs=Decimal("1.0"),
                        braiins_connected=True,
                        ocean_connected=True,
                        mempool_connected=True
                    )
                    await live_queue.put(row)
                
                asyncio.create_task(publish_later())
                
                async for line in response.aiter_lines():
                    print(f"DEBUG: received line: {line}")
                    if "id: 100" in line:
                        break
                print("DEBUG: test passed")
