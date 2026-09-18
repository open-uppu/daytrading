"""Show that per-instance counters + 1-second timestamps collide."""
import pandas as pd

counter_a, counter_b = 1, 1  # each broker instance starts its own counter at 1
now = int(pd.Timestamp.now().timestamp())

id1 = f"cmd_mt5_{counter_a}_{now}"
id2 = f"cmd_mt5_{counter_b}_{now}"

print(f"  broker instance 1 -> {id1}")
print(f"  broker instance 2 -> {id2}")
print(f"  COLLISION: {id1 == id2}")
print()
print("  cmd_counter is per-instance (restarts at 1 per broker object) and the")
print("  timestamp has 1-second granularity. Any two brokers issuing a command")
print("  in the same second generate the SAME id.")
print()
print("  Impact: the bridge keys _execution_results by command_id and never")
print("  expires entries, so a confirmation for order A is returned as the")
print("  confirmation for order B -> false 'confirmed=True' and wrong ticket.")
