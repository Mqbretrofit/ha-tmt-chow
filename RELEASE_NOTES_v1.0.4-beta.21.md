# TMT Chow v1.0.4-beta.21

This beta cleans up the four unavailable PS19001 parameter entities left in Home Assistant by the earlier, incorrect 23-slot profile.

On integration startup, the migration removes only `parameter_20` through `parameter_23` when all of the following are true:

- the live controller is PS19001;
- the verified 19-slot profile is active;
- the stale entity belongs to the same config entry.

The 19 working PS19001 parameters, their existing entity IDs, all native gate control/status functions, and every other controller profile are unchanged.
