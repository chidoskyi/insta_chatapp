import asyncio
import websockets
import json

async def test_connection():
    url = "ws://localhost:8000/ws/test/"
    
    print(f"Testing connection to: {url}")
    
    try:
        async with websockets.connect(url) as ws:
            print("✅ Connected successfully!")
            
            # Test 1: Send ping
            print("\n📤 Sending ping...")
            await ws.send(json.dumps({"action": "ping"}))
            response = await ws.recv()
            print(f"📨 Ping response: {response}")
            
            # Test 2: Send echo
            print("\n📤 Sending echo test...")
            await ws.send(json.dumps({"action": "echo", "message": "Hello"}))
            response = await ws.recv()
            print(f"📨 Echo response: {response}")
            
            # Test 3: Send raw text
            print("\n📤 Sending raw text...")
            await ws.send("Hello raw text")
            response = await ws.recv()
            print(f"📨 Raw response: {response}")
            
    except websockets.exceptions.InvalidURI:
        print("❌ Invalid URL format")
    except ConnectionRefusedError:
        print("❌ Connection refused - server not running or wrong port")
    except Exception as e:
        print(f"❌ Error: {type(e).__name__}: {e}")

if __name__ == "__main__":
    asyncio.run(test_connection())