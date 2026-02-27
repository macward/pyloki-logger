# pyloki-logger

Non-blocking Python client for sending logs to [Grafana Loki](https://grafana.com/oss/loki/). Batches entries in memory, flushes in a background thread with gzip compression, and retries on failure. Single dependency: `httpx`.

**Python 3.11+**

## Install

```bash
pip install pyloki-logger
```

## Quick start

```python
from loki_client import Loki

loki = Loki(endpoint="http://localhost:3100", app="myapp", environment="production")

loki.info("User signed in", user_id="42", ip="10.0.0.1")
loki.error("Payment failed", order_id="abc-123", reason="timeout")

loki.stop()  # flush remaining logs and close connections
```

Log calls return immediately. A background thread batches and ships entries to Loki.

## Configuration

Pass a `LokiConfig` object for full control:

```python
from loki_client import Loki, LokiConfig

config = LokiConfig(
    endpoint="https://loki.example.com",
    app="billing",
    environment="staging",
    batch_size=200,           # flush every N entries (default: 100)
    flush_interval=2.0,       # flush every N seconds (default: 5.0)
    max_buffer_size=50_000,   # hard cap on buffered entries (default: 10,000)
    max_batch_bytes=1_048_576,# max payload size per HTTP request (default: 1 MB)
    max_retries=3,            # retry failed batches up to N times (default: 3)
    retry_backoff=1.0,        # base backoff in seconds, doubles each attempt (default: 1.0)
    timeout=10.0,             # HTTP request timeout in seconds (default: 10.0)
    gzip_enabled=True,        # gzip compress payloads (default: True)
    auth_header="Bearer <token>",  # Authorization header (default: None)
    extra_labels={"team": "payments"},  # additional low-cardinality labels
)

loki = Loki(config)
```

Or use keyword arguments directly:

```python
loki = Loki(endpoint="http://localhost:3100", app="myapp")
```

## Log levels

```python
loki.debug("Verbose detail here")
loki.info("Normal operation")
loki.warn("Something looks off")
loki.error("Something broke", traceback="...")
```

Each method accepts `**kwargs` as metadata. Metadata is appended to the log line as `key=value` pairs, keeping Loki labels low-cardinality:

```
User signed in | user_id=42 ip=10.0.0.1
```

Only `app`, `env`, `level`, and `extra_labels` go into Loki stream labels. Everything else stays in the log line.

## stdlib logging integration

### Share buffer with an existing client

```python
import logging
from loki_client import Loki, LokiHandler

loki = Loki(endpoint="http://localhost:3100", app="myapp")

handler = LokiHandler.from_client(loki)
logger = logging.getLogger("myapp")
logger.addHandler(handler)
logger.setLevel(logging.DEBUG)

logger.info("This goes to Loki via the shared buffer")
logger.error("So does this", exc_info=True)  # traceback included automatically

# When done:
loki.stop()
```

### Standalone handler (no separate client needed)

```python
import logging
from loki_client import LokiHandler

handler = LokiHandler.standalone(endpoint="http://localhost:3100", app="myapp")
logger = logging.getLogger("myapp")
logger.addHandler(handler)
logger.setLevel(logging.INFO)

logger.warning("Disk usage high")

# handler.close() stops the internal client
```

The handler automatically:
- Maps Python log levels: `DEBUG`->`debug`, `INFO`->`info`, `WARNING`->`warn`, `ERROR`/`CRITICAL`->`error`
- Extracts metadata: logger name, module, function name
- Includes tracebacks on exceptions
- Ignores logs from `loki_client.*` loggers to prevent infinite loops

## Monitoring

Check client health with the `stats` property:

```python
print(loki.stats)
# {
#     "sent": 1523,      # log entries successfully delivered
#     "errors": 2,       # HTTP 4xx/5xx responses
#     "dropped": 0,      # network failures + entries dropped from overflow/exhausted retries
#     "pending": 14,     # entries waiting in buffer
#     "retrying": 1,     # batches in retry queue
#     "flushes": 16,     # total flush operations
# }
```

## Lifecycle

```python
loki = Loki(endpoint="http://localhost:3100", app="myapp")

# ... log stuff ...

loki.flush()  # force-flush buffer now (also happens automatically)
loki.stop()   # stop background thread, flush remaining, close HTTP connection
```

`stop()` is also registered via `atexit`, so it runs automatically on interpreter shutdown. Calling `stop()` multiple times is safe.

## How it works

```
loki.info("msg") ──> LogEntry ──> LogBuffer (in-memory, thread-safe)
                                       │
                                       ├── batch_size reached? ──> flush
                                       ├── flush_interval elapsed? ──> flush
                                       └── manual flush() / stop() ──> flush
                                                    │
                                              LokiTransport.send()
                                                    │
                                         POST /loki/api/v1/push
                                              (gzip, auth)
                                                    │
                                              ┌─────┴─────┐
                                           success     failure
                                              │           │
                                        sent_count++   retry queue
                                                     (exponential backoff)
                                                          │
                                                   max_retries exceeded?
                                                          │
                                                        drop
```

## License

MIT
