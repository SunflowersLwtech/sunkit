# Docker Deployment Guide

This guide explains how to use MCP Creator Growth with Docker.

## Quick Start

### 1. Build the Image

```bash
docker build -t mcp-creator-growth .
```

### 2. Run with Docker

For interactive use:

```bash
docker run -i mcp-creator-growth
```

### 3. Run with Docker Compose

```bash
docker-compose up -d
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_DEBUG` | `false` | Enable debug logging |
| `HOME` | `/data` | Home directory for persistent storage |

### Volume Mounts

Mount your project directory to allow the MCP server to access your code:

```bash
docker run -i \
  -v $(pwd):/workspace \
  -w /workspace \
  mcp-creator-growth
```

## Using with Claude Desktop

Add this configuration to your Claude Desktop MCP settings:

### macOS/Linux

Edit `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "mcp-creator-growth": {
      "command": "docker",
      "args": [
        "run",
        "-i",
        "--rm",
        "-v",
        "/path/to/your/project:/workspace",
        "-w",
        "/workspace",
        "mcp-creator-growth"
      ]
    }
  }
}
```

### Windows

Edit `%APPDATA%\Claude\claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "mcp-creator-growth": {
      "command": "docker",
      "args": [
        "run",
        "-i",
        "--rm",
        "-v",
        "C:\\path\\to\\your\\project:/workspace",
        "-w",
        "/workspace",
        "mcp-creator-growth"
      ]
    }
  }
}
```

## Persistent Storage

By default, learning sessions and debug records are stored in `/data/.mcp-sidecar` inside the container.

To persist this data:

```bash
docker run -i \
  -v mcp-data:/data/.mcp-sidecar \
  mcp-creator-growth
```

Or use the provided docker-compose.yml which includes a named volume.

## Publishing to Docker Hub

To share your image on Docker Hub:

```bash
# Tag the image
docker tag mcp-creator-growth:latest your-username/mcp-creator-growth:latest

# Push to Docker Hub
docker push your-username/mcp-creator-growth:latest
```

## Glama.ai Integration

This Docker setup is optimized for use with [Glama.ai](https://glama.ai/mcp/servers/@SunflowersLwtech/mcp_creator_growth).

Users can pull and run your MCP server directly:

```bash
docker pull sunflowerslwtech/mcp-creator-growth:latest
docker run -i sunflowerslwtech/mcp-creator-growth:latest
```

## Troubleshooting

### Server Not Responding

Check if the container is running:

```bash
docker ps -a
```

View logs:

```bash
docker logs mcp-creator-growth
```

### Permission Issues

Ensure volumes have proper permissions:

```bash
docker run -i -u $(id -u):$(id -g) \
  -v $(pwd):/workspace \
  mcp-creator-growth
```

### Debug Mode

Enable debug logging:

```bash
docker run -i -e MCP_DEBUG=true mcp-creator-growth
```

## Security Considerations

- The default Dockerfile runs as root. For production, consider creating a non-root user.
- Mount volumes as read-only (`:ro`) when possible to limit container access.
- Use specific tags instead of `latest` for reproducible builds.

## Building for Multiple Architectures

To build multi-platform images (e.g., for ARM and x86):

```bash
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -t your-username/mcp-creator-growth:latest \
  --push .
```
