# Share Clipboard

## Usage

### Server

```bash
python clip_sync.py --listen 0.0.0.0:8765 --secret "your-shared-key"
```

### Client

```bash
python clip_sync.py --connect ws://192.168.1.10:8765 --secret "your-shared-key"
```