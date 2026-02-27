"""MCP stdio transport over SSH: run the server command on a remote host and use its stdin/stdout."""

import logging
from contextlib import asynccontextmanager
from typing import Optional, Dict, List

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream

import mcp.types as types
from mcp.shared.message import SessionMessage

logger = logging.getLogger(__name__)

# Timeout for graceful process shutdown (match mcp.client.stdio)
PROCESS_TERMINATION_TIMEOUT = 2.0


@asynccontextmanager
async def stdio_ssh_client(
    ssh_host_alias: str,
    command: str,
    args: Optional[List[str]] = None,
    env: Optional[Dict[str, str]] = None,
    encoding: str = "utf-8",
    encoding_errors: str = "strict",
):
    """Async context manager that runs an MCP server over SSH and yields (read_stream, write_stream).

    Uses the same anyio stream types as mcp.client.stdio.stdio_client so it can be
    passed to Strands MCPClient. Resolves ssh_host_alias and key via glitch.tools.ssh_tools.
    """
    from glitch.tools.ssh_tools import _resolve_host, _get_ssh_private_key
    import asyncssh

    resolved = _resolve_host(ssh_host_alias)
    if not resolved:
        raise ValueError(f"Unknown SSH host alias: {ssh_host_alias}")
    key = _get_ssh_private_key()
    if not key:
        raise ValueError("SSH key not configured (GLITCH_SSH_KEY_PATH or glitch/ssh-key)")

    conn = await asyncssh.connect(
        resolved["host"],
        port=resolved["port"],
        username=resolved["user"],
        client_keys=[key],
        known_hosts=None,
    )

    try:
        full_cmd = [command] + (args or [])
        process = await conn.create_process(
            full_cmd[0],
            *full_cmd[1:],
            env=env,
            encoding=encoding,
        )
    except Exception as e:
        conn.close()
        raise RuntimeError(f"Failed to start MCP process on {ssh_host_alias}: {e}") from e

    read_stream_writer, read_stream = anyio.create_memory_object_stream(0)
    write_stream, write_stream_reader = anyio.create_memory_object_stream(0)

    async def stdout_reader() -> None:
        try:
            async with read_stream_writer:
                while True:
                    try:
                        line = await process.stdout.readline()
                        if not line:
                            break
                        if isinstance(line, bytes):
                            line = line.decode(encoding, errors=encoding_errors)
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            message = types.JSONRPCMessage.model_validate_json(line)
                            await read_stream_writer.send(SessionMessage(message))
                        except Exception as exc:
                            logger.debug("Parse JSON-RPC from remote MCP: %s", exc)
                            await read_stream_writer.send(exc)
                    except (asyncssh.BreakReceived, asyncssh.ConnectionLost, Exception) as e:
                        logger.debug("SSH stdout read ended: %s", e)
                        break
        except anyio.ClosedResourceError:
            await anyio.lowlevel.checkpoint()

    async def stdin_writer() -> None:
        try:
            async with write_stream_reader:
                async for session_message in write_stream_reader:
                    json_str = session_message.message.model_dump_json(by_alias=True, exclude_none=True)
                    out = (json_str + "\n").encode(encoding, errors=encoding_errors)
                    await process.stdin.write(out)
        except anyio.ClosedResourceError:
            await anyio.lowlevel.checkpoint()

    async with anyio.create_task_group() as tg:
        tg.start_soon(stdout_reader)
        tg.start_soon(stdin_writer)
        try:
            yield read_stream, write_stream
        finally:
            try:
                if process.stdin:
                    process.stdin.write_eof()
            except Exception:
                pass
            try:
                with anyio.fail_after(PROCESS_TERMINATION_TIMEOUT):
                    await process.wait()
            except (TimeoutError, Exception):
                try:
                    process.terminate()
                except Exception:
                    pass
            await read_stream.aclose()
            await write_stream.aclose()
            await read_stream_writer.aclose()
            await write_stream_reader.aclose()
    conn.close()
