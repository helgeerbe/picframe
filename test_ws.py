import asyncio
import websockets
import json

async def test():
    async with websockets.connect("ws://localhost:9000/ws/state") as websocket:
        print("Connected")
        while True:
            message = await websocket.recv()
            print(f"Received: {message}")

asyncio.run(test())
