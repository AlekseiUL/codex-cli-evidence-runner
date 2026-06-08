# Endurance protocol

For 30+ minute runs, run Walter in background from your orchestrator and use notification-on-complete.

`--timeout` is Codex execution time. `--verification-timeout` is per verification command. The wrapper calculates a larger parent timeout so receipt/report generation is not killed early.
