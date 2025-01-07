"""TCP Server implementation for Crestron."""
import asyncio
import struct
import logging
from typing import Any, Callable, Dict, Set, Final
from collections import defaultdict
from datetime import datetime
import time
from threading import Lock

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .const import (
    MAX_DIGITAL_JOIN,
    MAX_ANALOG_JOIN,
    ERROR_INVALID_JOIN,
    CMD_CLEAR_OUTPUTS,
    CMD_GET_JOINS,
    CMD_UPDATE_REQUEST,
)

_LOGGER = logging.getLogger(__name__)

# Constants for connection management
RECONNECT_DELAY: Final = 5.0  # Delay between reconnection attempts
MAX_RECONNECT_ATTEMPTS: Final = 3  # Maximum number of reconnection attempts
CONNECTION_TIMEOUT: Final = 10.0  # Connection timeout in seconds
MAX_QUEUE_SIZE: Final = 100  # Maximum command queue size
COMMAND_TIMEOUT: Final = 5.0  # Command timeout in seconds
INITIAL_SYNC_TIMEOUT: Final = 5.0  # Timeout waiting for initial sync response

# Constants for join management
MAX_JOIN_UPDATES: Final = 1000  # Maximum number of join updates per second
JOIN_UPDATE_WINDOW: Final = 1.0  # Time window for join update rate limiting
MAX_CALLBACK_TIME: Final = 0.5  # Maximum time for callback execution

class JoinState:
    """Track join state and updates."""

    def __init__(self):
        """Initialize join state."""
        self.value = False
        self.last_update = 0
        self.update_count = 0
        self.callbacks = set()
        self.lock = Lock()

class CrestronServer:
    """Implements TCP Server for Crestron communication."""

    def __init__(self, hass: HomeAssistant, host: str, port: int) -> None:
        """Initialize the server."""
        self.hass = hass
        self._host = host
        self._port = port
        self._entry_id = None
        self._version = "1.0.0"
        
        # Connection state
        self._server = None
        self._writer = None
        self._reader = None
        self._available = False
        self._reconnect_task = None
        self._command_queue = asyncio.Queue(maxsize=MAX_QUEUE_SIZE)
        self._command_task = None
        self._command_lock = asyncio.Lock()
        self._command_event = asyncio.Event()
        
        # Thread safety
        self._state_lock = Lock()
        self._callback_lock = Lock()
        self._join_lock = Lock()
        self._connection_lock = Lock()
        
        # Join state
        self._digital = defaultdict(JoinState)
        self._analog = defaultdict(JoinState)
        self._serial = defaultdict(JoinState)
        self._join_update_times = defaultdict(list)
        
        # Callback management
        self._join_callbacks: Dict[str, set[Callable]] = defaultdict(set)
        self._global_callbacks: Set[Callable] = set()
        self._callback_tasks = set()
        self._sync_all_joins_callback = None

        # Initial sync tracking
        self._initial_sync_received = False
        self._initial_sync_event = asyncio.Event()
        self._last_sync_request = 0

    @property
    def available(self) -> bool:
        """Return if server is available."""
        with self._state_lock:
            is_available = (
                self._available and
                self._writer is not None and
                not self._writer.is_closing()
            )
            return is_available

    @property
    def entry_id(self) -> str | None:
        """Return the config entry ID."""
        return self._entry_id

    @property
    def version(self) -> str:
        """Return server version."""
        return self._version

    def set_entry_id(self, entry_id: str) -> None:
        """Set the config entry ID."""
        self._entry_id = entry_id

    def is_available(self) -> bool:
        """Return if server is available."""
        return self.available

    def _validate_join(self, join: int, join_type: str) -> None:
        """Validate join number."""
        if join_type == "d" and not 0 < join <= MAX_DIGITAL_JOIN:
            raise ValueError(f"{ERROR_INVALID_JOIN}: Digital join {join} exceeds maximum {MAX_DIGITAL_JOIN}")
        elif join_type == "a" and not 0 < join <= MAX_ANALOG_JOIN:
            raise ValueError(f"{ERROR_INVALID_JOIN}: Analog join {join} exceeds maximum {MAX_ANALOG_JOIN}")

    def _check_rate_limit(self, join_id: str) -> bool:
        """Check if join updates are within rate limit."""
        with self._join_lock:
            now = time.time()
            updates = self._join_update_times[join_id]
            
            # Remove old updates
            while updates and now - updates[0] > JOIN_UPDATE_WINDOW:
                updates.pop(0)
                
            # Check rate limit
            if len(updates) >= MAX_JOIN_UPDATES:
                return False
                
            updates.append(now)
            return True

    async def start(self) -> bool:
        """Start TCP server."""
        try:
            with self._connection_lock:
                # Clean up any existing server
                if self._server:
                    await self.stop()
                    
                # Create new server with socket reuse
                self._server = await asyncio.start_server(
                    self.handle_connection,
                    "0.0.0.0",
                    self._port,
                    reuse_address=True,
                    reuse_port=True,
                )
                addr = self._server.sockets[0].getsockname()
                _LOGGER.info(f"Listening on {addr}:{self._port}")
                
                # Reset state
                with self._state_lock:
                    self._available = False
                    self._command_event.clear()
                
                # Start tasks
                self._command_task = asyncio.create_task(self._process_command_queue())
                
                # Start serving
                asyncio.create_task(self._server.serve_forever())
                return True
                
        except Exception as err:
            _LOGGER.error(f"Failed to start server: {err}")
            return False

    async def stop(self):
        """Stop TCP server."""
        try:
            with self._connection_lock:
                # First notify all callbacks about disconnection
                with self._state_lock:
                    self._available = False
                    self._command_event.clear()
                await self._notify_callbacks("system", "disconnected")
                
                # Cancel tasks
                if self._command_task and not self._command_task.done():
                    self._command_task.cancel()
                if self._reconnect_task and not self._reconnect_task.done():
                    self._reconnect_task.cancel()
                    
                # Wait for tasks to complete
                tasks = []
                if self._command_task:
                    tasks.append(self._command_task)
                if self._reconnect_task:
                    tasks.append(self._reconnect_task)
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
                
                # Close writer if it exists
                if self._writer:
                    try:
                        self._writer.close()
                        await asyncio.wait_for(self._writer.wait_closed(), timeout=5.0)
                    except (asyncio.TimeoutError, Exception) as err:
                        _LOGGER.error("Error closing writer: %s", err)
                    self._writer = None

                # Close server if it exists  
                if self._server:
                    try:
                        self._server.close()
                        await asyncio.wait_for(self._server.wait_closed(), timeout=5.0)
                    except (asyncio.TimeoutError, Exception) as err:
                        _LOGGER.error("Error closing server: %s", err)
                    self._server = None

                # Clear state
                with self._state_lock:
                    self._command_queue = asyncio.Queue(maxsize=MAX_QUEUE_SIZE)
                    
                with self._join_lock:
                    self._digital.clear()
                    self._analog.clear()
                    self._serial.clear()
                    self._join_update_times.clear()
                    
                with self._callback_lock:
                    self._callback_tasks.clear()

                _LOGGER.info("Server stopped")
                
                # Add a small delay to ensure socket is released
                await asyncio.sleep(1)
                
        except Exception as err:
            _LOGGER.error("Error stopping server: %s", err)
        finally:
            # Ensure these are cleared even if there were errors
            with self._state_lock:
                self._writer = None
                self._reader = None
                self._server = None
                self._command_task = None
                self._reconnect_task = None

    async def _process_command_queue(self):
        """Process commands from the queue."""
        while True:
            try:
                # Wait for server to be available
                if not self.available:
                    await self._command_event.wait()
                
                # Get command from queue
                try:
                    command = await asyncio.wait_for(
                        self._command_queue.get(),
                        timeout=COMMAND_TIMEOUT
                    )
                except asyncio.TimeoutError:
                    continue
                
                if not self.available:
                    _LOGGER.debug("Skipping command, server not available")
                    self._command_queue.task_done()
                    continue
                    
                async with self._command_lock:
                    try:
                        await command()
                    except Exception as err:
                        _LOGGER.error("Error processing command: %s", err)
                        # Connection error, mark as unavailable
                        if self._available:
                            self._available = False
                            self._command_event.clear()
                            await self._notify_callbacks("system", "disconnected")
                        
                self._command_queue.task_done()
                
            except asyncio.CancelledError:
                break
            except Exception as err:
                _LOGGER.error("Error in command queue: %s", err)
                await asyncio.sleep(0.1)  # Prevent tight loop on error

    async def handle_connection(self, reader, writer):
        """Handle incoming connection."""
        try:
            self._writer = writer
            self._reader = reader
            peer = writer.get_extra_info("peername")
            _LOGGER.info(f"Control system connection from {peer}")
            
            # Reset sync state
            self._initial_sync_received = False
            self._initial_sync_event.clear()
            self._last_sync_request = 0
            
            # Clear existing state
            self._digital.clear()
            self._analog.clear()
            self._serial.clear()
            
            # Send initial update request
            writer.write(CMD_UPDATE_REQUEST)
            await writer.drain()
            _LOGGER.debug("Sent initial sync request")
            
            connected = True
            while connected:
                try:
                    data = await reader.read(1)
                    if data:
                        # Sync all joins request/response
                        if data[0] == 0xFB:
                            # Debounce sync requests
                            current_time = time.time()
                            if current_time - self._last_sync_request > 0.1:  # 100ms debounce
                                self._last_sync_request = current_time
                                
                                # If this is first sync after connection
                                if not self._initial_sync_received:
                                    _LOGGER.debug("Received initial sync response")
                                    self._initial_sync_received = True
                                    self._initial_sync_event.set()
                                    
                                    # Now mark as available and notify
                                    self._available = True
                                    self._command_event.set()
                                    await self._notify_callbacks("system", "connected")
                                    _LOGGER.debug("Server marked as available after initial sync")
                                    
                                    # Request all joins again to ensure we have latest state
                                    writer.write(CMD_UPDATE_REQUEST)
                                    await writer.drain()
                                    _LOGGER.debug("Sent follow-up sync request")
                                
                                # Call sync callback if registered
                                if self._sync_all_joins_callback is not None:
                                    await self._sync_all_joins_callback()
                                
                        else:
                            data += await reader.read(1)
                            # Digital Join
                            if (
                                data[0] & 0b11000000 == 0b10000000
                                and data[1] & 0b10000000 == 0b00000000
                            ):
                                header = struct.unpack("BB", data)
                                join = ((header[0] & 0b00011111) << 7 | header[1]) + 1
                                value = ~header[0] >> 5 & 0b1
                                
                                _LOGGER.debug(
                                    "Raw digital packet received: bytes=%02x %02x, join=%d, value=%d",
                                    data[0],
                                    data[1],
                                    join,
                                    value
                                )
                                
                                # Convert to bool and get join state
                                current_bool = value == 1
                                join_state = self._digital[join]
                                join_id = f"d{join}"
                                
                                _LOGGER.debug(
                                    "Processing digital packet - join: %d, join_id: %s, current_bool: %s, stored_value: %s, initial_sync: %s",
                                    join,
                                    join_id,
                                    current_bool,
                                    join_state.value,
                                    self._initial_sync_received
                                )
                                
                                # Update state and notify
                                old_value = join_state.value
                                join_state.value = current_bool
                                join_state.last_update = time.time()
                                join_state.update_count += 1
                                
                                _LOGGER.debug(
                                    "Digital value changed - join: %d, join_id: %s, value: %s -> %s",
                                    join,
                                    join_id,
                                    old_value,
                                    current_bool
                                )
                                
                                # Send value as string "1" or "0" for consistency
                                _LOGGER.debug(
                                    "Notifying callbacks for %s with value %s",
                                    join_id,
                                    "1" if current_bool else "0"
                                )
                                
                                await self._notify_callbacks(join_id, "1" if current_bool else "0")
                                
                                _LOGGER.debug(
                                    "Processed digital value: join=%d, value=%s, callbacks_notified=%d",
                                    join,
                                    current_bool,
                                    len(self._join_callbacks.get(join_id, set()))
                                )
                                
                            # Analog Join
                            elif (
                                data[0] & 0b11001000 == 0b11000000
                                and data[1] & 0b10000000 == 0b00000000
                            ):
                                data += await reader.read(2)
                                header = struct.unpack("BBBB", data)
                                join = ((header[0] & 0b00000111) << 7 | header[1]) + 1
                                value = (
                                    (header[0] & 0b00110000) << 10 | header[2] << 7 | header[3]
                                )
                                
                                # Only update if value changed
                                join_state = self._analog[join]
                                if join_state.value != value:
                                    join_state.value = value
                                    join_state.last_update = time.time()
                                    join_state.update_count += 1
                                    
                                    await self._notify_callbacks(f"a{join}", str(value))
                                    _LOGGER.debug("Received analog value: join=%d, value=%d", join, value)
                                
                            # Serial Join
                            elif (
                                data[0] & 0b11111000 == 0b11001000
                                and data[1] & 0b10000000 == 0b00000000
                            ):
                                data += await reader.readuntil(b"\xff")
                                header = struct.unpack("BB", data[:2])
                                join = ((header[0] & 0b00000111) << 7 | header[1]) + 1
                                string = data[2:-1].decode("utf-8")
                                
                                # Only update if value changed
                                join_state = self._serial[join]
                                if join_state.value != string:
                                    join_state.value = string
                                    join_state.last_update = time.time()
                                    join_state.update_count += 1
                                    
                                    await self._notify_callbacks(f"s{join}", string)
                                    _LOGGER.debug("Received serial value: join=%d, value=%s", join, string)
                    else:
                        _LOGGER.info("Control system disconnected")
                        connected = False
                        self._available = False
                        self._command_event.clear()
                        await self._notify_callbacks("system", "disconnected")
                        
                except Exception as err:
                    _LOGGER.error("Error handling connection: %s", err)
                    connected = False
                    self._available = False
                    self._command_event.clear()
                    await self._notify_callbacks("system", "disconnected")
                    
        except Exception as err:
            _LOGGER.error("Error in connection handler: %s", err)
        finally:
            # Clean up connection
            if self._writer:
                try:
                    self._writer.close()
                    await self._writer.wait_closed()
                except Exception:
                    pass
            self._writer = None
            self._reader = None
            self._available = False
            self._command_event.clear()
            self._initial_sync_received = False
            self._initial_sync_event.clear()
            await self._notify_callbacks("system", "disconnected")

    async def get_analog(self, join: int) -> int | None:
        """Get analog value for join."""
        try:
            self._validate_join(join, "a")
            if not self.available:
                _LOGGER.debug("Cannot get analog value: server not available")
                return None
            join_state = self._analog[join]
            return join_state.value
        except Exception as err:
            _LOGGER.error("Error getting analog value: %s", err)
            return None

    async def set_analog(self, join: int, value: int) -> None:
        """Send Analog Join to Crestron."""
        try:
            self._validate_join(join, "a")
            if not self.available:
                raise ConnectionError("Server not available")
                
            if not self._writer:
                raise ConnectionError("No connection to Crestron system")
                
            # Check rate limit
            join_id = f"a{join}"
            if not self._check_rate_limit(join_id):
                raise HomeAssistantError(f"Join {join_id} update rate exceeded")
                
            # Create command
            async def send_command():
                data = struct.pack(
                    ">BBBB",
                    0b11000000 | (value >> 10 & 0b00110000) | (join - 1) >> 7,
                    (join - 1) & 0b01111111,
                    value >> 7 & 0b01111111,
                    value & 0b01111111,
                )
                self._writer.write(data)
                await self._writer.drain()
                _LOGGER.debug("Sent analog value: join=%d, value=%d", join, value)
                
                # Update state
                join_state = self._analog[join]
                join_state.value = value
                join_state.last_update = time.time()
                join_state.update_count += 1
            
            # Queue command
            await self._command_queue.put(send_command)
            
        except Exception as err:
            raise ConnectionError(f"Failed to send analog value: {err}") from err

    def register_callback(self, join_id: str, callback: Callable[[Any], None]) -> Callable[[], None]:
        """Register callback for updates."""
        with self._callback_lock:
            if join_id == "system":
                self._global_callbacks.add(callback)
            else:
                # Add callback to the set for this join
                if join_id not in self._join_callbacks:
                    self._join_callbacks[join_id] = set()
                self._join_callbacks[join_id].add(callback)
            
            def unregister():
                with self._callback_lock:
                    if join_id == "system":
                        self._global_callbacks.discard(callback)
                    else:
                        if join_id in self._join_callbacks:
                            self._join_callbacks[join_id].discard(callback)
                            if not self._join_callbacks[join_id]:
                                del self._join_callbacks[join_id]
            
            return unregister

    def unregister_callback(self, join_id: str, callback: Callable[[Any], None]) -> None:
        """Remove callback."""
        _LOGGER.debug("Unregistering callback for %s", join_id)
        
        if join_id == "system":
            self._global_callbacks.discard(callback)
            _LOGGER.debug("Removed global callback")
        else:
            if join_id in self._join_callbacks:
                self._join_callbacks[join_id].discard(callback)
                # Remove the join_id if no callbacks left
                if not self._join_callbacks[join_id]:
                    del self._join_callbacks[join_id]
            _LOGGER.debug("Removed callback for join %s", join_id)

    async def _notify_callbacks(self, join_id: str, value: Any) -> None:
        """Notify callbacks of join updates."""
        try:
            callbacks = []
            
            # Get callbacks for this join under lock
            with self._callback_lock:
                if join_id in self._join_callbacks:
                    callbacks.extend(list(self._join_callbacks[join_id]))
                
                # Include global callbacks for system events
                if join_id == "system":
                    callbacks.extend(list(self._global_callbacks))
            
            # Create tasks for callbacks
            tasks = []
            for callback in callbacks:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        task = asyncio.create_task(callback(value))
                    else:
                        callback(value)
                        task = None
                    
                    if task:
                        tasks.append(task)
                        
                except Exception as err:
                    _LOGGER.error("Error executing callback for %s: %s", join_id, err)
            
            # Wait for callbacks with timeout
            if tasks:
                try:
                    await asyncio.wait_for(asyncio.gather(*tasks), timeout=MAX_CALLBACK_TIME)
                except asyncio.TimeoutError:
                    _LOGGER.warning("Callbacks timed out for %s", join_id)
                except Exception as err:
                    _LOGGER.error("Error in callbacks for %s: %s", join_id, err)
                    
        except Exception as err:
            _LOGGER.error("Error notifying callbacks: %s", err)

    async def _run_callback(self, callback: Callable, value: Any) -> None:
        """Run a single callback with error handling."""
        try:
            if asyncio.iscoroutinefunction(callback):
                await callback(value)
            else:
                callback(value)
        except Exception as err:
            _LOGGER.error("Error in callback: %s", err)

    async def get_digital(self, join: int) -> bool:
        """Get digital value for join."""
        try:
            self._validate_join(join, "d")
            if not self.available:
                _LOGGER.debug("Cannot get digital value: server not available")
                return False
            join_state = self._digital[join]
            return join_state.value or False
        except Exception as err:
            _LOGGER.error("Error getting digital value: %s", err)
            return False

    async def set_digital(self, join: int, value: bool) -> None:
        """Send Digital Join to Crestron."""
        try:
            self._validate_join(join, "d")
            if not self.available:
                raise ConnectionError("Server not available")
                
            if not self._writer:
                raise ConnectionError("No connection to Crestron system")
                
            # Check rate limit
            join_id = f"d{join}"
            if not self._check_rate_limit(join_id):
                raise HomeAssistantError(f"Join {join_id} update rate exceeded")
                
            # Create command
            async def send_command():
                data = struct.pack(
                    ">BB",
                    0b10000000 | (~value << 5 & 0b00100000) | (join - 1) >> 7,
                    (join - 1) & 0b01111111,
                )
                self._writer.write(data)
                await self._writer.drain()
                _LOGGER.debug("Sent digital value: join=%d, value=%s", join, value)
                
                # Don't update state here - wait for response from Crestron
            
            # Queue command
            await self._command_queue.put(send_command)
            
        except Exception as err:
            raise ConnectionError(f"Failed to send digital value: {err}") from err

    async def get_serial(self, join: int) -> str:
        """Get serial value for join."""
        try:
            if not self.available:
                _LOGGER.debug("Cannot get serial value: server not available")
                return ""
            join_state = self._serial[join]
            return join_state.value or ""
        except Exception as err:
            _LOGGER.error("Error getting serial value: %s", err)
            return ""

    async def set_serial(self, join: int, string: str) -> None:
        """Send Serial Join to Crestron."""
        try:
            if not self.available:
                raise ConnectionError("Server not available")
                
            if not self._writer:
                raise ConnectionError("No connection to Crestron system")
                
            if len(string) > 252:
                raise ValueError(f"String too long ({len(string)}>252)")
                
            # Check rate limit
            join_id = f"s{join}"
            if not self._check_rate_limit(join_id):
                raise HomeAssistantError(f"Join {join_id} update rate exceeded")
                
            # Create command
            async def send_command():
                data = struct.pack(
                    ">BB", 0b11001000 | ((join - 1) >> 7), (join - 1) & 0b01111111
                )
                data += string.encode()
                data += b"\xff"
                self._writer.write(data)
                await self._writer.drain()
                _LOGGER.debug("Sent serial value: join=%d, value=%s", join, string)
                
                # Update state
                join_state = self._serial[join]
                join_state.value = string
                join_state.last_update = time.time()
                join_state.update_count += 1
            
            # Queue command
            await self._command_queue.put(send_command)
            
        except Exception as err:
            raise ConnectionError(f"Failed to send serial value: {err}") from err

    def register_sync_all_joins_callback(self, callback: Callable) -> None:
        """Register callback for when control system requests all joins update."""
        _LOGGER.debug("Registering sync-all-joins callback")
        self._sync_all_joins_callback = callback

    def _handle_join_update(self, join_type: str, join: int, value: Any) -> None:
        """Handle join updates."""
        join_id = f"{join_type}{join}"
        
        # Log warning for unregistered joins during initial sync
        if not self._available and join_id not in self._registered_joins:
            _LOGGER.warning(
                "Received value for unregistered %s join %s: %s",
                "digital" if join_type == "d" else "analog",
                join,
                value
            )
            return
            
        # Notify callbacks
        if join_id in self._join_callbacks:
            for callback in self._join_callbacks[join_id]:
                try:
                    callback(value)
                except Exception as err:
                    _LOGGER.error(
                        "Error in callback for join %s: %s",
                        join_id,
                        err,
                        exc_info=True
                    )

    def _handle_analog_update(self, join: int, value: int) -> None:
        """Handle analog join updates."""
        self._handle_join_update("a", join, value)

    def _handle_digital_update(self, join: int, value: bool) -> None:
        """Handle digital join updates."""
        self._handle_join_update("d", join, value)